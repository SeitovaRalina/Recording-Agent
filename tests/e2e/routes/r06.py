"""R06 — calendar problems: no Telemost link, no event, duplicated event; one reply, one answer."""

from __future__ import annotations

from tests.e2e.lib.route import RouteCtx
from tests.e2e.routes.common import EXTERNAL, SCAN, SPOTS, terminal_sent

TITLE = "Проблемы календаря"
CATALOG = "B2, B3, B5, C7, G1, J2"
TARGET = "2"


def body(ctx: RouteCtx) -> None:
    no_link = ctx.interview(
        "E2E Анна Безссылкина",
        spot_ids=[SPOTS["python"]],
        description="Созвон с кандидатом",
        expected_folder=f"{EXTERNAL}/Python",
    )
    no_event = ctx.interview("E2E Борис Бессобытийный", create_card=False, event=False)
    twin_event = ctx.interview(
        "E2E Вера Двойная",
        spot_ids=[SPOTS["python"]],
        duplicate_event=True,
        expected_folder=f"{EXTERNAL}/Python",
    )
    turn = ctx.say(
        SCAN,
        scenario=(
            "R06. Три новые записи с проблемами календаря: (1) у события нет ссылки Телемоста — "
            "низкая уверенность совпадения; (2) события в календаре нет вообще; (3) в календаре "
            "два одинаковых события на это время."
        ),
        expected=(
            "Мила вызывает scan и questions и отвечает ОДНИМ сообщением: сколько записей найдено и "
            "один нумерованный список из трёх вопросов с вариантами, рекомендацией и примером "
            "ответа. Ничего не сохраняет наугад."
        ),
    )
    ctx.check_cli(turn, must=("scan", "questions"), must_not=("route-interview",))
    state = ctx.observe(notion=False)
    ctx.check_waiting(state, no_link, "low_confidence")
    ctx.check_waiting(state, no_event, "no_compatible_event")
    ctx.check_waiting(state, twin_event, "multiple_eligible_events")

    ctx.say(
        "1 — да, это то самое событие. 2 — это не собеседование, пропусти. "
        "3 — любое из двух, они одинаковые",
        scenario="R06. Рекрутер отвечает на все три вопроса одним сообщением.",
        expected=(
            "Мила вызывает questions, затем answer ровно с тремя действиями: подтверждение события "
            "для первой, пропуск второй, выбор первого из событий для третьей; перечисляет, как "
            "поняла ответ; затем доводит 1 и 3 до сохранения (папка Python однозначна) и сообщает "
            "итог со ссылками."
        ),
    )
    state = ctx.wait_for(lambda s: terminal_sent(s, 2), timeout=240)
    ctx.check_completed(state, no_link)
    ctx.check_completed(state, twin_event)
    rec = ctx.recording(state, no_event) or {}
    ctx.check(f"{no_event.candidate}: пропущена", "ignored", rec.get("status"))
    ctx.check("Открытых вопросов после маршрута", 0, len(ctx.open_reviews(state)))
