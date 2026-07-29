#!/usr/bin/env bash
set -Eeuo pipefail

readonly ROOT=/opt/recording-agent
readonly ENV_FILE=/etc/recording-agent/backend.env
readonly PROJECT=recording-agent
readonly WORKSPACE_SKILL=/srv/openclaw/workspaces/recordings-saver/skills/recording-agent
readonly MIN_AVAILABLE_KIB=393216

failure_trap_armed=false
die() {
  printf 'deploy: %s\n' "$*" >&2
  if [[ $failure_trap_armed == true ]]; then
    return 1
  fi
  exit 1
}

if [[ ${EUID} -ne 0 ]]; then
  [[ $# -eq 0 && -n ${SSH_ORIGINAL_COMMAND:-} ]] ||
    die "deploy identity accepts only its forced SSH command"
  [[ $SSH_ORIGINAL_COMMAND =~ ^sudo\ -n\ /usr/local/sbin/recording-agent-deploy\ ([0-9a-f]{40})\ (ghcr\.io/seitovaralina/recording-agent@sha256:[0-9a-f]{64})\ ([0-9a-f]{64})\ ([0-9a-f]{64})\ ([0-9a-f]{64})$ ]] ||
    die "rejected SSH command"
  exec sudo -n /usr/local/sbin/recording-agent-deploy \
    "${BASH_REMATCH[1]}" "${BASH_REMATCH[2]}" "${BASH_REMATCH[3]}" \
    "${BASH_REMATCH[4]}" "${BASH_REMATCH[5]}"
fi

[[ $# -eq 5 ]] ||
  die "usage: recording-agent-deploy COMMIT IMAGE COMPOSE_SHA SKILL_SHA METADATA_SHA"
commit=$1
image=$2
compose_sha=$3
skill_sha=$4
metadata_sha=$5
[[ $commit =~ ^[0-9a-f]{40}$ ]] || die "invalid commit"
[[ $image =~ ^ghcr\.io/seitovaralina/recording-agent@sha256:[0-9a-f]{64}$ ]] ||
  die "image must be the allowlisted GHCR repository pinned by digest"
for digest in "$compose_sha" "$skill_sha" "$metadata_sha"; do
  [[ $digest =~ ^[0-9a-f]{64}$ ]] || die "invalid artifact digest"
done
[[ -f $ENV_FILE ]] || die "missing protected runtime environment"
[[ $(stat -c '%a:%U' "$ENV_FILE") == 600:root ]] ||
  die "runtime environment must be root-owned mode 0600"
[[ $(awk '/MemAvailable:/ { print $2 }' /proc/meminfo) -ge $MIN_AVAILABLE_KIB ]] ||
  die "pre-deploy capacity gate failed: less than 384 MiB available"
[[ $(awk '/SwapTotal:/ { print $2 }' /proc/meminfo) -eq 0 ]] ||
  die "host capacity drift: rollout was approved for no swap"

release="$ROOT/releases/$commit"
manifest="$release/release-manifest.json"
if [[ -f $manifest ]]; then
  jq -e \
    --arg commit "$commit" --arg image "$image" --arg compose "$compose_sha" \
    --arg skill "$skill_sha" --arg metadata "$metadata_sha" '
      .schemaVersion == 1 and .status == "deployed" and
      .commit == $commit and .image == $image and
      .artifacts.composeSha256 == $compose and
      .artifacts.skillSha256 == $skill and
      .artifacts.migrationMetadataSha256 == $metadata
    ' "$manifest" >/dev/null || die "existing release manifest does not match command"
  [[ $(readlink -f "$ROOT/current") == "$release" ]] ||
    die "release is recorded as deployed but is not current"
  exec /usr/local/sbin/recording-agent-smoke-test --local
fi

incoming="$ROOT/sftp/incoming/$commit"
staged="$ROOT/staging/$commit"
[[ -d $incoming ]] || die "missing staged release directory"
if [[ ! -d $staged ]]; then
  install -d -o root -g root -m 0700 "$staged"
  cp -a "$incoming/." "$staged/"
  chown -R root:root "$staged"
fi
for name in compose.prod.yml recording-agent-skill.tar.gz release-metadata.json; do
  [[ -f "$staged/$name" && ! -L "$staged/$name" ]] || die "missing or unsafe staged $name"
done
staged_files=$(find "$staged" -mindepth 1 -maxdepth 1 -type f -printf '%f\n')
if grep -Ev '^(compose\.prod\.yml|compose\.prod\.yml\.sha256|recording-agent-skill\.tar\.gz|recording-agent-skill\.tar\.gz\.sha256|release-metadata\.json)$' \
  <<<"$staged_files" | grep -q .; then
  die "unexpected staged files"
fi
[[ $(sha256sum "$staged/compose.prod.yml" | awk '{print $1}') == "$compose_sha" ]] ||
  die "Compose digest does not match authenticated command"
[[ $(sha256sum "$staged/recording-agent-skill.tar.gz" | awk '{print $1}') == "$skill_sha" ]] ||
  die "skill digest does not match authenticated command"
[[ $(sha256sum "$staged/release-metadata.json" | awk '{print $1}') == "$metadata_sha" ]] ||
  die "migration metadata digest does not match authenticated command"

jq -e '
  .schemaVersion == 1 and
  (.targetAlembicRevision | test("^[0-9A-Za-z_]{1,64}$")) and
  (.previousApplicationCompatibleWithTargetSchema | type == "boolean") and
  (.reviewPolicy == "code-owner-and-production-environment-approver") and
  (.rationale | type == "string" and length >= 20) and
  ((.previousApplicationCompatibleWithTargetSchema == true and
    .migrationStrategy == "expand-contract" and
    .failurePolicy == "automatic-application-rollback") or
   (.previousApplicationCompatibleWithTargetSchema == false and
    .migrationStrategy == "forward-only" and
    .failurePolicy == "stop-writes-forward-fix"))
' "$staged/release-metadata.json" >/dev/null || die "invalid migration compatibility metadata"
compatible=$(jq -r '.previousApplicationCompatibleWithTargetSchema' \
  "$staged/release-metadata.json")
target_revision=$(jq -r '.targetAlembicRevision' "$staged/release-metadata.json")

archive_listing=$(tar -tzf "$staged/recording-agent-skill.tar.gz")
[[ -n $archive_listing ]] || die "skill archive is empty"
grep -Eq '(^/|(^|/)\.\.(/|$))' <<<"$archive_listing" &&
  die "unsafe skill archive path"
grep -Ev '^recording-agent(/|$)' <<<"$archive_listing" | grep -q . &&
  die "skill archive has an unexpected root"
archive_verbose=$(tar -tvzf "$staged/recording-agent-skill.tar.gz")
grep -Eq '^[lh]' <<<"$archive_verbose" && die "skill archive links are forbidden"

if [[ -e $release ]]; then
  [[ ! -f $manifest ]] || die "existing release collision"
  rm -rf -- "$release"
fi
install -d -o root -g root -m 0755 "$release"
install -o root -g root -m 0644 "$staged/compose.prod.yml" "$release/compose.prod.yml"
install -o root -g root -m 0444 "$staged/release-metadata.json" \
  "$release/release-metadata.json"
install -d -o openclaw -g openclaw -m 0750 "$release/skill"
tar -xzf "$staged/recording-agent-skill.tar.gz" --strip-components=1 \
  --no-same-owner --no-same-permissions -C "$release/skill"
[[ -f "$release/skill/SKILL.md" ]] || die "skill archive has an unexpected root"
chown -R openclaw:openclaw "$release/skill"

if [[ -e $WORKSPACE_SKILL && ! -f "$WORKSPACE_SKILL/.recording-agent-owned" ]]; then
  die "skill collision: existing subtree lacks ownership marker"
fi

export RECORDING_AGENT_IMAGE=$image
export POSTGRES_IMAGE
POSTGRES_IMAGE=$(sed -n 's/^POSTGRES_IMAGE=//p' "$ENV_FILE")
[[ $POSTGRES_IMAGE =~ ^[a-z0-9./_-]+@sha256:[0-9a-f]{64}$ ]] ||
  die "POSTGRES_IMAGE must be pinned by digest"
compose=(docker compose --project-name "$PROJECT" --env-file "$ENV_FILE" \
  --file "$release/compose.prod.yml")
"${compose[@]}" config --quiet
"${compose[@]}" pull
migration_cli=(poetry run alembic)
if ! candidate_heads=$("${compose[@]}" run -T --rm --no-deps migrate \
  "${migration_cli[@]}" heads 2>/dev/null); then
  die "candidate Alembic head probe failed"
fi
candidate_head_lines=$(grep -Ec '^[0-9A-Za-z_]{1,64} \(head\)$' \
  <<<"$candidate_heads" || true)
nonempty_head_lines=$(grep -Ec '.+' <<<"$candidate_heads" || true)
[[ $candidate_head_lines -eq 1 && $nonempty_head_lines -eq 1 ]] ||
  die "candidate image must expose exactly one Alembic head"
candidate_head=${candidate_heads% (head)}
[[ $candidate_head == "$target_revision" ]] ||
  die "candidate Alembic head does not match authenticated release metadata"

previous=
if [[ -L "$ROOT/current" ]]; then
  previous=$(readlink -f "$ROOT/current")
  [[ $previous == "$ROOT/releases/"* && -f "$previous/release-manifest.json" ]] ||
    die "current release is not owned"
fi
quiesced=false
deploy_started_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
oom_baseline=$(awk '/oom_kill / { print $2 }' /proc/vmstat)
[[ $oom_baseline =~ ^[0-9]+$ ]] || die "kernel OOM counter is unavailable"
migration_attempted=false

activate_skill() {
  local source_release=$1
  local next="${WORKSPACE_SKILL}.next"
  local old="${WORKSPACE_SKILL}.old"
  rm -rf -- "$next" "$old"
  cp -a "$source_release/skill" "$next"
  touch "$next/.recording-agent-owned"
  chown -R openclaw:openclaw "$next"
  if [[ -e $WORKSPACE_SKILL ]]; then
    mv -T "$WORKSPACE_SKILL" "$old"
  fi
  mv -T "$next" "$WORKSPACE_SKILL"
  rm -rf -- "$old"
}

recover_previous() {
  [[ -n $previous && -f "$previous/release-manifest.json" ]] || return 1
  local previous_image
  previous_image=$(jq -r '.image' "$previous/release-manifest.json")
  [[ $previous_image =~ ^ghcr\.io/seitovaralina/recording-agent@sha256:[0-9a-f]{64}$ ]] ||
    return 1
  export RECORDING_AGENT_IMAGE=$previous_image
  local previous_compose=(docker compose --project-name "$PROJECT" --env-file "$ENV_FILE" \
    --file "$previous/compose.prod.yml")
  "${compose[@]}" stop backend >/dev/null 2>&1 || true
  ln -sfn "$previous" "$ROOT/current.next"
  mv -Tf "$ROOT/current.next" "$ROOT/current"
  activate_skill "$previous"
  "${previous_compose[@]}" up -d --no-deps backend
  CAPACITY_OOM_KILL_BASELINE="$oom_baseline" \
    /usr/local/sbin/recording-agent-smoke-test --local
}

handle_failure() {
  local rc=$?
  trap - ERR
  set +e
  failure_trap_armed=false
  if [[ $quiesced == true ]]; then
    if [[ $migration_attempted == false || $compatible == true ]] && recover_previous; then
      printf 'deploy failed; previous schema-compatible application release restored\n' >&2
    else
      "${compose[@]}" stop backend >/dev/null 2>&1
      install -d -o root -g root -m 0700 "$ROOT/failures"
      printf 'commit=%s\nfailed_at=%s\npolicy=stop-writes-forward-fix\n' \
        "$commit" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        >"$ROOT/failures/$commit"
      chmod 0600 "$ROOT/failures/$commit"
      printf 'deploy failed; writes remain stopped; forward-fix or approve restore\n' >&2
    fi
  fi
  exit "$rc"
}
failure_trap_armed=true
trap handle_failure ERR

if [[ -n $previous ]]; then
  previous_image=$(jq -r '.image' "$previous/release-manifest.json")
  export RECORDING_AGENT_IMAGE=$previous_image
  docker compose --project-name "$PROJECT" --env-file "$ENV_FILE" \
    --file "$previous/compose.prod.yml" stop backend
else
  "${compose[@]}" stop backend >/dev/null 2>&1 || true
fi
quiesced=true
export RECORDING_AGENT_IMAGE=$image

timestamp=$(date -u +%Y%m%dT%H%M%SZ)
backup="/var/backups/recording-agent/${timestamp}-${commit}.dump"
"${compose[@]}" up -d --wait --wait-timeout 70 postgres
"${compose[@]}" exec -T postgres sh -eu -c \
  'PGPASSWORD="$POSTGRES_PASSWORD" pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' >"$backup"
[[ -s $backup ]] || die "database backup is empty"
"${compose[@]}" exec -T postgres pg_restore --list <"$backup" >/dev/null ||
  die "database backup verification failed"

migration_attempted=true
"${compose[@]}" run -T --rm migrate "${migration_cli[@]}" upgrade head
ln -sfn "$release" "$ROOT/current.next"
mv -Tf "$ROOT/current.next" "$ROOT/current"
activate_skill "$release"
"${compose[@]}" up -d --no-deps backend
CAPACITY_OOM_KILL_BASELINE="$oom_baseline" \
  /usr/local/sbin/recording-agent-smoke-test --local

previous_json=null
[[ -z $previous ]] || previous_json=$(printf '%s' "$(basename "$previous")" | jq -R .)
jq -n \
  --arg commit "$commit" --arg image "$image" \
  --arg compose "$compose_sha" --arg skill "$skill_sha" --arg metadata "$metadata_sha" \
  --arg deployed_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --arg started_at "$deploy_started_at" \
  --argjson previous "$previous_json" \
  --slurpfile migration "$release/release-metadata.json" '{
    schemaVersion: 1,
    status: "deployed",
    commit: $commit,
    image: $image,
    artifacts: {
      composeSha256: $compose,
      skillSha256: $skill,
      migrationMetadataSha256: $metadata
    },
    migration: $migration[0],
    previousRelease: $previous,
    startedAt: $started_at,
    deployedAt: $deployed_at
  }' >"$manifest.next"
chown root:root "$manifest.next"
chmod 0444 "$manifest.next"
mv -Tf "$manifest.next" "$manifest"
printf '%s\n' "${previous:-none}" >"$ROOT/previous-release"
chmod 0600 "$ROOT/previous-release"
failure_trap_armed=false
trap - ERR
rm -rf -- "$staged" "$incoming" || true
printf 'deployed %s\n' "$commit"
