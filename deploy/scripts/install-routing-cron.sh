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
/usr/local/sbin/recording-agent-routing-cron-admin preflight
/usr/local/sbin/recording-agent-routing-cron-admin install
/usr/local/sbin/recording-agent-routing-cron-admin status >/dev/null
printf 'routing cron installed\n'
