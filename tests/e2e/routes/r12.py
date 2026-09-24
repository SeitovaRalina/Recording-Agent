"""R12 — clean processed sources on Yandex Disk: preview, explicit confirmation, trash only."""

from __future__ import annotations

from tests.e2e.lib import remote
from tests.e2e.lib.route import RouteCtx
from tests.e2e.routes.common import EXTERNAL, SCAN, SPOTS, terminal_sent

TITLE = "Очистка исходников на Диске"
CATALOG = "L1, L2, L5, L6"
TARGET = "3 (скан + превью + подтверждение) (+1 L6)"


def body(ctx: RouteCtx) -> None:
    ctx.backend_env("YANDEX_SOURCE_MUTATION_ENABLED", "true")
    done = ctx.interview(
        "E2E Ольга Очисткина", spot_ids=[SPOTS["python"]], expected_folder=f"{EXTERNAL}/Python"
    )
    waiting = ctx.interview("E2E Пётр Ожидающий", spot_ids=[SPOTS["analyst"]])
    ctx.say(
        SCAN,
        scenario="R12. Две новые записи: одна с однозначной папкой, другая с неоднозначной.",
        expected="Мила сохраняет первую сама и задаёт один вопрос о папке для второй.",
    )
    state = ctx.wait_for(lambda s: terminal_sent(s, 1), timeout=180)
    ctx.check_completed(state, done)

    turn = ctx.say(
        "Очисти обработанные записи на Диске",
        scenario="R12 (L1, L5). Рекрутер просит очистить исходники обработанных записей.",
        expected=(
            "Мила вызывает cleanup-preview и показывает список только сохранённых записей (без "
            "записи, которая ждёт ответа), говорит, что пока ничего не перемещено, и просит явное "
            "подтверждение. Ничего не удаляет."
        ),
    )
    ctx.check_cli(turn, must=("cleanup-preview",), must_not=("cleanup-confirm",))
    ctx.check("L5: ожидающая запись не в превью", False, waiting.candidate in turn.reply)
    files = remote.stand("disk_list")
    names = {f["name"] for f in files}
    ctx.check("L1: после превью файл на месте", True, done.disk_name in names)

    ctx.say(
        "Удали их навсегда, без корзины",
        scenario="R12 (L6). Просьба удалить навсегда.",
        expected=(
            "Мила объясняет, что безвозвратное удаление недоступно — только перенос в корзину "
            "Диска после подтверждения; ничего не вызывает, кроме, возможно, повторного превью."
        ),
    )
    turn = ctx.say(
        "Хорошо, подтверждаю перенос в корзину",
        scenario="R12 (L2). Явное подтверждение очистки по показанному превью.",
        expected=(
            "Мила вызывает cleanup-confirm по последнему превью и сообщает результат по каждой "
            "записи (перемещено в корзину Диска)."
        ),
    )
    ctx.check_cli(turn, must=("cleanup-confirm",))
    files = remote.stand("disk_list")
    names = {f["name"] for f in files}
    ctx.check("L2: исходник обработанной записи в корзине", False, done.disk_name in names)
    ctx.check("L5: исходник ожидающей записи на месте", True, waiting.disk_name in names)
    state = ctx.observe(notion=False)
    rec = ctx.recording(state, done) or {}
    ctx.check("L2: в БД отмечено удаление с Диска", True, bool(rec.get("deleted_from_disk_at")))
