"""R10 — move a stored recording, then reassign it to another Notion card."""

from __future__ import annotations

from tests.e2e.lib.route import RouteCtx
from tests.e2e.routes.common import EXTERNAL, INTERNAL, SCAN, SPOTS, terminal_sent

TITLE = "Перенос и перепривязка"
CATALOG = "K1, K3, F1"
TARGET = "4 (скан + перенос + перепривязка с подтверждением)"


def body(ctx: RouteCtx) -> None:
    item = ctx.interview(
        "E2E Зоя Переносова", spot_ids=[SPOTS["python"]], expected_folder=f"{EXTERNAL}/Python"
    )
    other = ctx.card("E2E Зоя Другая", spot_ids=[SPOTS["python"]])
    ctx.say(
        SCAN,
        scenario="R10. Одна новая запись, папка однозначна (Python во внешних).",
        expected="Мила сохраняет запись сама в одном ходе и сообщает итог со ссылками.",
    )
    state = ctx.wait_for(lambda s: terminal_sent(s, 1), timeout=180)
    ctx.check_completed(state, item)
    before = ctx.recording(state, item) or {}

    turn = ctx.say(
        f"Перенеси запись {item.candidate} во внутренние, в Uncategorised",
        scenario="R10 (K1). Рекрутер просит перенести уже сохранённую запись.",
        expected=(
            "Мила вызывает status (запись completed), destinations и reroute-recording (не "
            "route-interview) в 3. Interviews internal/Uncategorised; сообщает новую ссылку."
        ),
    )
    ctx.check_cli(turn, must=("reroute-recording",), must_not=("route-interview",))
    state = ctx.observe()
    after = ctx.recording(state, item) or {}
    ctx.check(
        "Папка после переноса",
        f"{INTERNAL}/Uncategorised",
        after.get("synology_folder_path"),
    )
    old_path = before.get("synology_file_path") or ""
    exists = ctx.syno_exists([old_path, after.get("synology_file_path") or ""])
    ctx.check("Старого файла нет", False, exists.get(old_path))
    ctx.check("Новый файл есть", True, exists.get(after.get("synology_file_path") or ""))
    card = state["cards"].get(after.get("notion_page_id") or "", {})
    ctx.check("Ссылка в Notion обновлена", after.get("synology_share_url"), card.get("recording"))
    if after.get("synology_file_path"):
        ctx.register_cleanup("Файл Synology", after["synology_file_path"], "удалить (с маркером)")

    ctx.say(
        f"Эту запись надо привязать к другой карточке: {other['url']}",
        scenario="R10 (K3). Рекрутер просит перепривязать запись к другой карточке Notion.",
        expected=(
            "Мила вызывает notion-reassignment-resolve/propose, показывает, куда перепривяжет "
            "(имя и ссылка целевой карточки), и просит явное подтверждение; ничего не меняет."
        ),
    )
    turn = ctx.say(
        "Да, подтверждаю",
        scenario="R10 (K3). Явное подтверждение перепривязки.",
        expected=(
            "Мила вызывает notion-reassignment-confirm; сообщает, что запись привязана к новой "
            "карточке, а из старой ссылка убрана."
        ),
    )
    ctx.check_cli(turn, must=("notion-reassignment-confirm",))
    state = ctx.observe()
    rec = ctx.recording(state, item) or {}
    ctx.check(
        "Запись привязана к новой карточке",
        other["id"].replace("-", ""),
        (rec.get("notion_page_id") or "").replace("-", ""),
    )
    old_card = remote_card(ctx, before.get("notion_page_id") or "")
    ctx.check("В старой карточке ссылки нет", True, not old_card.get("recording"))


def remote_card(ctx: RouteCtx, page_id: str) -> dict:
    from tests.e2e.lib import remote

    return remote.stand("notion_card_get", {"id": page_id}) if page_id else {}
