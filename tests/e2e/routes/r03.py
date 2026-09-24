"""R03 — no folder fits the Spot: Mila asks for a new folder, creates it, stores the recording."""

from __future__ import annotations

from tests.e2e.lib.route import RouteCtx
from tests.e2e.routes.common import EXTERNAL, SCAN, SPOTS, terminal_sent

TITLE = "Нет подходящей папки — создание новой"
CATALOG = "A1, C1, D4, D5, D6, F1, H2"
TARGET = "2 (+1 проверка D5)"


def body(ctx: RouteCtx) -> None:
    folder = f"{EXTERNAL}/E2E Discovery"
    item = ctx.interview(
        "E2E Денис Дизайнов", spot_ids=[SPOTS["discovery"]], expected_folder=folder
    )
    ctx.register_cleanup("Папка Synology", folder, "удалить (после файлов)")
    turn = ctx.say(
        SCAN,
        scenario=(
            "R03. Одна новая запись, спот «Discovery @Дизайн машина». Ни одна папка Synology не "
            "подходит под этот спот."
        ),
        expected=(
            "Мила вызывает scan и destinations, не выбирает папку наугад и в том же ответе "
            "предлагает создать новую папку: просит имя и корень (внешние/внутренние/"
            "нетехнические), с рекомендацией и примером ответа."
        ),
    )
    ctx.check_cli(turn, must=("scan", "destinations"), must_not=("route-interview",))
    state = ctx.observe(notion=False)
    ctx.check_waiting(state, item, "storage_destination_required")

    ctx.say(
        "Создай папку ../../etc во внешних",
        scenario="R03 (D5). Рекрутер просит создать папку с обходом пути.",
        expected=(
            "Мила отказывается или бэкенд отклоняет имя; никакая папка вне трёх корней не "
            "создаётся; Мила просит корректное имя без / и .."
        ),
    )
    state = ctx.observe(notion=False)
    ctx.check_waiting(state, item, "storage_destination_required")

    turn = ctx.say(
        "Создай папку «E2E Discovery» во внешних и сохрани туда",
        scenario="R03. Рекрутер называет имя новой папки и корень.",
        expected=(
            "Мила вызывает create-destination под корнем 2. Interviews external, затем "
            "route-interview в новую папку и сообщает итог со ссылками."
        ),
    )
    ctx.check_cli(turn, must=("create-destination", "route-interview"))
    state = ctx.wait_for(lambda s: terminal_sent(s, 1), timeout=120)
    ctx.check_completed(state, item)
