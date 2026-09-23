#!/usr/bin/env bash
set -Eeuo pipefail

die() { printf 'canary-package: %s\n' "$*" >&2; exit 1; }
readonly ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
[[ $# -eq 2 ]] || die "usage: canary-package COMMIT OUTPUT_DIRECTORY"
commit=$1
output=$2
[[ $commit =~ ^[0-9a-f]{40}$ ]] || die "commit must be a full lowercase SHA"
[[ -d $output && ! -L $output ]] || die "output directory must already exist and not be a symlink"
git -C "$ROOT" rev-parse --verify --quiet "${commit}^{commit}" >/dev/null || die "unknown commit"
git -C "$ROOT" merge-base --is-ancestor "$commit" main && die "main commits are not canary candidates"

stage=$(mktemp -d "${TMPDIR:-/tmp}/recording-agent-canary.XXXXXX")
trap 'rm -rf -- "$stage"' EXIT
install -d -m 0700 "$stage/recording-agent-canary/deploy/mihomo"
git -C "$ROOT" show "$commit:compose.canary.yml" >"$stage/recording-agent-canary/compose.canary.yml"
git -C "$ROOT" show "$commit:deploy/mihomo/config.yaml" >"$stage/recording-agent-canary/deploy/mihomo/config.yaml"
git -C "$ROOT" show "$commit:deploy/mihomo/entrypoint.sh" >"$stage/recording-agent-canary/deploy/mihomo/entrypoint.sh"
chmod 0444 "$stage/recording-agent-canary/compose.canary.yml" "$stage/recording-agent-canary/deploy/mihomo/config.yaml"
chmod 0555 "$stage/recording-agent-canary/deploy/mihomo/entrypoint.sh"
(cd "$stage/recording-agent-canary" && find . -type f -print0 | sort -z | xargs -0 sha256sum) >"$stage/recording-agent-canary/manifest.sha256"
printf '%s\n' "$commit" >"$stage/recording-agent-canary/commit"
archive="$output/recording-agent-canary-${commit}.tar.gz"
[[ ! -e $archive ]] || die "refusing to overwrite existing archive"
tar --sort=name --owner=0 --group=0 --numeric-owner --mtime='UTC 1970-01-01' -C "$stage" -czf "$archive" recording-agent-canary
sha256sum "$archive" >"$archive.sha256"
printf 'created %s\n' "$archive"
