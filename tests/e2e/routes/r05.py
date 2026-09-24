"""R05 — the card has several Spots: Mila asks which project the interview was for."""

from __future__ import annotations

from tests.e2e.lib.route import RouteCtx
from tests.e2e.routes.common import EXTERNAL, SCAN, SPOTS, terminal_sent

TITLE = "Несколько спотов у карточки"
CATALOG = "C3, C4, F1, H2"
TARGET = "2"


def body(ctx: RouteCtx) -> None:
    item = ctx.interview(
        "E2E Павел Двуспотов",
        spot_ids=[SPOTS["python"], SPOTS["java"]],
        expected_folder=f"{EXTERNAL}/Backend",
    )
    turn = ctx.say(
        SCAN,
        scenario=(
            "R05. Одна новая запись. У карточки кандидата два спота: «Python-разработчик @Т-банк» "
            "и «Java-разработчик @Т-банк»."
        ),
        expected=(
            "Мила вызывает scan и questions и в том же ответе спрашивает, по какому проекту было "
            "собеседование, перечисляя оба спота (название и ссылка), без выбора наугад."
        ),
    )
    ctx.check_cli(turn, must=("scan",), must_not=("route-interview",))
    state = ctx.observe(notion=False)
    ctx.check_waiting(state, item, "multiple_spots")

    turn = ctx.say(
        "По джаве",
        scenario="R05 (C4). Рекрутер отвечает частичным названием спота.",
        expected=(
            "Мила сопоставляет «по джаве» со спотом «Java-разработчик @Т-банк», вызывает answer, "
            "затем сама выбирает единственную подходящую папку 2. Interviews external/Backend и "
            "вызывает route-interview в том же ходе; сообщает итог со ссылками."
        ),
    )
    ctx.check_cli(turn, must=("answer",))
    state = ctx.wait_for(lambda s: terminal_sent(s, 1), timeout=180)
    ctx.check_completed(state, item)
    rec = ctx.recording(state, item) or {}
    ctx.check("Выбранный спот", "Java-разработчик @Т-банк", rec.get("project_or_spot"))
