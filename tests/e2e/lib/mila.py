# ruff: noqa: E501
"""Drive one Mila turn through `openclaw agent` on the server.

The Mattermost channel plugin prepends a "Conversation info (untrusted metadata)" block to
every DM; the runner prepends the same block so the skill sees the same trusted ids.
Replies are NOT delivered to Mattermost (no --deliver); backend notifications still are.
"""

from __future__ import annotations

import json
import secrets
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from tests.e2e.lib import remote

AGENT = "recordings-saver"
RECRUITER_USER_ID = "z1cn9tz3opg6fm7e8d7phcs88r"
RECRUITER_HANDLE = "@ralina.seitova"
DM_CHANNEL = "gg3pjz8uypf3xxs33o5hhyy3ny__z1cn9tz3opg6fm7e8d7phcs88r"

OC = (
    "oc() { ( set -a; . /etc/openclaw/gateway.env; set +a; runuser -u openclaw -- env "
    "HOME=/var/lib/openclaw OPENCLAW_STATE_DIR=/var/lib/openclaw "
    'OPENCLAW_CONFIG_PATH=/etc/openclaw/openclaw.json /opt/openclaw/bin/openclaw "$@" ); }\n'
)
SESSIONS = "/var/lib/openclaw/agents/recordings-saver/sessions"


@dataclass
class ToolCall:
    command: str
    result: str = ""


@dataclass
class Turn:
    user: str
    reply: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    duration_s: float = 0.0
    ok: bool = True
    error: str = ""


def _envelope(text: str, sender_id: str = RECRUITER_USER_ID, channel: str = DM_CHANNEL) -> str:
    now = datetime.now(UTC).strftime("%a %Y-%m-%d %H:%M:%S UTC")
    message_id = secrets.token_hex(13)
    info = {
        "chat_id": f"user:{sender_id}",
        "message_id": message_id,
        "sender_id": sender_id,
        "sender": RECRUITER_HANDLE,
        "timestamp": now,
        "group_channel": f"#{channel}",
    }
    sender = {
        "label": f"{RECRUITER_HANDLE} ({sender_id})",
        "id": sender_id,
        "name": RECRUITER_HANDLE,
    }
    return (
        "Conversation info (untrusted metadata):\n```json\n"
        + json.dumps(info, ensure_ascii=False, indent=2)
        + "\n```\n\nSender (untrusted metadata):\n```json\n"
        + json.dumps(sender, ensure_ascii=False, indent=2)
        + "\n```\n\n"
        + text
    )


_TURN_SCRIPT = r"""
set -u
MSG=$(mktemp /tmp/e2e-msg.XXXXXX)
cat > "$MSG" <<'__E2E_MSG__'
{message}
__E2E_MSG__
chmod 644 "$MSG"
python3 - "{key}" > /tmp/e2e-before.json <<'EOF'
import json, os, sys
key = sys.argv[1]
d = json.load(open("{sessions}/sessions.json"))
s = d.get(key) or {{}}
f = s.get("sessionFile")
print(json.dumps({{"file": f, "lines": sum(1 for _ in open(f)) if f and os.path.exists(f) else 0}}))
EOF
oc agent --agent {agent} --session-key "{key}" --message-file "$MSG" --json --timeout {timeout} > /tmp/e2e-out.json 2>/tmp/e2e-err.txt
RC=$?
rm -f "$MSG"
python3 - "{key}" "$RC" <<'EOF'
import json, sys
key, rc = sys.argv[1], int(sys.argv[2])
before = json.load(open("/tmp/e2e-before.json"))
try:
    out = json.load(open("/tmp/e2e-out.json"))
except Exception:
    out = {{}}
d = json.load(open("{sessions}/sessions.json"))
f = (d.get(key) or {{}}).get("sessionFile")
skip = before["lines"] if before.get("file") == f else 0
calls, results = [], {{}}
if f:
    for i, line in enumerate(open(f)):
        if i < skip:
            continue
        r = json.loads(line)
        m = r.get("message") or {{}}
        for x in m.get("content") or []:
            if not isinstance(x, dict):
                continue
            if x.get("type") in ("toolCall", "tool_use"):
                args = x.get("arguments") or x.get("input") or {{}}
                calls.append({{"id": x.get("id"), "name": x.get("name"),
                               "command": args.get("command") or json.dumps(args, ensure_ascii=False)}})
        if m.get("role") in ("toolResult", "tool"):
            content = m.get("content")
            text = content if isinstance(content, str) else "".join(
                c.get("text", "") for c in content or [] if isinstance(c, dict))
            results[m.get("toolCallId") or m.get("tool_call_id")] = text[:4000]

def find(o, k):
    if isinstance(o, dict):
        if k in o:
            return o[k]
        for v in o.values():
            r = find(v, k)
            if r is not None:
                return r
    elif isinstance(o, list):
        for v in o:
            r = find(v, k)
            if r is not None:
                return r
    return None

reply = find(out, "finalAssistantVisibleText") or ""
err = open("/tmp/e2e-err.txt", errors="replace").read()[-1500:]
print("@@TURN@@" + json.dumps({{"rc": rc, "reply": reply, "err": err if rc else "",
    "calls": [dict(c, result=results.get(c["id"], "")) for c in calls]}}, ensure_ascii=False))
EOF
"""


def turn(session: str, text: str, *, timeout: int = 420) -> Turn:
    key = f"agent:{AGENT}:e2e-{session}"
    message = _envelope(text)
    if "__E2E_MSG__" in message:
        raise ValueError("message contains heredoc terminator")
    script = OC + _TURN_SCRIPT.format(
        message=message, key=key, agent=AGENT, timeout=timeout, sessions=SESSIONS
    )
    started = time.monotonic()
    out = remote.bash(script, timeout=timeout + 120, check=False)
    duration = time.monotonic() - started
    if "@@TURN@@" not in out:
        return Turn(user=text, reply="", duration_s=duration, ok=False, error=out[-1500:])
    data: dict[str, Any] = json.loads(out.split("@@TURN@@", 1)[1])
    calls = [
        ToolCall(command=_redact(c.get("command") or ""), result=_redact(c.get("result") or ""))
        for c in data["calls"]
    ]
    return Turn(
        user=text,
        reply=data["reply"],
        tool_calls=calls,
        duration_s=duration,
        ok=data["rc"] == 0 and bool(data["reply"]),
        error=data.get("err", ""),
    )


def _redact(value: str) -> str:
    import re

    value = re.sub(r"(--capability\s+)\S+", r"\1<capability>", value)
    value = re.sub(r'("capability"\s*:\s*")[^"]+', r"\1<capability>", value)
    return value
