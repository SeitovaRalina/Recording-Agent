"""R07 — three recordings, partial answers and noise between them."""

from __future__ import annotations

from tests.e2e.lib.route import RouteCtx
from tests.e2e.routes.common import EXTERNAL, INTERNAL, SCAN, SPOTS, terminal_sent

TITLE = "Пачка из трёх записей, частичные ответы"
CATALOG = "G1, G2, G3, G4, G5, G8, H1, H2, D2"
TARGET = "3 (+2 посторонних)"


def body(ctx: RouteCtx) -> None:
    first = ctx.interview(
        "E2E Глеб Первый", spot_ids=[SPOTS["analyst"]], expected_folder=f"{EXTERNAL}/Analyst"
    )
    second = ctx.interview(
        "E2E Дарья Вторая", spot_ids=[SPOTS["analyst"]], expected_folder=f"{INTERNAL}/Analyst"
    )
    third = ctx.interview(
        "E2E Егор Третий", spot_ids=[SPOTS["analyst"]], expected_folder=f"{INTERNAL}/Analyst"
    )
    turn = ctx.say(
        SCAN,
        scenario=(
            "R07. Три новые записи, у всех спот «Бизнес-аналитик @Т-банк»; папка Analyst есть во "
            "внешних и во внутренних — для каждой нужен выбор."
        ),
        expected=(
            "Мила одним сообщением сообщает о трёх записях и задаёт нумерованные вопросы о папке "
            "(можно одним общим вопросом с перечнем кандидатов), с рекомендацией и примером ответа."
        ),
    )
    ctx.check_cli(turn, must=("scan", "destinations"), must_not=("route-interview",))

    ctx.say(
        "Какая сегодня погода в Омске?",
        scenario="R07 (G4). Постороннее сообщение при открытых вопросах.",
        expected=(
            "Мила не трогает вопросы (никаких answer/route-interview), вежливо отвечает, что это "
            "вне её задач, и напоминает про открытые вопросы одной строкой."
        ),
    )
    state = ctx.observe(notion=False)
    for item in (first, second, third):
        ctx.check_waiting(state, item, "storage_destination_required")

    turn = ctx.say(
        f"Запись {first.candidate} — во внешние, остальные решу позже",
        scenario="R07 (G2). Ответ только на один вопрос из трёх.",
        expected=(
            "Мила сохраняет только первую запись во внешние Analyst (route-interview), остальные "
            "две оставляет открытыми и явно говорит, что они ждут ответа."
        ),
    )
    ctx.check_cli(turn, must=("route-interview",))
    state = ctx.wait_for(lambda s: terminal_sent(s, 1), timeout=180)
    ctx.check_completed(state, first)
    ctx.check_waiting(state, second, "storage_destination_required")
    ctx.check_waiting(state, third, "storage_destination_required")

    ctx.say(
        "Ок, спасибо",
        scenario="R07 (G5). Подтверждение без ответа на вопросы.",
        expected="Мила ничего не отправляет в бэкенд и не считает это ответом на вопросы.",
    )
    state = ctx.observe(notion=False)
    ctx.check_waiting(state, second, "storage_destination_required")

    ctx.say(
        "Оставшиеся две — во внутренние",
        scenario="R07. Ответ на оставшиеся вопросы.",
        expected=(
            "Мила сохраняет обе оставшиеся записи во внутренние Analyst и сообщает итог по каждой "
            "со ссылками."
        ),
    )
    state = ctx.wait_for(lambda s: terminal_sent(s, 3), timeout=300)
    ctx.check_completed(state, second)
    ctx.check_completed(state, third)
    ctx.check("Открытых вопросов после маршрута", 0, len(ctx.open_reviews(state)))
