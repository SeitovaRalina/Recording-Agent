"""R09 — Notion goes down mid-transfer; the recording fails cleanly and is retried via Mila."""

from __future__ import annotations

from tests.e2e.lib.route import RouteCtx
from tests.e2e.routes.common import EXTERNAL, SCAN, SPOTS

TITLE = "Ошибка переноса и повтор"
CATALOG = "F5, N2, H3, D3 (повтор), F1, F2"
TARGET = "3"


def body(ctx: RouteCtx) -> None:
    item = ctx.interview(
        "E2E Жанна Повторова", spot_ids=[SPOTS["analyst"]], expected_folder=f"{EXTERNAL}/Analyst"
    )
    turn = ctx.say(
        SCAN,
        scenario="R09. Одна новая запись, папка неоднозначна (Analyst во внешних и внутренних).",
        expected="Мила задаёт один вопрос о папке с рекомендацией.",
    )
    ctx.check_cli(turn, must=("scan",), must_not=("route-interview",))

    # Failure injection: the Notion proxy is down while the transfer writes the Notion card.
    ctx.container("stop")
    try:
        ctx.say(
            "Во внешние",
            scenario=(
                "R09 (F5/H3). Рекрутер выбрал папку, но Notion недоступен: файл загрузится в "
                "Synology, а запись в карточку Notion не пройдёт."
            ),
            expected=(
                "Мила вызывает route-interview; получив ошибку, честно и понятно сообщает, что "
                "запись сохранена не до конца из-за временной ошибки Notion, без технических "
                "деталей, и предлагает повторить позже."
            ),
        )
    finally:
        ctx.container("start")
    state = ctx.wait_for(
        lambda s: any(str(o["dedupe_key"]).startswith("terminal:") for o in s["outbox"]),
        timeout=120,
    )
    rec = ctx.recording(state, item) or {}
    ctx.check("После сбоя: статус", "failed", rec.get("status"))
    failed_dm = [o for o in state["outbox"] if ":failed:" in str(o["dedupe_key"])]
    ctx.check("Одно уведомление об ошибке (H3)", 1, len(failed_dm))
    uploaded = rec.get("synology_file_path")

    turn = ctx.say(
        "Notion снова работает, повтори сохранение",
        scenario="R09 (D3). Рекрутер просит повторить после ошибки.",
        expected=(
            "Мила вызывает status, затем route-interview с той же папкой и новым ключом; сообщает "
            "итог со ссылками. Второй копии файла нет."
        ),
    )
    ctx.check_cli(turn, must=("route-interview",), must_not=("reroute-recording",))
    state = ctx.wait_for(
        lambda s: any(":completed:" in str(o["dedupe_key"]) for o in s["outbox"]), timeout=180
    )
    ctx.check_completed_after_retry(state, item, uploaded)
