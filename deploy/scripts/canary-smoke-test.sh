#!/usr/bin/env bash
set -Eeuo pipefail

die() { printf 'canary-smoke: %s\n' "$*" >&2; exit 1; }
readonly ROOT=/opt/recording-agent-canary
readonly ENV_FILE=/etc/recording-agent/canary/backend.env
readonly PROJECT=recording-agent-canary
readonly PORT=18001
[[ ${EUID} -eq 0 ]] || die "must be invoked by root"
[[ $# -eq 0 ]] || die "smoke test takes no arguments"
[[ -L $ROOT/current && -f $ROOT/current/compose.canary.yml ]] || die "no owned canary release"
grep -qx 'TEST_MODE_ENABLED=true' "$ENV_FILE" || die "test mode must remain enabled"
for setting in SCHEDULER_ENABLED AUTONOMOUS_ROUTING_ENABLED NOTION_WRITES_ENABLED MATTERMOST_DELIVERY_ENABLED YANDEX_SOURCE_MUTATION_ENABLED; do
  grep -qx "${setting}=false" "$ENV_FILE" || die "$setting must remain false"
done
compose=(docker compose --project-name "$PROJECT" --env-file "$ENV_FILE" --file "$ROOT/current/compose.canary.yml")
for service in postgres backend notion-proxy; do
  "${compose[@]}" ps --status running --quiet "$service" | grep -q . || die "$service is not running"
done
curl --fail --silent --show-error --max-time 5 "http://127.0.0.1:${PORT}/health" >/dev/null
proxy_id=$("${compose[@]}" ps --quiet notion-proxy)
[[ -n $proxy_id ]] || die "notion proxy is unavailable"
docker exec "$proxy_id" sh -eu -c 'test -f /run/mihomo/notion-ready' || die "Notion proxy did not pass JSON readiness"
backend_id=$("${compose[@]}" ps --quiet backend)
[[ -n $backend_id ]] || die "backend is unavailable"
database_id=$(docker exec "$backend_id" python -c '
import json
import os
ids = json.loads(os.environ["TEST_NOTION_DATABASE_ALLOWLIST"])
assert isinstance(ids, list) and len(ids) == 1 and isinstance(ids[0], str) and ids[0]
print(ids[0])
') || die "canary requires exactly one test Notion database"
docker exec "$backend_id" python tools/setup/preflight_notion.py --database-id "$database_id" || die "read-only Notion schema preflight failed"
printf 'canary smoke checks passed\n'
