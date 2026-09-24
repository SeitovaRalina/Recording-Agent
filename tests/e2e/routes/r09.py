"""R09 — Notion goes down mid-transfer; the stored recording waits for Notion and resumes."""

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
                "Мила вызывает route-interview и честно сообщает: файл сохранён в Synology, "
                "ссылка есть, а карточку Notion обновить пока не удалось (Notion временно "
                "недоступен), это будет сделано при следующей проверке. Не утверждает, что "
                "ссылка уже в карточке."
            ),
        )
    finally:
        ctx.container("start")
    # Since the R12-D1 fix a transient Notion failure is not terminal: the stored recording stays
    # at synology_link_created and the next scan writes the card; no error DM is sent.
    state = ctx.observe(notion=False)
    rec = ctx.recording(state, item) or {}
    ctx.check("После сбоя: запись ждёт Notion", "synology_link_created", rec.get("status"))
    ctx.check(
        "После сбоя: причина", "notion_temporarily_unavailable", rec.get("error_message")
    )
    failed_dm = [o for o in state["outbox"] if ":failed:" in str(o["dedupe_key"])]
    ctx.check("Нет уведомления об ошибке", 0, len(failed_dm))
    uploaded = rec.get("synology_file_path")

    turn = ctx.say(
        "Notion снова работает, повтори сохранение",
        scenario="R09 (D3). Рекрутер просит повторить после ошибки.",
        expected=(
            "Мила вызывает status, видит, что запись ждёт Notion, и запускает scan (или "
            "route-interview) — бэкенд дописывает карточку; сообщает итог со ссылками. Второй "
            "копии файла нет, ссылка та же."
        ),
    )
    ran = ctx.cli(turn)
    ctx.check(
        "Мила возобновила запись",
        "scan или route-interview",
        " → ".join(ran) or "—",
        ok="scan" in ran or "route-interview" in ran,
    )
    ctx.check_cli(turn, must_not=("reroute-recording",))
    state = ctx.wait_for(
        lambda s: any(":completed:" in str(o["dedupe_key"]) for o in s["outbox"]), timeout=180
    )
    ctx.check_completed_after_retry(state, item, uploaded)
