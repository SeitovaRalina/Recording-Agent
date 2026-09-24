"""R01 — one candidate, the folder is unambiguous: one recruiter message end to end."""

from __future__ import annotations

from tests.e2e.lib.route import RouteCtx
from tests.e2e.routes.common import EXTERNAL, SCAN, SPOTS

TITLE = "Один кандидат, папка однозначна"
CATALOG = "A1, B1, C1, C10, D1/D3/D8, F1, H2, I7"
TARGET = "1"


def body(ctx: RouteCtx) -> None:
    item = ctx.interview(
        "E2E Олег Тестов", spot_ids=[SPOTS["python"]], expected_folder=f"{EXTERNAL}/Python"
    )
    turn = ctx.say(
        SCAN,
        scenario=(
            "R01. На Диске одна новая запись собеседования. Событие календаря и карточка Notion "
            "однозначны, спот «Python-разработчик @Т-банк», подходящая папка Synology одна: "
            "Recruiting-E / 2. Interviews external / Python."
        ),
        expected=(
            "Мила в ОДНОМ ходе вызывает scan, затем destinations и route-interview в папку Python "
            "без вопросов рекрутеру, и сообщает итог: кандидат, ссылка на карточку Notion и "
            "ссылка на запись. Не читает файлы воркспейса кроме SKILL.md."
        ),
    )
    # `process` poll/log of a still-running exec is fine; anything else outside the CLI is not.
    names = [
        c.command
        for c in turn.tool_calls
        if '"action": "poll"' not in c.command and '"action": "log"' not in c.command
    ]
    ctx.check(
        "Мила вызвала scan и route-interview в одном ходе",
        "scan → route-interview",
        " → ".join(n.split()[2] for n in names if "recording_agent.py" in n) or "—",
        ok=any(" scan " in f" {n} " for n in names) and any("route-interview" in n for n in names),
    )
    ctx.check(
        "Мила не лезет в файлы воркспейса (I7)",
        "только SKILL.md и CLI навыка",
        "; ".join(n[:80] for n in names if "recording_agent.py" not in n and "SKILL.md" not in n)
        or "ок",
        ok=all("recording_agent.py" in n or "SKILL.md" in n for n in names),
    )
    state = ctx.wait_for(
        lambda s: any(
            o["status"] == "sent" and str(o["dedupe_key"]).startswith("terminal:")
            for o in s["outbox"]
        ),
        timeout=120,
    )
    ctx.check_completed(state, item)
    reply = turn.reply
    rec = ctx.recording(state, item) or {}
    ctx.check(
        "В ответе Милы есть ссылка на карточку Notion",
        True,
        bool(rec.get("notion_page_url")) and (rec.get("notion_page_url") or "")[-32:] in reply,
    )
    ctx.check(
        "В ответе Милы есть ссылка на запись",
        True,
        bool(rec.get("synology_share_url")) and rec.get("synology_share_url") in reply,
    )
    ctx.check("Открытых вопросов после маршрута", 0, len(ctx.open_reviews(state)))
