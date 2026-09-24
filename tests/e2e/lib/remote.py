"""SSH transport to the prod stand.

Everything is sent as UTF-8 bytes on stdin so Cyrillic survives the Windows console.
Secrets never leave the server: scripts read them from the server-side env files.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

HOST = os.environ.get("E2E_SSH_HOST", "root@217.149.19.21")
KEY = os.environ.get("E2E_SSH_KEY", str(Path.home() / ".ssh" / "access_K0DE"))
SSH = os.environ.get("E2E_SSH_BIN", r"C:\Windows\System32\OpenSSH\ssh.exe")
BACKEND_CONTAINER = "recording-agent-backend-1"
POSTGRES_CONTAINER = "recording-agent-postgres-1"
STAND = Path(__file__).resolve().parents[1] / "stand" / "stand.py"


class RemoteError(RuntimeError):
    pass


def bash(script: str, *, timeout: int = 600, check: bool = True) -> str:
    """Run a bash script on the server; return stdout (UTF-8)."""
    proc = subprocess.run(
        [SSH, "-o", "BatchMode=yes", "-i", KEY, HOST, "bash -s"],
        input=script.replace("\r", "").encode("utf-8"),
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    out = proc.stdout.decode("utf-8", "replace")
    if check and proc.returncode != 0:
        err = proc.stderr.decode("utf-8", "replace")[-2000:]
        raise RemoteError(f"remote exit {proc.returncode}: {err or out[-2000:]}")
    return out


def stand(command: str, payload: dict[str, Any] | None = None, *, timeout: int = 600) -> Any:
    """Run tests/e2e/stand/stand.py inside the backend container; return its JSON result."""
    code = STAND.read_text(encoding="utf-8")
    body = json.dumps({"command": command, "payload": payload or {}}, ensure_ascii=False)
    # The stand script and its JSON request travel in one heredoc-free stream:
    # first line = script length, then script, then the request.
    blob = f"{len(code.encode('utf-8'))}\n{code}{body}"
    script = (
        f"docker exec -i -w /app {BACKEND_CONTAINER} python -X utf8 -c "
        '"import sys;b=sys.stdin.buffer;n=int(b.readline());src=b.read(n).decode();'
        "sys.argv=['stand'];exec(compile(src,'stand.py','exec'),{'__name__':'__main__'})\""
    )
    proc = subprocess.run(
        [SSH, "-o", "BatchMode=yes", "-i", KEY, HOST, script],
        input=blob.encode("utf-8"),
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    out = proc.stdout.decode("utf-8", "replace")
    marker = "\n@@E2E@@"
    if marker not in "\n" + out:
        err = proc.stderr.decode("utf-8", "replace")[-3000:]
        raise RemoteError(f"stand {command} failed (exit {proc.returncode}): {err or out[-3000:]}")
    result = json.loads(("\n" + out).split(marker, 1)[1])
    if isinstance(result, dict) and result.get("error"):
        raise RemoteError(f"stand {command}: {result['error']}")
    return result


def psql(sql: str) -> list[dict[str, Any]]:
    """Run a read query in prod Postgres; rows as dicts (json_agg)."""
    wrapped = f"select coalesce(json_agg(t), '[]'::json) from ({sql.rstrip(';')}) t;"
    out = bash(
        f"docker exec -i {POSTGRES_CONTAINER} psql -U postgres -d recording_agent -At <<'SQL'\n"
        f"{wrapped}\nSQL\n"
    )
    return json.loads(out.strip() or "[]")
