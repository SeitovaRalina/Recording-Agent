#!/usr/bin/env bash
set -Eeuo pipefail

readonly COMPLETION_MARKER=/etc/recording-agent/.bootstrap-complete
readonly OWNERSHIP_MANIFEST=/etc/recording-agent-bootstrap.paths
readonly OPENCLAW_VERSION="${OPENCLAW_VERSION:-2026.6.11}"
readonly MATTERMOST_PLUGIN_VERSION="${MATTERMOST_PLUGIN_VERSION:-2026.6.11}"
readonly NODE_VERSION="${NODE_VERSION:-24.15.0}"
readonly DOCKER_ENGINE_VERSION="${DOCKER_ENGINE_VERSION:-29.1.3-0ubuntu4.1}"
readonly DOCKER_COMPOSE_VERSION="${DOCKER_COMPOSE_VERSION:-2.40.3+ds1-0ubuntu1}"
readonly OPENCLAW_INSTALLER_COMMIT="${OPENCLAW_INSTALLER_COMMIT:-84fb1548a77d77dba1af27fa9f32c7c46a0a0d77}"
readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly REPO_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"

die() { printf 'bootstrap: %s\n' "$*" >&2; exit 1; }
require_root() { [[ ${EUID} -eq 0 ]] || die "run as root"; }
require_approval() {
  [[ ${APPROVE_HOST_MUTATION:-} == yes ]] ||
    die "set APPROVE_HOST_MUTATION=yes after approving the pinned manifest"
}
require_pin() {
  [[ -n $2 && $2 != latest && $2 != *'*'* ]] || die "$1 must be an exact version"
}

require_root
require_approval
[[ -r /etc/os-release ]] || die "/etc/os-release is unavailable"
# shellcheck disable=SC1091
source /etc/os-release
[[ ${ID:-} == ubuntu && ${VERSION_ID:-} == 26.04 ]] ||
  die "supported host is Ubuntu 26.04; found ${ID:-unknown} ${VERSION_ID:-unknown}"
require_pin OPENCLAW_VERSION "$OPENCLAW_VERSION"
require_pin MATTERMOST_PLUGIN_VERSION "$MATTERMOST_PLUGIN_VERSION"
require_pin NODE_VERSION "$NODE_VERSION"
require_pin DOCKER_ENGINE_VERSION "$DOCKER_ENGINE_VERSION"
require_pin DOCKER_COMPOSE_VERSION "$DOCKER_COMPOSE_VERSION"
[[ $OPENCLAW_INSTALLER_COMMIT =~ ^[0-9a-f]{40}$ ]] ||
  die "OPENCLAW_INSTALLER_COMMIT must be a full commit SHA"

ownership_spec=$(mktemp)
trap 'rm -f -- "$ownership_spec"' EXIT
cat >"$ownership_spec" <<'EOF'
D	/etc/openclaw	root	openclaw	750
D	/etc/openclaw/agents	root	openclaw	750
D	/etc/recording-agent	root	root	700
D	/etc/ssh/authorized_keys	root	root	755
D	/opt/recording-agent	root	root	755
D	/opt/recording-agent/failures	root	root	700
D	/opt/recording-agent/releases	root	root	755
D	/opt/recording-agent/shared-backups	root	root	700
D	/opt/recording-agent/shared-staging	root	root	700
D	/opt/recording-agent/sftp	root	root	755
D	/opt/recording-agent/sftp/incoming	recording-stage	recording-stage	750
D	/opt/recording-agent/sftp/shared-incoming	openclaw-stage	openclaw-stage	750
D	/opt/recording-agent/staging	root	root	700
D	/srv/openclaw	root	openclaw	750
D	/srv/openclaw/workspaces	openclaw	openclaw	750
D	/var/backups/recording-agent	root	root	700
D	/var/lib/openclaw	openclaw	openclaw	700
D	/var/lib/openclaw/agents	openclaw	openclaw	700
D	/var/lib/openclaw-deploy	openclaw-deploy	openclaw-deploy	700
D	/var/lib/recording-agent-deploy	deploy	deploy	700
F	/etc/sudoers.d/openclaw-shared-deploy	root	root	440
F	/etc/ssh/sshd_config.d/60-recording-agent-deploy.conf	root	root	644
F	/etc/sudoers.d/recording-agent-deploy	root	root	440
F	/etc/systemd/system/openclaw-gateway.service	root	root	644
F	/usr/local/sbin/recording-agent-deploy	root	root	755
F	/usr/local/sbin/recording-agent-firewall	root	root	755
F	/usr/local/sbin/recording-agent-rollback	root	root	755
F	/usr/local/sbin/recording-agent-smoke-test	root	root	755
F	/usr/local/sbin/openclaw-shared-deploy	root	root	755
EOF

if [[ ! -e $OWNERSHIP_MANIFEST ]]; then
  while IFS=$'\t' read -r _ path _; do
    [[ ! -e $path ]] || die "unowned collision at $path"
  done <"$ownership_spec"
  install -o root -g root -m 0600 "$ownership_spec" "$OWNERSHIP_MANIFEST"
else
  cmp -s "$ownership_spec" "$OWNERSHIP_MANIFEST" ||
    die "bootstrap ownership manifest differs from the approved layout"
  [[ $(stat -c '%a:%U:%G' "$OWNERSHIP_MANIFEST") == 600:root:root ]] ||
    die "bootstrap ownership manifest permissions drifted"
fi

ensure_user() {
  local name=$1 home=$2 shell=$3 system=$4
  if id "$name" &>/dev/null; then
    local entry
    entry=$(getent passwd "$name")
    [[ $(cut -d: -f6 <<<"$entry") == "$home" &&
      $(cut -d: -f7 <<<"$entry") == "$shell" &&
      $(id -gn "$name") == "$name" ]] ||
      die "user $name collides with the approved identity"
    return
  fi
  if [[ $system == true ]]; then
    useradd --system --user-group --no-create-home --home-dir "$home" --shell "$shell" "$name"
  else
    useradd --user-group --no-create-home --home-dir "$home" --shell "$shell" "$name"
  fi
}

ensure_user openclaw /var/lib/openclaw /usr/sbin/nologin true
ensure_user deploy /var/lib/recording-agent-deploy /bin/bash false
ensure_user recording-stage /incoming /bin/bash true
ensure_user openclaw-deploy /var/lib/openclaw-deploy /bin/bash false
ensure_user openclaw-stage /shared-incoming /bin/bash true

while IFS=$'\t' read -r kind path owner group mode; do
  [[ $kind == D ]] || continue
  if [[ -e $path ]]; then
    [[ -d $path && $(stat -c '%U:%G:%a' "$path") == "$owner:$group:$mode" ]] ||
      die "owned path drift at $path"
  else
    install -d -o "$owner" -g "$group" -m "$mode" "$path"
  fi
done <"$OWNERSHIP_MANIFEST"

verify_managed_file_target() {
  local target=$1 mode=$2
  if [[ -e $target ]]; then
    [[ -f $target && ! -L $target &&
      $(stat -c '%U:%G:%a' "$target") == "root:root:$mode" ]] ||
      die "managed file drift at $target"
  fi
}

apt-get update
apt-get install -y --no-install-recommends \
  "docker.io=${DOCKER_ENGINE_VERSION}" \
  "docker-compose-v2=${DOCKER_COMPOSE_VERSION}" \
  ca-certificates curl git jq nftables

[[ $(dpkg-query -W -f='${Version}' docker.io) == "$DOCKER_ENGINE_VERSION" ]] ||
  die "installed Docker version does not match the approved pin"
[[ $(dpkg-query -W -f='${Version}' docker-compose-v2) == "$DOCKER_COMPOSE_VERSION" ]] ||
  die "installed Compose version does not match the approved pin"

if [[ ! -x /opt/openclaw/bin/openclaw ]]; then
  installer=$(mktemp)
  curl -fsSL --proto '=https' --tlsv1.2 \
    "https://raw.githubusercontent.com/openclaw/openclaw.ai/${OPENCLAW_INSTALLER_COMMIT}/public/install-cli.sh" \
    -o "$installer"
  bash "$installer" --json --prefix /opt/openclaw \
    --version "$OPENCLAW_VERSION" --node-version "$NODE_VERSION" --no-onboard
  rm -f -- "$installer"
fi
[[ "$(/opt/openclaw/bin/openclaw --version)" == *"$OPENCLAW_VERSION"* ]] ||
  die "OpenClaw pin mismatch"
mapfile -t mattermost_manifests < <(
  find /var/lib/openclaw/npm/projects -type f \
    -path '*/node_modules/@openclaw/mattermost/package.json' 2>/dev/null
)
if [[ ${#mattermost_manifests[@]} -eq 0 ]]; then
  runuser -u openclaw -- env HOME=/var/lib/openclaw OPENCLAW_STATE_DIR=/var/lib/openclaw \
    /opt/openclaw/bin/openclaw plugins install \
    "@openclaw/mattermost@${MATTERMOST_PLUGIN_VERSION}"
  mapfile -t mattermost_manifests < <(
    find /var/lib/openclaw/npm/projects -type f \
      -path '*/node_modules/@openclaw/mattermost/package.json'
  )
fi
[[ ${#mattermost_manifests[@]} -eq 1 ]] ||
  die "expected exactly one tracked Mattermost plugin installation"
[[ $(jq -r '.version' "${mattermost_manifests[0]}") == "$MATTERMOST_PLUGIN_VERSION" ]] ||
  die "Mattermost plugin version drift"

verify_managed_file_target /usr/local/sbin/recording-agent-deploy 755
verify_managed_file_target /usr/local/sbin/recording-agent-firewall 755
verify_managed_file_target /usr/local/sbin/recording-agent-rollback 755
verify_managed_file_target /usr/local/sbin/recording-agent-smoke-test 755
verify_managed_file_target /usr/local/sbin/openclaw-shared-deploy 755
verify_managed_file_target /etc/systemd/system/openclaw-gateway.service 644
verify_managed_file_target /etc/sudoers.d/recording-agent-deploy 440
verify_managed_file_target /etc/sudoers.d/openclaw-shared-deploy 440
verify_managed_file_target /etc/ssh/sshd_config.d/60-recording-agent-deploy.conf 644
install -o root -g root -m 0755 "$REPO_ROOT/deploy/scripts/deploy.sh" \
  /usr/local/sbin/recording-agent-deploy
install -o root -g root -m 0755 "$REPO_ROOT/deploy/scripts/install-firewall.sh" \
  /usr/local/sbin/recording-agent-firewall
install -o root -g root -m 0755 "$REPO_ROOT/deploy/scripts/rollback.sh" \
  /usr/local/sbin/recording-agent-rollback
install -o root -g root -m 0755 "$REPO_ROOT/deploy/scripts/smoke-test.sh" \
  /usr/local/sbin/recording-agent-smoke-test
install -o root -g root -m 0755 "$REPO_ROOT/deploy/scripts/openclaw-shared-deploy.sh" \
  /usr/local/sbin/openclaw-shared-deploy
install -o root -g root -m 0644 "$REPO_ROOT/deploy/systemd/openclaw-gateway.service" \
  /etc/systemd/system/openclaw-gateway.service
install -o root -g root -m 0440 "$REPO_ROOT/deploy/systemd/recording-agent-deploy.sudoers" \
  /etc/sudoers.d/recording-agent-deploy
install -o root -g root -m 0440 "$REPO_ROOT/deploy/systemd/openclaw-shared-deploy.sudoers" \
  /etc/sudoers.d/openclaw-shared-deploy
visudo -cf /etc/sudoers.d/recording-agent-deploy >/dev/null ||
  die "invalid deploy sudoers policy"
visudo -cf /etc/sudoers.d/openclaw-shared-deploy >/dev/null ||
  die "invalid shared deploy sudoers policy"
cat >/etc/ssh/sshd_config.d/60-recording-agent-deploy.conf <<'EOF'
Match User recording-stage
    ChrootDirectory /opt/recording-agent/sftp
    AuthorizedKeysFile /etc/ssh/authorized_keys/%u
    ForceCommand internal-sftp -d /incoming
    DisableForwarding yes
    PermitTTY no
    PasswordAuthentication no

Match User deploy
    AuthorizedKeysFile /etc/ssh/authorized_keys/%u
    ForceCommand /usr/local/sbin/recording-agent-deploy
    DisableForwarding yes
    PermitTTY no
    PasswordAuthentication no

Match User openclaw-stage
    ChrootDirectory /opt/recording-agent/sftp
    AuthorizedKeysFile /etc/ssh/authorized_keys/%u
    ForceCommand internal-sftp -d /shared-incoming
    DisableForwarding yes
    PermitTTY no
    PasswordAuthentication no

Match User openclaw-deploy
    AuthorizedKeysFile /etc/ssh/authorized_keys/%u
    ForceCommand /usr/local/sbin/openclaw-shared-deploy
    DisableForwarding yes
    PermitTTY no
    PasswordAuthentication no
EOF
chmod 0644 /etc/ssh/sshd_config.d/60-recording-agent-deploy.conf
sshd -t
systemctl daemon-reload
systemctl reload ssh.service

touch "$COMPLETION_MARKER"
chmod 0600 "$COMPLETION_MARKER"
printf 'bootstrap complete; install reviewed config/unit/sudoers before enabling services\n'
