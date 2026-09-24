"""R14 — the daily scan + question digest fires at a chosen time T instead of 18:00."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

from tests.e2e.lib import remote
from tests.e2e.lib.route import OMSK, RouteCtx
from tests.e2e.routes.common import SPOTS

TITLE = "Сводка по расписанию в заданное время T"
CATALOG = "G6, O1, O3"
TARGET = "0"

SCAN_ARGS = (
    "scan",
    "--recruiter-user-id",
    "z1cn9tz3opg6fm7e8d7phcs88r",
    "--mattermost-dm-channel-id",
    "gg3pjz8uypf3xxs33o5hhyy3ny__z1cn9tz3opg6fm7e8d7phcs88r",
)


def _digests(local_date: str) -> list[dict]:
    return remote.stand(
        "sql",
        {
            "query": "select status, created_at from question_digests where local_date = "
            "cast(:d as date)",
            "params": {"d": local_date},
        },
    )


def _summaries(since: datetime) -> list[dict]:
    return remote.stand(
        "sql",
        {
            "query": "select status, payload, created_at, sent_at from notification_outbox "
            "where kind = 'summary' and created_at >= :since order by created_at",
            "params": {"since": since.isoformat()},
        },
    )


def body(ctx: RouteCtx) -> None:
    today = datetime.now(OMSK).date().isoformat()
    already = _digests(today)
    if any(d["status"] == "sent" for d in already):
        ctx.error = f"сводка за {today} уже отправлена — R14 можно прогнать только завтра"
        return

    first = ctx.interview("E2E Таня Сводкина", spot_ids=[SPOTS["analyst"]])
    second = ctx.interview("E2E Ульяна Сводкина", spot_ids=[SPOTS["analyst"]])
    ctx.skill_cli(*SCAN_ARGS, "--idempotency-key", f"e2e-{ctx.session}-scan")
    state = ctx.observe(notion=False)
    ctx.check_waiting(state, first, "storage_destination_required")
    ctx.check_waiting(state, second, "storage_destination_required")

    now = datetime.now(OMSK).replace(second=0, microsecond=0)
    due = now + timedelta(minutes=4)
    ctx.backend_env("SUMMARY_LOCAL_TIME", f"{due:%H:%M}")
    since = datetime.now(UTC)

    deadline = due + timedelta(minutes=3)
    summaries: list[dict] = []
    while datetime.now(OMSK) < deadline:
        summaries = [s for s in _summaries(since) if s["status"] == "sent"]
        if summaries:
            break
        time.sleep(15)
    ctx.check("G6: сводка отправлена", ">= 1", len(summaries), ok=bool(summaries))
    if not summaries:
        return
    sent_at = datetime.fromisoformat(summaries[0]["sent_at"]).astimezone(OMSK)
    ctx.check(
        "G6: пришла вовремя",
        f"[{due:%H:%M}; {due + timedelta(minutes=2):%H:%M}]",
        f"{sent_at:%H:%M:%S}",
        ok=due <= sent_at <= due + timedelta(minutes=2),
    )
    message = str(summaries[0]["payload"].get("message") or "")
    (ctx.dir / "artifacts" / ctx.route_id / "digest.txt").write_text(message, encoding="utf-8")
    ctx.check(
        "Формат: русский заголовок с числом вопросов",
        "Вопросы по записям собеседований: N.",
        message.splitlines()[0] if message else "—",
        ok=message.startswith("Вопросы по записям собеседований:"),
    )
    ctx.check(
        "Формат: обе записи в сводке",
        "обе",
        "обе" if first.candidate in message and second.candidate in message else message[:200],
        ok=first.candidate in message and second.candidate in message,
    )
    ctx.check(
        "Формат: без внутренних кодов",
        "без storage_destination_required",
        "ок" if "storage_destination_required" not in message else "есть код",
        ok="storage_destination_required" not in message,
    )

    time.sleep(180)
    later = [s for s in _summaries(since) if s["status"] == "sent"]
    ctx.check("O1: ровно одна сводка за дату", 1, len(later))
    digests = _digests(today)
    ctx.check("O1: одна строка question_digests за дату", 1, len(digests))
    logs = remote.bash(
        f"docker logs --since {int((datetime.now(UTC) - since).total_seconds()) + 60}s "
        "recording-agent-backend-1 2>&1 | grep -ciE 'traceback|exception' || true",
        check=False,
    ).strip()
    ctx.check("O3: без исключений в логах бэкенда", "0", logs or "0")
