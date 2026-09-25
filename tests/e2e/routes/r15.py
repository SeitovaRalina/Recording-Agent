"""R15 — resilience: Backend down during a turn, Backend restart during a scan."""

from __future__ import annotations

import threading
import time

from tests.e2e.lib import remote
from tests.e2e.lib.route import RouteCtx
from tests.e2e.routes.common import EXTERNAL, SCAN, SPOTS

TITLE = "Устойчивость"
CATALOG = "I5, N4, A3, N1"
TARGET = "— (проверки отказов)"

SCAN_ARGS = (
    "scan",
    "--recruiter-user-id",
    "z1cn9tz3opg6fm7e8d7phcs88r",
    "--mattermost-dm-channel-id",
    "gg3pjz8uypf3xxs33o5hhyy3ny__z1cn9tz3opg6fm7e8d7phcs88r",
)


def body(ctx: RouteCtx) -> None:
    # I5: Backend is down while Mila handles a request.
    ctx.container("stop", "recording-agent-backend-1")
    try:
        turn = ctx.say(
            SCAN,
            scenario="R15 (I5). Бэкенд недоступен.",
            expected=(
                "Мила честно сообщает, что сервис обработки записей сейчас недоступен и просит "
                "повторить позже; ничего не выдумывает, не лезет в файлы."
            ),
        )
    finally:
        ctx.container("start", "recording-agent-backend-1")
    ctx.check_cli(turn, must=("scan",))
    remote.bash(
        "for i in $(seq 1 40); do s=$(docker inspect -f '{{.State.Health.Status}}' "
        'recording-agent-backend-1); [ "$s" = healthy ] && break; sleep 3; done'
    )

    # N4 + A3: restart the Backend in the middle of a scan, then rescan with the same key.
    item = ctx.interview(
        "E2E Сергей Рестартов", spot_ids=[SPOTS["analyst"]], expected_folder=f"{EXTERNAL}/Analyst"
    )
    key = f"e2e-{ctx.session}-scan"
    worker = threading.Thread(target=lambda: ctx.skill_cli(*SCAN_ARGS, "--idempotency-key", key))
    worker.start()
    time.sleep(4)
    remote.bash("docker restart recording-agent-backend-1 >/dev/null")
    ctx.stand_notes.append("`docker restart recording-agent-backend-1` во время скана")
    worker.join(timeout=420)
    remote.bash(
        "for i in $(seq 1 40); do s=$(docker inspect -f '{{.State.Health.Status}}' "
        'recording-agent-backend-1); [ "$s" = healthy ] && break; sleep 3; done'
    )
    first = ctx.skill_cli(*SCAN_ARGS, "--idempotency-key", key)
    second = ctx.skill_cli(*SCAN_ARGS, "--idempotency-key", key)
    ctx.check("A3: повтор скана с тем же ключом принят", True, bool(second.get("ok")))
    del first
    state = ctx.observe(notion=False)
    ctx.check("N4: одна строка на файл после рестарта", 1, len(state["recordings"]))
    ctx.check_waiting(state, item, "storage_destination_required")
