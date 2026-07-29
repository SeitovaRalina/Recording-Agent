#!/usr/bin/env bash
set -Eeuo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly REPO_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"

die() { printf 'install-routing-cron: %s\n' "$*" >&2; exit 1; }
[[ ${EUID} -eq 0 ]] || die "run as root"
[[ ${APPROVE_ROUTING_CRON_INSTALL:-} == yes ]] ||
  die "set APPROVE_ROUTING_CRON_INSTALL=yes after reviewing the cron contract"
[[ -f /etc/openclaw/openclaw.json && -f /etc/openclaw/gateway.env ]] ||
  die "Gateway configuration and environment must exist before installing routing cron"
[[ -f /etc/recording-agent/backend.env ]] ||
  die "Backend environment must exist before installing routing cron"

install -o root -g root -m 0755 \
  "$REPO_ROOT/deploy/scripts/recording-agent-routing-dispatch.sh" \
  /usr/local/sbin/recording-agent-routing-dispatch
install -o root -g root -m 0755 \
  "$REPO_ROOT/deploy/scripts/recording-agent-routing-cron-admin.sh" \
  /usr/local/sbin/recording-agent-routing-cron-admin
install -o root -g root -m 0440 \
  "$REPO_ROOT/deploy/systemd/recording-agent-routing-cron-admin.sudoers" \
  /etc/sudoers.d/recording-agent-routing-cron-admin
visudo -cf /etc/sudoers.d/recording-agent-routing-cron-admin >/dev/null ||
  die "invalid routing cron sudoers policy"
install -d -o openclaw -g openclaw -m 0700 /var/lib/openclaw/run
openclaw_secret=$(sed -n 's/^OPENCLAW_SECRET=//p' /etc/recording-agent/backend.env | tr -d '\r')
gateway_token=$(sed -n -E 's/^OPENCLAW_GATEWAY_TOKEN=([0-9a-f]{64})\r?$/\1/p' \
  /etc/openclaw/gateway.env)
[[ -n $openclaw_secret ]] || die "OPENCLAW_SECRET is missing from backend env"
[[ $gateway_token =~ ^[0-9a-f]{64}$ ]] ||
  die "OPENCLAW_GATEWAY_TOKEN is missing from gateway env"
{
  printf 'OPENCLAW_SECRET=%s\n' "$openclaw_secret"
  printf 'OPENCLAW_GATEWAY_TOKEN=%s\n' "$gateway_token"
} >/etc/openclaw/recording-agent-routing.env
chown root:openclaw /etc/openclaw/recording-agent-routing.env
chmod 0640 /etc/openclaw/recording-agent-routing.env
/usr/local/sbin/recording-agent-routing-cron-admin preflight
/usr/local/sbin/recording-agent-routing-cron-admin install
/usr/local/sbin/recording-agent-routing-cron-admin status >/dev/null
printf 'routing cron installed\n'
