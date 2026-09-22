#!/usr/bin/env bash
set -Eeuo pipefail

die() { printf 'canary-deploy: %s\n' "$*" >&2; exit 1; }
readonly ROOT=/opt/recording-agent-canary
readonly ENV_FILE=/etc/recording-agent/canary/backend.env
readonly PROXY_ENV_FILE=/etc/recording-agent/canary/notion-proxy.env
readonly PROJECT=recording-agent-canary
readonly MIN_AVAILABLE_KIB=1179648
readonly CANARY_RESERVATION_KIB=786432
[[ ${EUID} -eq 0 ]] || die "must be invoked by root"
[[ $# -eq 3 ]] || die "usage: canary-deploy COMMIT IMAGE ARCHIVE_SHA256"
commit=$1
image=$2
archive_sha=$3
[[ $commit =~ ^[0-9a-f]{40}$ ]] || die "commit must be a full lowercase SHA"
[[ $image =~ ^ghcr\.io/seitovaralina/recording-agent@sha256:[0-9a-f]{64}$ ]] || die "image must be a pinned allowlisted digest"
[[ $archive_sha =~ ^[0-9a-f]{64}$ ]] || die "invalid archive digest"
[[ ! -e $ROOT || ! -L $ROOT ]] || die "canary root must not be a symlink"
for file in "$ENV_FILE" "$PROXY_ENV_FILE"; do
  [[ -f $file && ! -L $file ]] || die "missing protected environment file"
  [[ $(stat -c '%a:%U:%G' "$file") == 600:root:root ]] || die "environment files must be root-owned mode 0600"
done
grep -qx 'TEST_MODE_ENABLED=true' "$ENV_FILE" || die "test mode must be enabled"
for setting in SCHEDULER_ENABLED AUTONOMOUS_ROUTING_ENABLED NOTION_WRITES_ENABLED MATTERMOST_DELIVERY_ENABLED YANDEX_SOURCE_MUTATION_ENABLED; do
  grep -qx "${setting}=false" "$ENV_FILE" || die "$setting must be false"
done
grep -qx 'STORAGE_PROVIDER=minio' "$ENV_FILE" || die "canary storage must be MinIO"
grep -qx 'POSTGRES_DB=recording_agent_canary' "$ENV_FILE" || die "canary database name is required"
grep -qx 'POSTGRES_USER=recording_agent_canary' "$ENV_FILE" || die "canary database user is required"
grep -Eq '^TEST_RECRUITER_ALLOWLIST=\[[^]]+\]$' "$ENV_FILE" || die "test recruiter allowlist is required"
grep -Eq '^TEST_NOTION_DATABASE_ALLOWLIST=\[[^]]+\]$' "$ENV_FILE" || die "test Notion database allowlist is required"
grep -qx 'APP_PORT=18001' "$ENV_FILE" || die "canary must use port 18001"
grep -Eq '^VPN_SUB_URL=.+$' "$PROXY_ENV_FILE" || die "VPN subscription is required"

prod_ids=$(docker ps --filter label=com.docker.compose.project=recording-agent --format '{{.ID}}')
[[ -n $prod_ids ]] || die "production Compose project is not running"
while IFS= read -r id; do
  [[ $(docker inspect --format '{{.State.Running}}' "$id") == true ]] || die "production container is not running"
done <<<"$prod_ids"
available=$(awk '/MemAvailable:/ { print $2 }' /proc/meminfo)
[[ $available =~ ^[0-9]+$ && $available -ge $MIN_AVAILABLE_KIB ]] || die "capacity gate failed: need canary reservation plus 384 MiB production headroom"
[[ $(awk '/SwapTotal:/ { print $2 }' /proc/meminfo) -eq 0 ]] || die "canary requires no-swap host profile"
[[ $CANARY_RESERVATION_KIB -eq 786432 ]] || die "internal capacity invariant failed"

incoming="$ROOT/incoming/${commit}.tar.gz"
[[ -f $incoming && ! -L $incoming ]] || die "missing canary archive"
[[ $(sha256sum "$incoming" | awk '{print $1}') == "$archive_sha" ]] || die "archive digest mismatch"
listing=$(tar -tzf "$incoming")
[[ -n $listing ]] || die "archive is empty"
grep -Eq '(^/|(^|/)\.\.(/|$))' <<<"$listing" && die "unsafe archive path"
grep -Ev '^recording-agent-canary(/|/deploy(/mihomo)?)?$|^recording-agent-canary/(compose\.canary\.yml|commit|manifest\.sha256|deploy/mihomo/(config\.yaml|entrypoint\.sh))$' <<<"$listing" | grep -q . && die "archive contains unexpected files"
verbose=$(tar -tvzf "$incoming")
grep -Eq '^[lh]' <<<"$verbose" && die "archive links are forbidden"

release="$ROOT/releases/$commit"
[[ ! -e $release ]] || die "release collision"
stage=$(mktemp -d "$ROOT/.stage.XXXXXX")
cleanup() { rm -rf -- "$stage"; }
trap cleanup EXIT
tar -xzf "$incoming" --no-same-owner --no-same-permissions -C "$stage"
[[ $(tr -d '\r' <"$stage/recording-agent-canary/commit") == "$commit" ]] || die "archive commit mismatch"
(cd "$stage/recording-agent-canary" && sha256sum -c manifest.sha256 >/dev/null) || die "manifest mismatch"
grep -Fq 'name: recording-agent-canary' "$stage/recording-agent-canary/compose.canary.yml" || die "Compose project name mismatch"
grep -Fq '/etc/recording-agent/canary/backend.env' "$stage/recording-agent-canary/compose.canary.yml" || die "Compose backend env path mismatch"
grep -Fq '/etc/recording-agent/canary/notion-proxy.env' "$stage/recording-agent-canary/compose.canary.yml" || die "Compose proxy env path mismatch"
install -d -o root -g root -m 0755 "$release"
cp -a "$stage/recording-agent-canary/." "$release/"
chown -R root:root "$release"
chmod 0444 "$release/compose.canary.yml" "$release/deploy/mihomo/config.yaml" "$release/manifest.sha256" "$release/commit"
chmod 0555 "$release/deploy/mihomo/entrypoint.sh"
export RECORDING_AGENT_IMAGE=$image
compose=(docker compose --project-name "$PROJECT" --env-file "$ENV_FILE" --file "$release/compose.canary.yml")
"${compose[@]}" config --quiet
"${compose[@]}" pull
"${compose[@]}" up -d --wait --wait-timeout 90
printf 'commit=%s\nimage=%s\narchive_sha256=%s\n' "$commit" "$image" "$archive_sha" >"$release/release-manifest"
chown root:root "$release/release-manifest"
chmod 0444 "$release/release-manifest"
ln -sfn "$release" "$ROOT/current.next"
mv -Tf "$ROOT/current.next" "$ROOT/current"
printf 'deployed canary %s\n' "$commit"
