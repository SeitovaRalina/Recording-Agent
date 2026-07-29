#!/usr/bin/env bash
set -Eeuo pipefail

die() { printf 'smoke: %s\n' "$*" >&2; exit 1; }
mode=${1:---local}
[[ $mode == --local || $mode == --external ]] || die "expected --local or --external"
readonly OPENCLAW_CONFIG=/etc/openclaw/openclaw.json
readonly RELEASE_MANIFEST=/opt/recording-agent/current/release-manifest.json
readonly MIN_AVAILABLE_KIB=393216
[[ -r $OPENCLAW_CONFIG ]] || die "OpenClaw config is unavailable"
if [[ -z ${RECORDING_AGENT_IMAGE:-} ]]; then
  [[ -r $RELEASE_MANIFEST ]] || die "current release manifest is unavailable"
  RECORDING_AGENT_IMAGE=$(jq -r '.image' "$RELEASE_MANIFEST")
fi
[[ $RECORDING_AGENT_IMAGE =~ ^ghcr\.io/seitovaralina/recording-agent@sha256:[0-9a-f]{64}$ ]] ||
  die "current release image is unavailable"
export RECORDING_AGENT_IMAGE
jq -e '
  (all(.agents.list[]; (.default // false) == false)) and
  ([.bindings[] |
    select(.agentId == "*" or .match.channel == "*" or .match.accountId == "*")
  ] | length == 0)
' "$OPENCLAW_CONFIG" >/dev/null || die "wildcard OpenClaw binding detected"
diff -u \
  <(jq -r '.channels.mattermost.accounts | keys[]' "$OPENCLAW_CONFIG" | sort) \
  <(jq -r '.bindings[] | select(.match.channel == "mattermost") | .match.accountId' \
  "$OPENCLAW_CONFIG" | sort) >/dev/null ||
  die "every Mattermost account must have exactly one explicit binding"
diff -u \
  <(jq -r '.agents.list[].id' "$OPENCLAW_CONFIG" | sort) \
  <(jq -r '.bindings[] | select(.match.channel == "mattermost") | .agentId' \
    "$OPENCLAW_CONFIG" | sort) >/dev/null ||
  die "every agent must have exactly one explicit Mattermost binding"
while IFS= read -r agent_id; do
  jq -e --arg id "$agent_id" '.agents.list | any(.id == $id)' "$OPENCLAW_CONFIG" >/dev/null ||
    die "binding references an unknown agent"
done < <(jq -r '.bindings[].agentId' "$OPENCLAW_CONFIG")

systemctl is-active --quiet openclaw-gateway.service ||
  die "OpenClaw Gateway is not active"
docker compose --project-name recording-agent \
  --env-file /etc/recording-agent/backend.env \
  --file /opt/recording-agent/current/compose.prod.yml ps --status running --quiet postgres |
  grep -q . || die "PostgreSQL is not running"
docker compose --project-name recording-agent \
  --env-file /etc/recording-agent/backend.env \
  --file /opt/recording-agent/current/compose.prod.yml ps --status running --quiet backend |
  grep -q . || die "Backend is not running"

curl --fail --silent --show-error --max-time 10 http://127.0.0.1:18000/health >/dev/null ||
  die "Backend health failed"
ss -lntH '( sport = :18000 or sport = :18789 or sport = :5432 )' |
  awk '$4 !~ /^(127\.0\.0\.1|\[::1\]):/ { exit 1 }' ||
  die "Gateway, Backend, or PostgreSQL has a non-loopback listener"

sleep 10
mem_total=$(awk '/MemTotal:/ { print $2 }' /proc/meminfo)
mem_available=$(awk '/MemAvailable:/ { print $2 }' /proc/meminfo)
swap_total=$(awk '/SwapTotal:/ { print $2 }' /proc/meminfo)
oom_now=$(awk '/oom_kill / { print $2 }' /proc/vmstat)
[[ $mem_total -ge 1800000 && $mem_total -le 2200000 ]] ||
  die "fixed-host capacity drift: expected approximately 1.9 GiB RAM"
[[ $swap_total -eq 0 ]] || die "fixed-host capacity drift: swap must remain disabled"
[[ $mem_available -ge $MIN_AVAILABLE_KIB ]] ||
  die "post-start capacity gate failed: less than 384 MiB available"
if [[ -n ${CAPACITY_OOM_KILL_BASELINE:-} ]]; then
  [[ $CAPACITY_OOM_KILL_BASELINE =~ ^[0-9]+$ ]] ||
    die "invalid OOM baseline"
  [[ $oom_now -eq $CAPACITY_OOM_KILL_BASELINE ]] ||
    die "OOM kill detected during rollout"
fi
for service in postgres backend; do
  container_id=$(docker compose --project-name recording-agent \
    --env-file /etc/recording-agent/backend.env \
    --file /opt/recording-agent/current/compose.prod.yml ps --quiet "$service")
  [[ -n $container_id ]] || die "$service container is unavailable"
  [[ $(docker inspect --format '{{.State.OOMKilled}}' "$container_id") == false ]] ||
    die "$service was OOM-killed"
done
gateway_memory=$(systemctl show openclaw-gateway.service --property=MemoryCurrent --value)
container_memory=$(docker stats --no-stream --format '{{.Name}}={{.MemUsage}}' \
  "$(docker compose --project-name recording-agent \
    --env-file /etc/recording-agent/backend.env \
    --file /opt/recording-agent/current/compose.prod.yml ps --quiet postgres)" \
  "$(docker compose --project-name recording-agent \
    --env-file /etc/recording-agent/backend.env \
    --file /opt/recording-agent/current/compose.prod.yml ps --quiet backend)" |
  paste -sd, -)
printf 'capacity: available_kib=%s gateway_bytes=%s containers=%s\n' \
  "$mem_available" "$gateway_memory" "$container_memory"

if [[ $mode == --external ]]; then
  [[ ${APPROVE_EXTERNAL_PREFLIGHTS:-} == yes ]] ||
    die "external checks require APPROVE_EXTERNAL_PREFLIGHTS=yes"
  [[ $(stat -c '%a:%U:%G' /etc/openclaw/gateway.env) == 600:root:root ]] ||
    die "Gateway environment must be root-owned mode 0600"
  openclaw_run=(
    systemd-run --quiet --wait --pipe --collect
    --uid=openclaw --gid=openclaw
    --property=EnvironmentFile=/etc/openclaw/gateway.env
    /opt/openclaw/bin/openclaw
  )
  "${openclaw_run[@]}" gateway status --require-rpc >/dev/null ||
    die "Gateway RPC preflight failed"
  "${openclaw_run[@]}" channels status --probe >/dev/null ||
    die "Mattermost account probe failed"
  while IFS= read -r agent_id; do
    "${openclaw_run[@]}" agent --agent "$agent_id" \
      --message "Reply exactly OK. Do not call tools." --timeout 120 --json >/dev/null ||
      die "$agent_id LLM preflight failed"
  done < <(jq -r '.agents.list[].id' "$OPENCLAW_CONFIG")
fi
printf 'local smoke checks passed\n'
