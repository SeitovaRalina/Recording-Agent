#!/usr/bin/env bash
set -Eeuo pipefail

readonly BACKEND_URL="${RECORDING_AGENT_BACKEND_URL:-http://127.0.0.1:18000}"
readonly GATEWAY_URL=ws://127.0.0.1:18789
readonly OPENCLAW=/opt/openclaw/bin/openclaw
readonly LOCK=/var/lib/openclaw/run/recording-agent-routing-dispatch.lock
readonly ROUTING_ENV=/etc/openclaw/recording-agent-routing.env

die() { printf 'routing-dispatch: %s\n' "$*" >&2; exit 1; }
[[ $BACKEND_URL =~ ^http://(127\.0\.0\.1|\[::1\]|localhost)(:[0-9]{1,5})?$ ]] ||
  die "backend URL must be loopback"
[[ -x $OPENCLAW ]] || die "OpenClaw CLI is unavailable"
[[ -f $ROUTING_ENV && ! -L $ROUTING_ENV &&
  $(stat -c '%a:%U:%G' "$ROUTING_ENV") == 640:root:openclaw ]] ||
  die "Routing environment must be root-owned mode 0640 for group openclaw"
OPENCLAW_SECRET=$(sed -n 's/^OPENCLAW_SECRET=//p' "$ROUTING_ENV" | tr -d '\r')
OPENCLAW_GATEWAY_TOKEN=$(
  sed -n -E 's/^OPENCLAW_GATEWAY_TOKEN=([0-9a-f]{64})\r?$/\1/p' "$ROUTING_ENV"
)
[[ -n ${OPENCLAW_SECRET:-} ]] || die "OPENCLAW_SECRET is required"
[[ ${OPENCLAW_GATEWAY_TOKEN:-} =~ ^[0-9a-f]{64}$ ]] ||
  die "OPENCLAW_GATEWAY_TOKEN is required"

umask 0077
exec 9>"$LOCK"
if ! flock -n 9; then
  printf 'NO_REPLY\n'
  exit 0
fi

payload=$(curl --config - <<EOF
fail
silent
show-error
max-time = 15
request = POST
header = "Accept: application/json"
header = "X-OpenClaw-Secret: ${OPENCLAW_SECRET}"
url = "${BACKEND_URL}/internal/routing-jobs/dispatch"
EOF
)

if [[ $payload == null ]]; then
  printf 'NO_REPLY\n'
  exit 0
fi
job_id=$(jq -er '.job_id | strings | select(test("^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"))' <<<"$payload") ||
  die "dispatch returned an invalid job id"
dispatch_nonce=$(jq -er '.dispatch_nonce | strings | select(test("^[A-Za-z0-9_-]{16,512}$"))' <<<"$payload") ||
  die "dispatch returned an invalid nonce"

session_key="autonomous-routing-${job_id}-$(date -u +%s)-$$"
message=$(printf 'AUTONOMOUS_ROUTING_V1\njob_id=%s\ndispatch_nonce=%s\nRead references/autonomous-routing.md and return NO_REPLY.' \
  "$job_id" "$dispatch_nonce")
env -i \
  PATH="$PATH" \
  HOME="${HOME:-/var/lib/openclaw}" \
  OPENCLAW_STATE_DIR="${OPENCLAW_STATE_DIR:-/var/lib/openclaw}" \
  OPENCLAW_CONFIG_PATH="${OPENCLAW_CONFIG_PATH:-/etc/openclaw/openclaw.json}" \
  OPENCLAW_GATEWAY_URL="$GATEWAY_URL" \
  OPENCLAW_GATEWAY_TOKEN="$OPENCLAW_GATEWAY_TOKEN" \
  RECORDING_AGENT_BACKEND_URL="$BACKEND_URL" \
  "$OPENCLAW" agent --agent recordings-saver --session-key "$session_key" \
  --message "$message" --timeout 150 --json >/dev/null
printf 'NO_REPLY\n'
