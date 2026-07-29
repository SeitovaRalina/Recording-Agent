#!/usr/bin/env bash
set -Eeuo pipefail

readonly OPENCLAW=/opt/openclaw/bin/openclaw
readonly GATEWAY_ENV=/etc/openclaw/gateway.env
readonly JOB_NAME=recordings-saver-routing-dispatch
readonly COMMAND=/usr/local/sbin/recording-agent-routing-dispatch

die() { printf 'routing-cron-admin: %s\n' "$*" >&2; exit 1; }
[[ ${EUID} -eq 0 ]] || die "run as root"
[[ $# -eq 1 && $1 =~ ^(install|remove|status|run|preflight)$ ]] ||
  die "usage: recording-agent-routing-cron-admin install|remove|status|run|preflight"
[[ -x $OPENCLAW && -x $COMMAND ]] || die "required executable is unavailable"
[[ -f $GATEWAY_ENV && ! -L $GATEWAY_ENV &&
  $(stat -c '%a:%U:%G' "$GATEWAY_ENV") == 600:root:root ]] ||
  die "Gateway environment must be root-owned mode 0600"

run_openclaw() {
  systemd-run --quiet --wait --pipe --collect \
    --uid=openclaw --gid=openclaw \
    --property="EnvironmentFile=$GATEWAY_ENV" \
    --setenv=HOME=/var/lib/openclaw \
    --setenv=OPENCLAW_STATE_DIR=/var/lib/openclaw \
    --setenv=OPENCLAW_CONFIG_PATH=/etc/openclaw/openclaw.json \
    "$OPENCLAW" "$@"
}

gateway_client_preflight() {
  local gateway_token
  gateway_token=$(sed -n -E 's/^OPENCLAW_GATEWAY_TOKEN=([0-9a-f]{64})$/\1/p' "$GATEWAY_ENV")
  [[ $gateway_token =~ ^[0-9a-f]{64}$ ]] || die "Gateway client token is unavailable"
  systemctl is-active --quiet openclaw-gateway.service || die "Gateway service is inactive"
  systemd-run --quiet --wait --pipe --collect \
    --uid=openclaw --gid=openclaw \
    --setenv=HOME=/var/lib/openclaw \
    --setenv=OPENCLAW_STATE_DIR=/var/lib/openclaw \
    --setenv=OPENCLAW_CONFIG_PATH=/etc/openclaw/openclaw.json \
    --setenv=OPENCLAW_GATEWAY_URL=ws://127.0.0.1:18789 \
    --setenv="OPENCLAW_GATEWAY_TOKEN=$gateway_token" \
    "$OPENCLAW" gateway status --require-rpc >/dev/null
  systemd-run --quiet --wait --pipe --collect \
    --uid=openclaw --gid=openclaw \
    --setenv=HOME=/var/lib/openclaw \
    --setenv=OPENCLAW_STATE_DIR=/var/lib/openclaw \
    --setenv=OPENCLAW_CONFIG_PATH=/etc/openclaw/openclaw.json \
    --setenv=OPENCLAW_GATEWAY_URL=ws://127.0.0.1:18789 \
    --setenv="OPENCLAW_GATEWAY_TOKEN=$gateway_token" \
    "$OPENCLAW" agents list --bindings --json |
    jq -e '.. | objects | select(.id? == "recordings-saver")' >/dev/null ||
    die "Recordings Saver is not available through Gateway RPC"
}

job_id() {
  run_openclaw cron list --all --json |
    jq -er --arg name "$JOB_NAME" '.jobs[]? | select(.name == $name) | .id' | head -n 1
}

case $1 in
  install)
    if existing=$(job_id 2>/dev/null); then
      run_openclaw cron remove "$existing" >/dev/null
    fi
    run_openclaw cron create '*/2 * * * *' \
      --name "$JOB_NAME" \
      --command-argv "[\"$COMMAND\"]" \
      --command-cwd / \
      --timeout-seconds 180 \
      --no-output-timeout-seconds 180 \
      --output-max-bytes 4096 \
      --no-deliver >/dev/null
    ;;
  remove)
    if existing=$(job_id 2>/dev/null); then
      run_openclaw cron remove "$existing" >/dev/null
    fi
    ;;
  status)
    existing=$(job_id) || die "routing cron job is not installed"
    run_openclaw cron show "$existing" --json
    ;;
  run)
    existing=$(job_id) || die "routing cron job is not installed"
    run_openclaw cron run "$existing" --wait --wait-timeout 5m --poll-interval 2s
    ;;
  preflight)
    gateway_client_preflight
    ;;
esac
