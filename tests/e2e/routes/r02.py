"""R02 — the folder is ambiguous (Analyst exists in external and internal): one question."""

from __future__ import annotations

from tests.e2e.lib.route import RouteCtx
from tests.e2e.routes.common import EXTERNAL, SCAN, SPOTS, terminal_sent

TITLE = "Папка неоднозначна (Analyst во внешних и внутренних)"
CATALOG = "A1, B1, C1, D2, D7, D8, F1, H2, K4"
TARGET = "2"


def body(ctx: RouteCtx) -> None:
    item = ctx.interview(
        "E2E Марина Аналитикова",
        spot_ids=[SPOTS["analyst"]],
        expected_folder=f"{EXTERNAL}/Analyst",
    )
    turn = ctx.say(
        SCAN,
        scenario=(
            "R02. Одна новая запись, спот «Бизнес-аналитик @Т-банк». Папка Analyst есть и во "
            "внешних (2. Interviews external/Analyst), и во внутренних (3. Interviews "
            "internal/Analyst), поэтому выбор неоднозначен."
        ),
        expected=(
            "Мила вызывает scan и destinations, НЕ сохраняет запись сама, а в том же ответе задаёт "
            "один вопрос: внешний проект или внутренняя роль, с нумерованными вариантами папок, "
            "своей рекомендацией и примером ответа."
        ),
    )
    ctx.check_cli(turn, must=("scan", "destinations"), must_not=("route-interview",))
    state = ctx.observe(notion=False)
    ctx.check_waiting(state, item, "storage_destination_required")
    reply = turn.reply.lower()
    ctx.check(
        "В вопросе есть и внешний, и внутренний вариант",
        "external + internal",
        turn.reply[:200],
        ok=("external" in reply or "внеш" in reply) and ("internal" in reply or "внутр" in reply),
    )

    turn = ctx.say(
        "Внешний проект, положи во внешние",
        scenario="R02, ответ рекрутера на вопрос о папке для записи E2E Марина Аналитикова.",
        expected=(
            "Мила сразу вызывает route-interview в 2. Interviews external/Analyst (не "
            "reroute-recording — запись ещё не сохранена), без переспрашивания, и сообщает итог "
            "со ссылками на карточку Notion и запись."
        ),
    )
    ctx.check_cli(turn, must=("route-interview",), must_not=("reroute-recording",))
    state = ctx.wait_for(lambda s: terminal_sent(s, 1), timeout=120)
    ctx.check_completed(state, item)
    ctx.check("Открытых вопросов после маршрута", 0, len(ctx.open_reviews(state)))
