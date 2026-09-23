#!/usr/bin/env bash
set -Eeuo pipefail

die() { printf 'canary-teardown: %s\n' "$*" >&2; exit 1; }
readonly ROOT=/opt/recording-agent-canary
readonly ENV_FILE=/etc/recording-agent/canary/backend.env
readonly PROJECT=recording-agent-canary
[[ ${EUID} -eq 0 ]] || die "must be invoked by root"
[[ $# -eq 1 && $1 == 'TEARDOWN_RECORDING_AGENT_CANARY' ]] || die "requires literal acknowledgement: TEARDOWN_RECORDING_AGENT_CANARY"
[[ -d $ROOT && ! -L $ROOT && $ROOT == /opt/recording-agent-canary ]] || die "unsafe canary root"
[[ -f $ENV_FILE && ! -L $ENV_FILE ]] || die "missing canary environment"
if [[ -L $ROOT/current ]]; then
  current=$(readlink -f "$ROOT/current")
  [[ $current == "$ROOT/releases/"* && -f $current/compose.canary.yml ]] || die "current canary release is unowned"
  compose=(docker compose --project-name "$PROJECT" --env-file "$ENV_FILE" --file "$current/compose.canary.yml")
  "${compose[@]}" down --volumes --remove-orphans
fi
for volume in recording-agent-canary-postgres recording-agent-canary-minio; do
  if docker volume inspect "$volume" >/dev/null 2>&1; then
    [[ $(docker volume inspect --format '{{ index .Labels "com.docker.compose.project" }}' "$volume") == "$PROJECT" ]] || die "refusing non-canary volume $volume"
    docker volume rm "$volume"
  fi
done
rm -rf -- "$ROOT/releases" "$ROOT/incoming" "$ROOT/current"
find "$ROOT" -mindepth 1 -maxdepth 1 -type d -name '.stage.*' -exec rm -rf -- {} +
printf 'canary containers and named canary volumes removed; root env files retained for operator rotation\n'
