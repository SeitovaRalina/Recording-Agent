"""Live demo helper: seed one test interview, show its result, remove the calendar event.

    python -u -X utf8 -m tests.e2e.demo go [--spot python|analyst|java|discovery]
    python -u -X utf8 -m tests.e2e.demo preflight [--fix]
    python -u -X utf8 -m tests.e2e.demo prepare [--spot python|analyst|java|discovery]
    python -u -X utf8 -m tests.e2e.demo status
    python -u -X utf8 -m tests.e2e.demo cleanup

`go` = `preflight --fix` then `prepare`; it stops when a check fails. `prepare` creates a
Notion card, a calendar event and a Telemost-style file on Yandex Disk for one `E2E Демо …`
candidate and prints what to write to Mila. It never talks to Mila itself: the
presenter does that in Mattermost. `cleanup` deletes only the demo calendar event; the Notion
card, the Disk source and the Synology file are listed for the batch cleanup that needs approval.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime
from pathlib import Path

from tests.e2e.lib import remote
from tests.e2e.lib.route import OMSK, REPORTS, RouteCtx
from tests.e2e.routes.common import SPOTS

STATE = REPORTS / "demo" / "demo-state.json"
FOLDERS = {
    "python": "Recruiting-E/2. Interviews external/Python",
    "java": "Recruiting-E/2. Interviews external/Backend",
    "analyst": "вопрос: Analyst во внешних или во внутренних",
    "discovery": "вопрос: подходящей папки нет",
}


def prepare(spot: str, *, calink: bool = False) -> None:
    now = datetime.now(OMSK)
    ctx = RouteCtx("DEMO", "Живая демонстрация", "demo", "—", "1")
    ctx.tag = ""  # the time suffix below keeps demo candidates unique
    candidate = f"E2E Демо Кандидатова {now:%H%M}"
    if calink:
        # Reproduces the real calink shape: the calendar event summary/description carry the
        # booking marker and candidate name; the Disk recording keeps Telemost's generic default
        # title, which never matches the event summary by construction (the exact bug the
        # booking-marker pool-entry path exists to handle — see matching.py/current-work.md §3).
        summary = f"Собеседование в Effective c Ралиной Сеитовой ({candidate})"
        description = (
            f"Участник: {candidate} (e2e-demo@example.com)\n"
            "https://telemost.360.yandex.ru/j/5500000000\n"
            "Детали встречи, отмена и перенос: "
            "https://calink.ru/e2e-demo/45min/00000?code=E2EDEMO"
        )
        item = ctx.interview(
            candidate,
            spot_ids=[SPOTS[spot]],
            summary=summary,
            description=description,
            file_title="Ссылка для собеседования с Ралиной Сеитовой",
        )
    else:
        item = ctx.interview(candidate, spot_ids=[SPOTS[spot]])
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(
        json.dumps(
            {
                "candidate": item.candidate,
                "disk_name": item.disk_name,
                "event_url": item.event["url"] if item.event else None,
                "card_url": item.card["url"] if item.card else None,
                "prepared_at": now.isoformat(),
                "spot": spot,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    print(f"Кандидат:        {item.candidate}")
    print(f"Карточка Notion: {item.card['url'] if item.card else '—'}")
    print(f"Файл на Диске:   {item.file['path'] if item.file else '—'}")
    print(f"Ожидаемый итог:  {FOLDERS[spot]}")
    if calink:
        print(f"Заголовок события:   {summary}")
        print(f"Заголовок файла:     {item.disk_name}")
        print(
            "Сценарий: calink-бронь — заголовки НЕ совпадают нарочно, "
            "матч идёт через booking-marker путь"
        )
    print()
    print("Напишите Миле в Mattermost:  Проверь новые записи")


def preflight(*, fix: bool) -> bool:
    """Check that a demo scan will show only the demo recording; park stray E2E files if asked."""
    ok = True

    def line(good: bool, text: str) -> None:
        nonlocal ok
        ok = ok and good
        print(f"{'OK ' if good else '!! '} {text}")

    health = remote.bash(
        "docker inspect -f '{{.State.Health.Status}}' recording-agent-backend-1; "
        "grep -E '^(AUTONOMOUS_ROUTING_ENABLED|YANDEX_SOURCE_MUTATION_ENABLED|"
        "NOTION_WRITES_ENABLED|MATTERMOST_DELIVERY_ENABLED)=' /etc/recording-agent/backend.env",
        check=False,
    ).split()
    line(bool(health) and health[0] == "healthy", f"бэкенд: {health[0] if health else '?'}")
    flags = dict(item.split("=", 1) for item in health[1:] if "=" in item)
    line(flags.get("AUTONOMOUS_ROUTING_ENABLED") == "false", "автовыбор папки выключен")
    line(flags.get("YANDEX_SOURCE_MUTATION_ENABLED") == "false", "исходники на Диске не меняются")
    line(flags.get("NOTION_WRITES_ENABLED") == "true", "запись в Notion включена")
    line(flags.get("MATTERMOST_DELIVERY_ENABLED") == "true", "сообщения в Mattermost включены")

    runner = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
            "Where-Object { $_.CommandLine -like '*tests.e2e.run*' -or "
            "$_.CommandLine -like '*tests.e2e.level2*' } | Measure-Object | "
            "Select-Object -ExpandProperty Count",
        ],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    line(runner in ("", "0"), "E2E-маршруты не запущены")

    try:
        remote.stand("notion_cards", {"limit": 1}, timeout=120)
        line(True, "Notion отвечает")
    except remote.RemoteError:
        line(False, "Notion не отвечает (прокси) — демо пойдёт по плану Б")

    pending = remote.stand(
        "sql",
        {
            "query": "select count(*) as n from manual_reviews where status = 'pending'",
            "params": {},
        },
    )[0]["n"]
    line(pending == 0, f"открытых вопросов: {pending}")

    today = datetime.now(OMSK).date().isoformat()
    files = [f for f in remote.stand("disk_list") if str(f.get("created") or "") >= today]
    names = [f["name"] for f in files]
    known = (
        {
            r["disk_filename"]
            for r in remote.stand(
                "sql",
                {
                    "query": "select disk_filename from recordings "
                    "where disk_filename = any(:names)",
                    "params": {"names": names},
                },
            )
        }
        if names
        else set()
    )
    fresh = [n for n in names if n not in known and n.endswith(".webm")]
    stray_test = [n for n in fresh if "E2E" in n]
    real = [n for n in fresh if "E2E" not in n]
    if stray_test and fix:
        parked = remote.stand("disk_park", {"disk_names": stray_test}).get("parked", [])
        print(f"    убраны в disk:/E2E/aborted/: {len(parked)}")
        stray_test = [n for n in stray_test if n not in parked]
    line(not stray_test, f"лишних тестовых файлов на Диске: {len(stray_test)}")
    if real:
        print(f"    внимание: новые настоящие записи попадут в демо-скан: {real}")
    return ok


def _state() -> dict:
    if not STATE.exists():
        raise SystemExit("Сначала запустите: python -u -X utf8 -m tests.e2e.demo prepare")
    return json.loads(STATE.read_text(encoding="utf-8"))


def status() -> None:
    state = _state()
    observed = remote.stand(
        "observe",
        {
            "disk_names": [state["disk_name"]],
            "outbox_since": state["prepared_at"],
            "notion": True,
            "routing": False,
        },
    )
    for rec in observed.get("recordings", []):
        print(f"Статус:          {rec.get('status')}")
        print(f"Папка Synology:  {rec.get('synology_folder_path') or '—'}")
        print(f"Ссылка:          {rec.get('synology_share_url') or '—'}")
        if rec.get("error_message"):
            print(f"Ошибка:          {rec.get('error_step')}: {rec.get('error_message')}")
    for card in (observed.get("cards") or {}).values():
        print(f"Карточка:        {json.dumps(card, ensure_ascii=False)[:400]}")
    if not observed.get("recordings"):
        print("Запись ещё не найдена — Мила не сканировала Диск.")


def cleanup() -> None:
    state = _state()
    if state.get("event_url"):
        result = remote.stand("calendar_delete", {"urls": [state["event_url"]]})
        print(f"Событие календаря удалено: {result}")
    print("На пакетную уборку с подтверждением: карточка Notion, исходник Диска, файл Synology")
    print(f"  {state.get('card_url')}")
    print(f"  {state.get('disk_name')}")
    Path(STATE).rename(STATE.with_suffix(f".{datetime.now(OMSK):%H%M%S}.done.json"))


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--spot", choices=sorted(SPOTS), default="python")
    prep.add_argument(
        "--calink", action="store_true", help="seed a calink-shaped mismatched-title scenario"
    )
    go = sub.add_parser("go")
    go.add_argument("--spot", choices=sorted(SPOTS), default="python")
    go.add_argument("--force", action="store_true", help="prepare even if a check failed")
    go.add_argument(
        "--calink", action="store_true", help="seed a calink-shaped mismatched-title scenario"
    )
    pre = sub.add_parser("preflight")
    pre.add_argument("--fix", action="store_true", help="park stray E2E files on Disk")
    sub.add_parser("status")
    sub.add_parser("cleanup")
    args = parser.parse_args()
    if args.command == "go":
        if not preflight(fix=True) and not args.force:
            raise SystemExit(
                "Подготовка остановлена: исправьте пункты с !! или запустите с --force"
            )
        prepare(args.spot, calink=args.calink)
    elif args.command == "preflight":
        raise SystemExit(0 if preflight(fix=args.fix) else 1)
    elif args.command == "prepare":
        prepare(args.spot, calink=args.calink)
    elif args.command == "status":
        status()
    else:
        cleanup()


if __name__ == "__main__":
    main()
