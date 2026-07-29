#!/usr/bin/env bash
set -Eeuo pipefail

readonly PENDING=/etc/recording-agent/firewall.pending.nft
readonly STATE=/etc/recording-agent/firewall.pending.state
readonly INSTALLED=/etc/nftables.d/recording-agent.nft
readonly BACKUP_ROOT=/var/backups/recording-agent-firewall
readonly ROLLBACK_UNIT=recording-agent-firewall-rollback

die() { printf 'firewall: %s\n' "$*" >&2; exit 1; }

validate_candidate() {
  local candidate=$1
  [[ -f $candidate && ! -L $candidate ]] || die "candidate must be a regular file"
  ! grep -Eq '__[A-Z0-9_]+__' "$candidate" ||
    die "replace or remove every required firewall placeholder"
  grep -Eq 'type filter hook input .*policy drop;' "$candidate" ||
    die "input chain must use default deny"
  grep -F 'iifname "lo" accept' "$candidate" >/dev/null ||
    die "loopback accept rule is required"
  grep -F 'ct state established,related accept' "$candidate" >/dev/null ||
    die "established/related accept rule is required"
  grep -Eq '(ip|ip6) saddr .*tcp dport 22 .*accept' "$candidate" ||
    die "at least one source-restricted SSH rule is required"
  ! grep -Eq '(0\.0\.0\.0/0|::/0).*tcp dport 22' "$candidate" ||
    die "world-open SSH is forbidden"
  ! grep -Eq 'tcp dport .*(18000|18789|5432).*accept' "$candidate" ||
    die "Gateway, Backend, and PostgreSQL ports must not be accepted from an interface"
  nft --check --file "$candidate" >/dev/null ||
    die "nftables rejected candidate"
}

[[ $# -ge 1 ]] || die "usage: install-firewall.sh check FILE | apply FILE | confirm"
action=$1
case "$action" in
  check)
    [[ $# -eq 2 ]] || die "check requires one candidate"
    validate_candidate "$2"
    printf 'firewall candidate validation passed\n'
    ;;
  apply)
    [[ ${EUID} -eq 0 ]] || die "apply requires root"
    [[ $# -eq 2 ]] || die "apply requires one candidate"
    [[ ${APPROVE_FIREWALL_APPLY:-} == yes ]] ||
      die "set APPROVE_FIREWALL_APPLY=yes after reviewing CIDRs and recovery access"
    validate_candidate "$2"
    install -d -o root -g root -m 0700 "$BACKUP_ROOT"
    install -d -o root -g root -m 0755 /etc/nftables.d
    install -o root -g root -m 0600 "$2" "$PENDING"
    backup="$BACKUP_ROOT/$(date -u +%Y%m%dT%H%M%SZ).nft"
    {
      printf 'flush ruleset\n'
      nft list ruleset
    } >"$backup"
    chmod 0600 "$backup"
    printf '%s\n' "$backup" >"$STATE"
    chmod 0600 "$STATE"
    systemctl stop "$ROLLBACK_UNIT.timer" >/dev/null 2>&1 || true
    systemctl reset-failed "$ROLLBACK_UNIT.service" >/dev/null 2>&1 || true
    systemd-run --quiet --unit="$ROLLBACK_UNIT" --on-active=120s \
      /usr/sbin/nft --file "$backup"
    nft list table inet recording_agent >/dev/null 2>&1 &&
      nft delete table inet recording_agent
    if ! nft --file "$PENDING"; then
      nft --file "$backup" || true
      systemctl stop "$ROLLBACK_UNIT.timer" >/dev/null 2>&1 || true
      die "apply failed; previous ruleset restore attempted"
    fi
    printf 'firewall active with 120-second rollback armed; reconnect, then confirm\n'
    ;;
  confirm)
    [[ ${EUID} -eq 0 ]] || die "confirm requires root"
    [[ $# -eq 1 ]] || die "confirm takes no candidate"
    [[ ${APPROVE_FIREWALL_CONFIRM:-} == yes ]] ||
      die "set APPROVE_FIREWALL_CONFIRM=yes only from a proven new SSH connection"
    [[ -f $PENDING && -f $STATE ]] || die "no pending firewall application"
    backup=$(<"$STATE")
    [[ $backup == "$BACKUP_ROOT/"*.nft && -f $backup ]] ||
      die "invalid rollback state"
    systemctl stop "$ROLLBACK_UNIT.timer"
    install -o root -g root -m 0644 "$PENDING" "$INSTALLED"
    if ! grep -F 'include "/etc/nftables.d/*.nft"' /etc/nftables.conf >/dev/null 2>&1; then
      printf '\ninclude "/etc/nftables.d/*.nft"\n' >>/etc/nftables.conf
    fi
    systemctl enable nftables.service >/dev/null
    rm -f -- "$PENDING" "$STATE"
    printf 'firewall confirmed and persisted; rollback backup retained at %s\n' "$backup"
    ;;
  *)
    die "unknown action"
    ;;
esac

