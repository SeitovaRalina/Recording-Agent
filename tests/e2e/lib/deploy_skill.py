"""Deploy the recording-agent skill files and the routing dispatcher to prod (with backup).

python -X utf8 -m tests.e2e.lib.deploy_skill
"""

from __future__ import annotations

import base64
from pathlib import Path

from tests.e2e.lib import remote

REPO = Path(__file__).resolve().parents[3] / "openclaw" / "skills" / "recording-agent"
TARGET = "/srv/openclaw/workspaces/recordings-saver/skills/recording-agent"
DISPATCHER = REPO.parents[2] / "deploy" / "scripts" / "recording-agent-routing-dispatch.sh"
DISPATCHER_TARGET = "/usr/local/sbin/recording-agent-routing-dispatch"
FILES = (
    "SKILL.md",
    "scripts/recording_agent.py",
    "references/autonomous-routing.md",
    "references/contract.md",
)


def main() -> None:
    parts = [
        "set -e",
        "TS=$(date -u +%Y%m%dT%H%M%SZ)",
        f"mkdir -p /root/skill-backup-$TS && cp -a {TARGET}/. /root/skill-backup-$TS/",
    ]
    for rel in FILES:
        data = base64.b64encode((REPO / rel).read_bytes()).decode()
        parts += [
            f"OWNER=$(stat -c %U:%G {TARGET}/{rel}); MODE=$(stat -c %a {TARGET}/{rel})",
            f"base64 -d > {TARGET}/{rel}.new <<'__B64__'\n{data}\n__B64__",
            f"chown $OWNER {TARGET}/{rel}.new && chmod $MODE {TARGET}/{rel}.new",
            f"mv {TARGET}/{rel}.new {TARGET}/{rel}",
        ]
    data = base64.b64encode(DISPATCHER.read_bytes()).decode()
    parts += [
        f"cp -a {DISPATCHER_TARGET} /root/skill-backup-$TS/routing-dispatch",
        f"base64 -d > {DISPATCHER_TARGET}.new <<'__B64__'\n{data}\n__B64__",
        f"chown root:root {DISPATCHER_TARGET}.new && chmod 755 {DISPATCHER_TARGET}.new",
        f"mv {DISPATCHER_TARGET}.new {DISPATCHER_TARGET}",
    ]
    parts.append(
        f"echo backup=/root/skill-backup-$TS; sha256sum {TARGET}/SKILL.md {DISPATCHER_TARGET}"
    )
    print(remote.bash("\n".join(parts)))


if __name__ == "__main__":
    main()
