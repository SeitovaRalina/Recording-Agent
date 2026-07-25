#!/usr/bin/env bash
set -Eeuo pipefail

readonly AUTHORIZED_KEYS_DIR=/etc/ssh/authorized_keys

die() { printf 'install-ci-keys: %s\n' "$*" >&2; exit 1; }
[[ ${EUID} -eq 0 ]] || die "run as root"
[[ $# -eq 2 ]] || die "usage: install-ci-keys.sh STAGE_PUBLIC_KEY DEPLOY_PUBLIC_KEY"

stage_source=$1
deploy_source=$2
for source in "$stage_source" "$deploy_source"; do
  [[ -f $source && ! -L $source && $(stat -c '%U:%G' "$source") == root:root ]] ||
    die "public key source must be a root-owned regular file"
  ssh-keygen -lf "$source" >/dev/null || die "invalid SSH public key"
done

install_restricted_key() {
  local source=$1
  shift
  local key target next
  key=$(<"$source")
  [[ $key == ssh-ed25519\ * && $key != *$'\n'* ]] ||
    die "only one-line ED25519 public keys are accepted"
  for target in "$@"; do
    next="$AUTHORIZED_KEYS_DIR/${target}.next"
    printf 'restrict %s\n' "$key" >"$next"
    chown "root:$target" "$next"
    chmod 0640 "$next"
    mv -Tf "$next" "$AUTHORIZED_KEYS_DIR/$target"
  done
}

install -d -o root -g root -m 0755 "$AUTHORIZED_KEYS_DIR"
install_restricted_key "$stage_source" recording-stage openclaw-stage
install_restricted_key "$deploy_source" deploy openclaw-deploy

sshd -t
systemctl reload ssh.service
printf 'restricted CI/CD public keys installed\n'
