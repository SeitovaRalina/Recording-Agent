"""R04 — two Notion cards with the same name: Mila shows both, the recruiter picks one."""

from __future__ import annotations

from tests.e2e.lib.route import RouteCtx
from tests.e2e.routes.common import EXTERNAL, SCAN, SPOTS, terminal_sent

TITLE = "Тёзки в Notion"
CATALOG = "C5, C6, F1, H2"
TARGET = "2"


def body(ctx: RouteCtx) -> None:
    item = ctx.interview(
        "E2E Ирина Лебедева", spot_ids=[SPOTS["python"]], expected_folder=f"{EXTERNAL}/Backend"
    )
    twin = ctx.card("E2E Ирина Лебедева", spot_ids=[SPOTS["java"]])
    turn = ctx.say(
        SCAN,
        scenario=(
            "R04. Одна новая запись «Собеседование (E2E Ирина Лебедева)». В Notion две карточки с "
            "этим именем: одна со спотом «Python-разработчик @Т-банк», другая — «Java-разработчик "
            "@Т-банк»."
        ),
        expected=(
            "Мила вызывает scan и questions и в том же ответе показывает обе карточки (имя, спот, "
            "ссылка на Notion), не схлопывая их, и просит выбрать одну; даёт пример ответа."
        ),
    )
    ctx.check_cli(turn, must=("scan",), must_not=("route-interview",))
    state = ctx.observe(notion=False)
    ctx.check_waiting(state, item, "multiple_candidates")
    both = all(c["url"][-32:] in turn.reply for c in (item.card or {}, twin) if c)
    ctx.check("В вопросе есть ссылки на обе карточки", True, both)

    turn = ctx.say(
        "Та, что по Java",
        scenario="R04. Рекрутер выбирает карточку по споту.",
        expected=(
            "Мила сопоставляет ответ с карточкой со спотом Java, вызывает answer; когда бэкенд "
            "попросит папку — сама выбирает единственную подходящую (2. Interviews external/"
            "Backend) и вызывает route-interview в том же ходе; сообщает итог со ссылками."
        ),
    )
    ctx.check_cli(turn, must=("answer",))
    state = ctx.wait_for(lambda s: terminal_sent(s, 1), timeout=180)
    ctx.check_completed(state, item)
    rec = ctx.recording(state, item) or {}
    ctx.check(
        "Выбрана карточка со спотом Java",
        twin["id"].replace("-", ""),
        (rec.get("notion_page_id") or "").replace("-", ""),
    )
