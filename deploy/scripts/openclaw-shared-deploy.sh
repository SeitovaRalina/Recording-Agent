#!/usr/bin/env bash
set -Eeuo pipefail

readonly ROOT=/opt/recording-agent
readonly CONFIG=/etc/openclaw/openclaw.json
readonly INVENTORY=/etc/openclaw/agents.yml
readonly MANIFEST=/etc/openclaw/shared-release-manifest.json
readonly OPENCLAW=/opt/openclaw/bin/openclaw
readonly GATEWAY_ENV=/etc/openclaw/gateway.env

die() { printf 'openclaw-shared-deploy: %s\n' "$*" >&2; exit 1; }

if [[ ${EUID} -ne 0 ]]; then
  [[ $# -eq 0 && -n ${SSH_ORIGINAL_COMMAND:-} ]] ||
    die "shared deploy identity accepts only its forced SSH command"
  [[ $SSH_ORIGINAL_COMMAND =~ ^sudo\ -n\ /usr/local/sbin/openclaw-shared-deploy\ ([0-9a-f]{40})\ ([0-9a-f]{64})\ ([0-9a-f]{64})$ ]] ||
    die "rejected SSH command"
  exec sudo -n /usr/local/sbin/openclaw-shared-deploy \
    "${BASH_REMATCH[1]}" "${BASH_REMATCH[2]}" "${BASH_REMATCH[3]}"
fi

[[ $# -eq 3 ]] ||
  die "usage: openclaw-shared-deploy COMMIT CONFIG_SHA INVENTORY_SHA"
commit=$1
config_sha=$2
inventory_sha=$3
[[ $commit =~ ^[0-9a-f]{40}$ ]] || die "invalid commit"
[[ $config_sha =~ ^[0-9a-f]{64}$ && $inventory_sha =~ ^[0-9a-f]{64}$ ]] ||
  die "invalid artifact digest"

incoming="$ROOT/sftp/shared-incoming/$commit"
staged="$ROOT/shared-staging/$commit"
[[ -f "$incoming/openclaw.json" && ! -L "$incoming/openclaw.json" ]] ||
  die "missing staged OpenClaw config"
[[ -f "$incoming/agents.yml" && ! -L "$incoming/agents.yml" ]] ||
  die "missing staged agent inventory"
if [[ ! -d $staged ]]; then
  install -d -o root -g openclaw -m 0750 "$staged"
  install -o root -g openclaw -m 0640 "$incoming/openclaw.json" "$staged/openclaw.json"
  install -o root -g root -m 0600 "$incoming/agents.yml" "$staged/agents.yml"
fi
[[ $(sha256sum "$staged/openclaw.json" | awk '{print $1}') == "$config_sha" ]] ||
  die "config digest does not match authenticated command"
[[ $(sha256sum "$staged/agents.yml" | awk '{print $1}') == "$inventory_sha" ]] ||
  die "inventory digest does not match authenticated command"
jq -e . "$staged/openclaw.json" >/dev/null || die "candidate config must be strict JSON"

validate_routes() {
  local candidate=$1
  jq -e '
    . as $root |
    ([$root.agents.list[].id] | length >= 1) and
    (([$root.agents.list[].id] | unique | length) ==
      ([$root.agents.list[].id] | length)) and
    (([$root.agents.list[].workspace] | unique | length) ==
      ([$root.agents.list[].workspace] | length)) and
    (([$root.agents.list[].agentDir] | unique | length) ==
      ([$root.agents.list[].agentDir] | length)) and
    (all($root.agents.list[]; (.default // false) == false)) and
    (all($root.bindings[] | select(.match.channel == "mattermost");
      .agentId == .match.accountId)) and
    ([$root.bindings[] |
      select(.agentId == "*" or .match.channel == "*" or .match.accountId == "*")
    ] | length == 0)
  ' "$candidate" >/dev/null || return 1
  diff -u \
    <(jq -r '.channels.mattermost.accounts | keys[]' "$candidate" | sort) \
    <(jq -r '.bindings[] | select(.match.channel == "mattermost") | .match.accountId' \
      "$candidate" | sort) >/dev/null || return 1
  diff -u \
    <(jq -r '.agents.list[].id' "$candidate" | sort) \
    <(jq -r '.bindings[] | select(.match.channel == "mattermost") | .agentId' \
      "$candidate" | sort) >/dev/null || return 1
}
validate_routes "$staged/openclaw.json" ||
  die "candidate failed explicit positive/negative routing regression"

if [[ -e $CONFIG || -e $INVENTORY ]]; then
  [[ -f $CONFIG && ! -L $CONFIG && -f $INVENTORY && ! -L $INVENTORY ]] ||
    die "partial or unsafe pre-existing shared config is not adoptable"
  [[ -f $MANIFEST && ! -L $MANIFEST ]] ||
    die "pre-existing shared config requires a valid managed manifest"
fi
if [[ -f $MANIFEST ]]; then
  [[ $(stat -c '%a:%U:%G' "$MANIFEST") == 444:root:root ]] ||
    die "shared manifest must be root-owned mode 0444"
  jq -e '
    .schemaVersion == 1 and
    (.commit | test("^[0-9a-f]{40}$")) and
    (.configSha256 | test("^[0-9a-f]{64}$")) and
    (.inventorySha256 | test("^[0-9a-f]{64}$")) and
    (.appliedAt | type == "string" and length > 0)
  ' "$MANIFEST" >/dev/null || die "invalid managed shared manifest"
  [[ -f $CONFIG && -f $INVENTORY ]] || die "managed shared files are missing"
  expected_config=$(jq -r '.configSha256' "$MANIFEST")
  expected_inventory=$(jq -r '.inventorySha256' "$MANIFEST")
  [[ $(sha256sum "$CONFIG" | awk '{print $1}') == "$expected_config" ]] ||
    die "unexpected live OpenClaw config drift"
  [[ $(sha256sum "$INVENTORY" | awk '{print $1}') == "$expected_inventory" ]] ||
    die "unexpected live agent inventory drift"
elif [[ -e $CONFIG || -e $INVENTORY ]]; then
  die "unmanaged shared config adoption is forbidden"
fi

if [[ -f $CONFIG ]]; then
  jq -e --slurpfile candidate "$staged/openclaw.json" '
    . as $live |
    all($live.agents.list[]; . as $old |
      any($candidate[0].agents.list[]; .id == $old.id and . == $old)) and
    all(($live.channels.mattermost.accounts | to_entries[]); . as $old |
      any(($candidate[0].channels.mattermost.accounts | to_entries[]);
        .key == $old.key and .value == $old.value)) and
    all($live.bindings[]; . as $old | any($candidate[0].bindings[]; . == $old))
  ' "$CONFIG" >/dev/null ||
    die "candidate changes or omits an existing agent, account, or binding"
fi
if [[ -f $INVENTORY ]]; then
  live_size=$(stat -c '%s' "$INVENTORY")
  [[ $(stat -c '%s' "$staged/agents.yml") -ge $live_size ]] ||
    die "candidate inventory truncates live ownership"
  cmp -n "$live_size" "$INVENTORY" "$staged/agents.yml" ||
    die "candidate inventory is not an additive extension"
fi

[[ -f $GATEWAY_ENV && ! -L $GATEWAY_ENV &&
  $(stat -c '%a:%U:%G' "$GATEWAY_ENV") == 600:root:root ]] ||
  die "Gateway environment must be root-owned mode 0600"
gateway_token=$(sed -n -E 's/^OPENCLAW_GATEWAY_TOKEN=([0-9a-f]{64})$/\1/p' "$GATEWAY_ENV")
[[ $gateway_token =~ ^[0-9a-f]{64}$ ]] ||
  die "Gateway environment must contain a valid OPENCLAW_GATEWAY_TOKEN"
mattermost_url=$(sed -n 's/^MATTERMOST_URL=//p' "$GATEWAY_ENV")
mattermost_token=$(sed -n 's/^RECORDINGS_SAVER_MATTERMOST_BOT_TOKEN=//p' "$GATEWAY_ENV")
recruiter_user_id=$(sed -n 's/^RECORDINGS_SAVER_RECRUITER_USER_ID=//p' "$GATEWAY_ENV")
[[ -n $mattermost_url && -n $mattermost_token && -n $recruiter_user_id ]] ||
  die "Gateway environment is missing Recordings Saver Mattermost settings"
run_openclaw() {
  local config_path=$1
  shift
  systemd-run --quiet --wait --pipe --collect \
    --uid=openclaw --gid=openclaw \
    --setenv="OPENCLAW_GATEWAY_TOKEN=$gateway_token" \
    --setenv="MATTERMOST_URL=$mattermost_url" \
    --setenv="RECORDINGS_SAVER_MATTERMOST_BOT_TOKEN=$mattermost_token" \
    --setenv="RECORDINGS_SAVER_RECRUITER_USER_ID=$recruiter_user_id" \
    /usr/bin/env \
    HOME=/var/lib/openclaw \
    OPENCLAW_STATE_DIR=/var/lib/openclaw \
    OPENCLAW_CONFIG_PATH="$config_path" \
    "$OPENCLAW" "$@"
}
candidate_config="$CONFIG.candidate-$commit"
install -o root -g openclaw -m 0640 "$staged/openclaw.json" "$candidate_config"
run_openclaw "$candidate_config" config validate --json >/dev/null || {
  rm -f -- "$candidate_config"
  die "pinned OpenClaw rejected candidate config"
}
rm -f -- "$candidate_config"

backup="$ROOT/shared-backups/$(date -u +%Y%m%dT%H%M%SZ)-$commit"
install -d -o root -g root -m 0700 "$backup"
[[ ! -f $CONFIG ]] || cp -a "$CONFIG" "$backup/openclaw.json"
[[ ! -f $INVENTORY ]] || cp -a "$INVENTORY" "$backup/agents.yml"
[[ ! -f $MANIFEST ]] || cp -a "$MANIFEST" "$backup/shared-release-manifest.json"
if systemctl is-active --quiet openclaw-gateway.service; then
  run_openclaw "$CONFIG" agents list --bindings --json >"$backup/live-bindings.json"
  chmod 0600 "$backup/live-bindings.json"
fi

restore_previous() {
  trap - ERR
  set +e
  if [[ -f "$backup/openclaw.json" ]]; then
    install -o root -g openclaw -m 0640 "$backup/openclaw.json" "$CONFIG"
  else
    rm -f -- "$CONFIG"
  fi
  if [[ -f "$backup/agents.yml" ]]; then
    install -o root -g root -m 0600 "$backup/agents.yml" "$INVENTORY"
  else
    rm -f -- "$INVENTORY"
  fi
  if [[ -f "$backup/shared-release-manifest.json" ]]; then
    install -o root -g root -m 0444 "$backup/shared-release-manifest.json" "$MANIFEST"
  else
    rm -f -- "$MANIFEST"
  fi
  systemctl restart openclaw-gateway.service
  printf 'shared rollout failed; previous config restored\n' >&2
  exit 1
}
trap restore_previous ERR

install -o root -g openclaw -m 0640 "$staged/openclaw.json" "$CONFIG.next"
install -o root -g root -m 0600 "$staged/agents.yml" "$INVENTORY.next"
mv -Tf "$CONFIG.next" "$CONFIG"
mv -Tf "$INVENTORY.next" "$INVENTORY"
systemctl restart openclaw-gateway.service
systemctl is-active --quiet openclaw-gateway.service
gateway_ready=false
for _ in {1..10}; do
  if run_openclaw "$CONFIG" gateway status --require-rpc >/dev/null 2>&1; then
    gateway_ready=true
    break
  fi
  sleep 1
done
[[ $gateway_ready == true ]] || die "Gateway RPC did not become ready"
run_openclaw "$CONFIG" channels status --probe >/dev/null
validate_routes "$CONFIG"

jq -n \
  --arg commit "$commit" --arg config "$config_sha" --arg inventory "$inventory_sha" \
  --arg applied_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" '{
    schemaVersion: 1,
    commit: $commit,
    configSha256: $config,
    inventorySha256: $inventory,
    appliedAt: $applied_at
  }' >"$MANIFEST.next"
chown root:root "$MANIFEST.next"
chmod 0444 "$MANIFEST.next"
mv -Tf "$MANIFEST.next" "$MANIFEST"
trap - ERR
rm -rf -- "$staged" "$incoming" || true
printf 'shared OpenClaw config deployed %s\n' "$commit"
