"""Live demo helper: seed one test interview, show its result, remove the calendar event.

    python -u -X utf8 -m tests.e2e.demo prepare [--spot python|analyst|java|discovery]
    python -u -X utf8 -m tests.e2e.demo status
    python -u -X utf8 -m tests.e2e.demo cleanup

`prepare` creates a Notion card, a calendar event and a Telemost-style file on Yandex Disk for
one `E2E Демо …` candidate and prints what to write to Mila. It never talks to Mila itself: the
presenter does that in Mattermost. `cleanup` deletes only the demo calendar event; the Notion
card, the Disk source and the Synology file are listed for the batch cleanup that needs approval.
"""

from __future__ import annotations

import argparse
import json
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


def prepare(spot: str) -> None:
    now = datetime.now(OMSK)
    ctx = RouteCtx("DEMO", "Живая демонстрация", "demo", "—", "1")
    ctx.tag = ""  # the time suffix below keeps demo candidates unique
    candidate = f"E2E Демо Кандидатова {now:%H%M}"
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
    print()
    print("Напишите Миле в Mattermost:  Проверь новые записи")


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
    sub.add_parser("status")
    sub.add_parser("cleanup")
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args.spot)
    elif args.command == "status":
        status()
    else:
        cleanup()


if __name__ == "__main__":
    main()
