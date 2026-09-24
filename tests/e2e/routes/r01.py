"""R01 — one candidate, the folder is unambiguous: one recruiter message end to end."""

from __future__ import annotations

from tests.e2e.lib.route import RouteCtx
from tests.e2e.routes.common import EXTERNAL, SCAN, SPOTS, terminal_sent

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
    ctx.check_cli(turn, must=("scan", "route-interview"))
    state = ctx.wait_for(lambda s: terminal_sent(s, 1), timeout=120)
    ctx.check_completed(state, item)
    rec = ctx.recording(state, item) or {}
    ctx.check(
        "В ответе Милы есть ссылка на карточку Notion",
        True,
        bool(rec.get("notion_page_url")) and (rec.get("notion_page_url") or "")[-32:] in turn.reply,
    )
    ctx.check(
        "В ответе Милы есть ссылка на запись",
        True,
        bool(rec.get("synology_share_url")) and rec.get("synology_share_url") in turn.reply,
    )
    ctx.check("Открытых вопросов после маршрута", 0, len(ctx.open_reviews(state)))
