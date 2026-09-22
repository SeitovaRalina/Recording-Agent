#!/usr/bin/env bash
set -Eeuo pipefail

die() { printf 'canary-rollback: %s\n' "$*" >&2; exit 1; }
readonly ROOT=/opt/recording-agent-canary
readonly ENV_FILE=/etc/recording-agent/canary/backend.env
readonly PROJECT=recording-agent-canary
[[ ${EUID} -eq 0 ]] || die "must be invoked by root"
[[ $# -eq 1 ]] || die "usage: canary-rollback PREVIOUS_COMMIT"
commit=$1
[[ $commit =~ ^[0-9a-f]{40}$ ]] || die "commit must be a full lowercase SHA"
target="$ROOT/releases/$commit"
[[ -d $target && ! -L $target && -f $target/compose.canary.yml && -f $target/manifest.sha256 && -f $target/release-manifest ]] || die "target is not a verified canary release"
(cd "$target" && sha256sum -c manifest.sha256 >/dev/null) || die "target manifest mismatch"
[[ $(tr -d '\r' <"$target/commit") == "$commit" ]] || die "target commit mismatch"
image=$(sed -n 's/^image=//p' "$target/release-manifest")
[[ $image =~ ^ghcr\.io/seitovaralina/recording-agent@sha256:[0-9a-f]{64}$ ]] || die "canary image must be pinned"
export RECORDING_AGENT_IMAGE=$image
compose=(docker compose --project-name "$PROJECT" --env-file "$ENV_FILE" --file "$target/compose.canary.yml")
"${compose[@]}" config --quiet
"${compose[@]}" up -d --wait --wait-timeout 90
ln -sfn "$target" "$ROOT/current.next"
mv -Tf "$ROOT/current.next" "$ROOT/current"
printf 'rolled back canary to %s\n' "$commit"
