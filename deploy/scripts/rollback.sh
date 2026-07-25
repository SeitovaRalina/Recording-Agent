#!/usr/bin/env bash
set -Eeuo pipefail

readonly ROOT=/opt/recording-agent
readonly ENV_FILE=/etc/recording-agent/backend.env
readonly SKILL=/srv/openclaw/workspaces/recordings-saver/skills/recording-agent
die() { printf 'rollback: %s\n' "$*" >&2; exit 1; }
[[ ${EUID} -eq 0 ]] || die "must run through constrained sudo"
[[ $# -eq 0 ]] || die "rollback takes no arguments"
[[ -L "$ROOT/current" ]] || die "no current release"

current=$(readlink -f "$ROOT/current")
current_manifest="$current/release-manifest.json"
[[ -f $current_manifest ]] || die "current release is unowned"
previous_name=$(jq -r '.previousRelease // empty' "$current_manifest")
[[ $previous_name =~ ^[0-9a-f]{40}$ ]] || die "no previous release"
previous="$ROOT/releases/$previous_name"
[[ -f "$previous/release-manifest.json" ]] || die "previous release is unowned"
jq -e '
  .migration.previousApplicationCompatibleWithTargetSchema == true and
  .migration.failurePolicy == "automatic-application-rollback"
' "$current_manifest" >/dev/null ||
  die "schema compatibility is not declared; keep writes stopped and forward-fix"

export POSTGRES_IMAGE
POSTGRES_IMAGE=$(sed -n 's/^POSTGRES_IMAGE=//p' "$ENV_FILE")
current_image=$(jq -r '.image' "$current_manifest")
previous_image=$(jq -r '.image' "$previous/release-manifest.json")
export RECORDING_AGENT_IMAGE=$current_image
current_compose=(docker compose --project-name recording-agent --env-file "$ENV_FILE" \
  --file "$current/compose.prod.yml")
export RECORDING_AGENT_IMAGE=$previous_image
previous_compose=(docker compose --project-name recording-agent --env-file "$ENV_FILE" \
  --file "$previous/compose.prod.yml")

"${current_compose[@]}" stop backend
trap '"${current_compose[@]}" stop backend >/dev/null 2>&1 || true; printf "rollback failed; writes remain stopped\n" >&2' ERR
next="${SKILL}.next"
old="${SKILL}.old"
rm -rf -- "$next" "$old"
cp -a "$previous/skill" "$next"
touch "$next/.recording-agent-owned"
chown -R openclaw:openclaw "$next"
mv -T "$SKILL" "$old"
mv -T "$next" "$SKILL"
ln -sfn "$previous" "$ROOT/current.next"
mv -Tf "$ROOT/current.next" "$ROOT/current"
"${previous_compose[@]}" up -d --no-deps backend
/usr/local/sbin/recording-agent-smoke-test --local
rm -rf -- "$old"
trap - ERR
printf 'rolled back to %s; database was not restored\n' "$previous_name"
