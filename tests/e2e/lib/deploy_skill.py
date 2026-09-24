"""Deploy the recording-agent skill files to the prod OpenClaw workspace (with backup).

python -X utf8 -m tests.e2e.lib.deploy_skill
"""

from __future__ import annotations

import base64
from pathlib import Path

from tests.e2e.lib import remote

REPO = Path(__file__).resolve().parents[3] / "openclaw" / "skills" / "recording-agent"
TARGET = "/srv/openclaw/workspaces/recordings-saver/skills/recording-agent"
FILES = ("SKILL.md", "scripts/recording_agent.py")


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
    parts.append(f"echo backup=/root/skill-backup-$TS; sha256sum {TARGET}/SKILL.md")
    print(remote.bash("\n".join(parts)))


if __name__ == "__main__":
    main()
