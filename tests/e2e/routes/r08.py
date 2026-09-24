"""R08 — a working meeting goes to a folder without Notion; another recording is skipped."""

from __future__ import annotations

from tests.e2e.lib.route import RouteCtx
from tests.e2e.routes.common import NON_ENGINEERING, SCAN, terminal_sent

TITLE = "Рабочая встреча и пропуск"
CATALOG = "J1, J2, B3"
TARGET = "2"


def body(ctx: RouteCtx) -> None:
    meeting = ctx.interview(
        "Планёрка",
        create_card=False,
        event=False,
        summary=f"Планёрка BizDev {ctx.tag}",
        expected_folder=f"{NON_ENGINEERING}/BizDev",
    )
    personal = ctx.interview(
        "Личный созвон", create_card=False, event=False, summary=f"Личный созвон {ctx.tag}"
    )
    turn = ctx.say(
        SCAN,
        scenario=(
            "R08. Две новые записи без событий в календаре: «Планёрка BizDev» и «Личный созвон». "
            "Это не собеседования."
        ),
        expected=(
            "Мила одним сообщением сообщает о двух записях, для которых не найдено событие, и "
            "спрашивает, что с ними делать (собеседование / рабочая встреча в папку / пропустить), "
            "с примером ответа."
        ),
    )
    ctx.check_cli(turn, must=("scan",), must_not=("route-interview", "non-interview"))

    turn = ctx.say(
        "Первая — рабочая встреча, положи в BizDev. Вторую пропусти, это не собеседование.",
        scenario="R08. Рекрутер классифицирует обе записи.",
        expected=(
            "Мила вызывает destinations и non-interview в Recruiting-NE/2. Interviews/BizDev для "
            "первой (без Notion) и пропускает вторую через answer/ignore; сообщает итог."
        ),
    )
    ctx.check_cli(turn, must=("non-interview",))
    state = ctx.wait_for(lambda s: terminal_sent(s, 1), timeout=180)
    rec = ctx.recording(state, meeting) or {}
    ctx.check("Планёрка: статус", "completed", rec.get("status"))
    ctx.check("Планёрка: тип", "non_interview", rec.get("route_type"))
    ctx.check("Планёрка: папка", meeting.expected_folder, rec.get("synology_folder_path"))
    ctx.check("Планёрка: без карточки Notion", None, rec.get("notion_page_id"))
    if rec.get("synology_file_path"):
        ctx.register_cleanup("Файл Synology", rec["synology_file_path"], "удалить (с маркером)")
    rec = ctx.recording(state, personal) or {}
    ctx.check("Личный созвон: пропущен", "ignored", rec.get("status"))
    ctx.check("Открытых вопросов после маршрута", 0, len(ctx.open_reviews(state)))
