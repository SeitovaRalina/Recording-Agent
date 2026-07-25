#!/usr/bin/env bash
set -Eeuo pipefail

readonly ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
readonly CONFIG="$ROOT/deploy/openclaw/openclaw.example.json"
readonly METADATA="$ROOT/deploy/release-metadata.json"

for script in "$ROOT"/deploy/scripts/*.sh; do
  bash -n "$script"
done

jq -e '
  . as $root |
  ($root.gateway.mode == "local") and
  ($root.gateway.bind == "loopback") and
  ([$root.agents.list[].id] | length >= 1) and
  (([$root.agents.list[].id] | unique | length) ==
    ([$root.agents.list[].id] | length)) and
  (([$root.agents.list[].workspace] | unique | length) ==
    ([$root.agents.list[].workspace] | length)) and
  (([$root.agents.list[].agentDir] | unique | length) ==
    ([$root.agents.list[].agentDir] | length)) and
  (all($root.agents.list[]; (.default // false) == false)) and
  (all($root.bindings[] | select(.match.channel == "mattermost");
    .agentId == .match.accountId)) and
  ([$root.bindings[] |
    select(.agentId == "*" or .match.channel == "*" or .match.accountId == "*")
  ] | length == 0)
' "$CONFIG" >/dev/null

diff -u \
  <(jq -r '.channels.mattermost.accounts | keys[]' "$CONFIG" | sort) \
  <(jq -r '.bindings[] | select(.match.channel == "mattermost") | .match.accountId' \
    "$CONFIG" | sort) >/dev/null
diff -u \
  <(jq -r '.agents.list[].id' "$CONFIG" | sort) \
  <(jq -r '.bindings[] | select(.match.channel == "mattermost") | .agentId' \
    "$CONFIG" | sort) >/dev/null

jq -e '
  (.schemaVersion == 1) and
  (.targetAlembicRevision | test("^[0-9A-Za-z_]{1,64}$")) and
  (.previousApplicationCompatibleWithTargetSchema | type == "boolean") and
  (.reviewPolicy == "code-owner-and-production-environment-approver") and
  (.rationale | type == "string" and length >= 20) and
  (.migrationStrategy == "expand-contract" or .migrationStrategy == "forward-only") and
  (.failurePolicy == "automatic-application-rollback" or
    .failurePolicy == "stop-writes-forward-fix") and
  ((.previousApplicationCompatibleWithTargetSchema == true and
    .migrationStrategy == "expand-contract" and
    .failurePolicy == "automatic-application-rollback") or
   (.previousApplicationCompatibleWithTargetSchema == false and
    .failurePolicy == "stop-writes-forward-fix"))
' "$METADATA" >/dev/null

grep -F 'ChrootDirectory /opt/recording-agent/sftp' \
  "$ROOT/deploy/scripts/bootstrap-host.sh" >/dev/null
grep -F 'deploy ALL=(root) NOPASSWD: /usr/local/sbin/recording-agent-deploy *' \
  "$ROOT/deploy/systemd/recording-agent-deploy.sudoers" >/dev/null
grep -F 'COMPOSE_SHA SKILL_SHA METADATA_SHA' \
  "$ROOT/deploy/scripts/deploy.sh" >/dev/null
grep -F 'Compose digest does not match authenticated command' \
  "$ROOT/deploy/scripts/deploy.sh" >/dev/null
grep -F 'release-manifest.json' "$ROOT/deploy/scripts/deploy.sh" >/dev/null
grep -F 'previousApplicationCompatibleWithTargetSchema' \
  "$ROOT/deploy/scripts/deploy.sh" >/dev/null
grep -F 'post-start capacity gate failed' \
  "$ROOT/deploy/scripts/smoke-test.sh" >/dev/null
grep -F 'candidate changes or omits an existing agent, account, or binding' \
  "$ROOT/deploy/scripts/openclaw-shared-deploy.sh" >/dev/null
grep -F 'unexpected live OpenClaw config drift' \
  "$ROOT/deploy/scripts/openclaw-shared-deploy.sh" >/dev/null
grep -F 'openclaw-shared-deploy COMMIT CONFIG_SHA INVENTORY_SHA' \
  "$ROOT/deploy/scripts/openclaw-shared-deploy.sh" >/dev/null
grep -F 'ForceCommand internal-sftp -d /shared-incoming' \
  "$ROOT/deploy/scripts/bootstrap-host.sh" >/dev/null
grep -F 'openclaw-deploy ALL=(root) NOPASSWD: /usr/local/sbin/openclaw-shared-deploy *' \
  "$ROOT/deploy/systemd/openclaw-shared-deploy.sudoers" >/dev/null
grep -F '__APPROVED_SSH_IPV4_CIDRS__' \
  "$ROOT/deploy/firewall/recording-agent.nft.example" >/dev/null
grep -F '__APPROVED_SSH_IPV6_CIDRS__' \
  "$ROOT/deploy/firewall/recording-agent.nft.example" >/dev/null
grep -F 'policy drop;' "$ROOT/deploy/firewall/recording-agent.nft.example" >/dev/null
grep -F 'iifname "lo" accept' \
  "$ROOT/deploy/firewall/recording-agent.nft.example" >/dev/null
grep -F 'replace or remove every required firewall placeholder' \
  "$ROOT/deploy/scripts/install-firewall.sh" >/dev/null
grep -F 'APPROVE_FIREWALL_APPLY' "$ROOT/deploy/scripts/install-firewall.sh" >/dev/null
grep -F 'on-active=120s' "$ROOT/deploy/scripts/install-firewall.sh" >/dev/null
! grep -Eq 'tcp dport (18000|18789|5432).*accept' \
  "$ROOT/deploy/firewall/recording-agent.nft.example"
grep -F 'candidate Alembic head does not match authenticated release metadata' \
  "$ROOT/deploy/scripts/deploy.sh" >/dev/null
grep -F 'pre-existing shared config requires a valid managed manifest' \
  "$ROOT/deploy/scripts/openclaw-shared-deploy.sh" >/dev/null
grep -F 'Gateway environment must be root-owned mode 0600' \
  "$ROOT/deploy/scripts/openclaw-shared-deploy.sh" >/dev/null
grep -F -- '--property="EnvironmentFile=$GATEWAY_ENV"' \
  "$ROOT/deploy/scripts/openclaw-shared-deploy.sh" >/dev/null
! grep -F 'runuser -u openclaw' \
  "$ROOT/deploy/scripts/openclaw-shared-deploy.sh" >/dev/null

quiesced_line=$(grep -n '^quiesced=true$' "$ROOT/deploy/scripts/deploy.sh" | cut -d: -f1)
backup_line=$(grep -n 'pg_dump' "$ROOT/deploy/scripts/deploy.sh" | tail -1 | cut -d: -f1)
migrate_line=$(grep -n 'run -T --rm migrate' "$ROOT/deploy/scripts/deploy.sh" | cut -d: -f1)
[[ $quiesced_line -lt $backup_line && $backup_line -lt $migrate_line ]]

printf 'deployment static validation passed\n'
