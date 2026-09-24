"""Level 2: fast Backend-only checks without Mila (catalog §2, "Уровень 2").

    python -X utf8 -m tests.e2e.level2 [--run-id 2026-09-24_1]

HTTP boundary checks run on the server against the loopback Backend; the secret is read there
from the OpenClaw env file and never printed. Calendar matching cases are seeded as one batch and
processed by one LLM-free scan. The report uses reports/TEMPLATE.md (section 3 = case table).
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta

from tests.e2e.lib import remote
from tests.e2e.lib.route import RouteCtx, run_route

TITLE = "Быстрые проверки бэкенда без Милы"
CATALOG = "M1, M2, M3, L4, G10, E6, B4, B6, B7, B8, B9, B11, A5, A7"
TARGET = "0"

USER = "z1cn9tz3opg6fm7e8d7phcs88r"
DM = "gg3pjz8uypf3xxs33o5hhyy3ny__z1cn9tz3opg6fm7e8d7phcs88r"

_HTTP = r"""
set -a; . /etc/openclaw/gateway.env; set +a
python3 - <<'EOF'
import json, os, urllib.request, urllib.error
BASE = os.environ["RECORDING_AGENT_BACKEND_URL"].rstrip("/")
SECRET = os.environ["RECORDING_AGENT_BACKEND_SECRET"]
cases = json.loads('''__CASES__''')
out = []
for c in cases:
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if c.get("auth") == "ok":
        headers["Authorization"] = "Bearer " + SECRET
    elif c.get("auth") == "bad":
        headers["Authorization"] = "Bearer wrong-" + "x" * 16
    data = json.dumps(c["body"]).encode() if "body" in c else None
    req = urllib.request.Request(BASE + c["path"], data=data, method=c["method"], headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            status, body = r.status, r.read(2000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        status, body = e.code, e.read(2000).decode("utf-8", "replace")
    out.append({"id": c["id"], "status": status, "body": body[:300]})
print("@@L2@@" + json.dumps(out, ensure_ascii=False))
EOF
"""


def http_cases(ctx: RouteCtx, completed: dict | None) -> None:
    cases = [
        {
            "id": "M1 без секрета",
            "method": "GET",
            "path": f"/tools/recordings/status?recruiter_user_id={USER}",
            "expect": [401],
        },
        {
            "id": "M1 неверный секрет",
            "method": "GET",
            "auth": "bad",
            "path": f"/tools/recordings/status?recruiter_user_id={USER}",
            "expect": [401],
        },
        {
            "id": "M2 чужой рекрутер: статус",
            "method": "GET",
            "auth": "ok",
            "path": "/tools/recordings/status?recruiter_user_id=foreign-user-000000000000",
            "expect": [403, 404, 409],
        },
        {
            "id": "M2 чужая личка: скан",
            "method": "POST",
            "auth": "ok",
            "path": "/tools/scans/trigger",
            "body": {
                "recruiter_user_id": USER,
                "mattermost_dm_channel_id": "attacker__dm",
                "idempotency_key": "e2e-level2-m2",
            },
            "expect": [403, 404, 409],
        },
        {
            "id": "M2 чужая личка: вопросы",
            "method": "GET",
            "auth": "ok",
            "path": f"/tools/questions?recruiter_user_id={USER}"
            "&mattermost_dm_channel_id=attacker__dm",
            "expect": [403, 404, 409],
        },
        {
            "id": "L4 подтверждение несуществующего превью",
            "method": "POST",
            "auth": "ok",
            "path": "/tools/cleanup/previews/00000000-0000-4000-8000-000000000000/confirm",
            "body": {
                "recruiter_user_id": USER,
                "mattermost_dm_channel_id": DM,
                "capability": "x" * 32,
                "snapshot_hash": "0" * 64,
                "idempotency_key": "e2e-level2-l4",
            },
            "expect": [403, 404, 409],
        },
        {
            "id": "E6 активация задания с чужим nonce",
            "method": "POST",
            "path": "/internal/routing-jobs/00000000-0000-4000-8000-000000000000/activate",
            "body": {"dispatch_nonce": "n" * 32},
            "expect": [401, 403, 404, 409, 422],
        },
    ]
    if completed:
        cases += [
            {
                "id": "M3 сырой путь вместо ID папки",
                "method": "POST",
                "auth": "ok",
                "path": f"/tools/recordings/{completed['id']}/route-interview",
                "body": {
                    "recruiter_user_id": USER,
                    "mattermost_dm_channel_id": DM,
                    "destination_id": "/home/Recruiting-E",
                    "expected_version": completed["version"],
                    "idempotency_key": "e2e-level2-m3",
                },
                "expect": [400, 404, 409, 422],
            },
            {
                "id": "G10 устаревшая версия записи",
                "method": "POST",
                "auth": "ok",
                "path": f"/tools/recordings/{completed['id']}/route-interview",
                "body": {
                    "recruiter_user_id": USER,
                    "mattermost_dm_channel_id": DM,
                    "destination_id": "00000000-0000-4000-8000-000000000000",
                    "expected_version": max(0, completed["version"] - 1),
                    "idempotency_key": "e2e-level2-g10",
                },
                "expect": [404, 409, 422],
            },
        ]
    script = _HTTP.replace("__CASES__", json.dumps(cases, ensure_ascii=False))
    out = remote.bash(script, check=False)
    results = json.loads(out.split("@@L2@@", 1)[1]) if "@@L2@@" in out else []
    by_id = {r["id"]: r for r in results}
    for c in cases:
        r = by_id.get(c["id"], {"status": "нет ответа", "body": out[-200:]})
        ctx.check(
            c["id"],
            " / ".join(str(x) for x in c["expect"]),
            f"{r['status']} {str(r.get('body', ''))[:120]}",
            ok=r["status"] in c["expect"],
        )


def matching_batch(ctx: RouteCtx) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    base = now - timedelta(minutes=40)
    cases: list[tuple[str, dict, str]] = []

    def add(label: str, reason: str, **kwargs: object) -> None:
        item = ctx.interview(label, **kwargs)  # type: ignore[arg-type]
        cases.append((label, {"item": item}, reason))

    # B4: the file title does not equal the event summary.
    add(
        "E2E Б4 Название",
        "no_compatible_event",
        create_card=False,
        start_utc=base,
        file_title=f"Другое название {ctx.tag}",
    )
    add(
        "E2E Б6 Моисобытия",
        "unmonitored_only",
        create_card=False,
        start_utc=base + timedelta(minutes=2),
        calendar="Мои события",
    )
    add(
        "E2E Б8 Окно",
        "no_compatible_event",
        create_card=False,
        start_utc=base + timedelta(minutes=4),
        file_offset_s=50 * 60,  # window is [start-15m, end+15m]; event is 30 min
    )
    add(
        "E2E Б9 Имяфайла",
        "filename_invalid",
        create_card=False,
        start_utc=base + timedelta(minutes=6),
        disk_name=f"запись без шаблона {ctx.tag}.webm",
    )
    add(
        "E2E Б11 Каллинк",
        "no_candidate_found",
        create_card=False,
        start_utc=base + timedelta(minutes=8),
        description=(
            "Бронирование через https://calink.ru/e2e — https://telemost.360.yandex.ru/j/551"
        ),
    )
    scan = ctx.skill_cli(
        "scan",
        "--recruiter-user-id",
        USER,
        "--mattermost-dm-channel-id",
        DM,
        "--idempotency-key",
        f"e2e-{ctx.session}-scan",
    )
    ctx.check(
        "Скан без LLM прошёл",
        True,
        scan.get("ok"),
    )
    result = scan.get("result") or {}
    ctx.check(
        "A5: старые файлы пропущены и посчитаны",
        "> 0",
        result.get("skipped_legacy"),
        ok=(result.get("skipped_legacy") or 0) > 0,
    )
    state = ctx.observe(notion=False)
    for label, data, reason in cases:
        item = data["item"]
        rec = ctx.recording(state, item) or {}
        ctx.check(
            f"{label}: причина вопроса",
            reason,
            f"{rec.get('status')} / {rec.get('manual_review_reason')}",
            ok=rec.get("manual_review_reason") == reason,
        )
    processed = remote.stand(
        "sql",
        {
            "query": "select count(*) as n from recordings where "
            "disk_filename like '%Максим Соболев%'"
        },
    )
    ctx.check("A7: файл с processed=true не взят в работу", 0, processed[0]["n"])


def body(ctx: RouteCtx) -> None:
    completed = remote.stand(
        "sql",
        {
            "query": "select id, version from recordings where status = 'completed' and "
            "disk_filename like '%E2E%' order by completed_at desc limit 1"
        },
    )
    http_cases(ctx, completed[0] if completed else None)
    matching_batch(ctx)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    ctx = RouteCtx("level2", TITLE, args.run_id, CATALOG, TARGET)
    path = run_route(ctx, body)
    print(f"level2: {ctx.verdict()} -> {path}")


if __name__ == "__main__":
    main()
