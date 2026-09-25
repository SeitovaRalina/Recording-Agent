"""E2E runner. Manual, against the prod stand. Not part of the regular pytest run.

    python -u -X utf8 -m tests.e2e.run R01 [R02 ...] [--run-id 2026-09-24_1]

Reports: tests/e2e/reports/<run-id>/<route>.md (template: reports/TEMPLATE.md).
Before each route the Notion proxy is probed; a route is skipped (not failed) when the
infrastructure is down for longer than --wait-infra minutes.
"""

from __future__ import annotations

import argparse
import importlib
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from tests.e2e.lib import remote
from tests.e2e.lib.route import REPORTS, RouteCtx, run_route


def next_run_id() -> str:
    today = datetime.now(ZoneInfo("Asia/Omsk")).strftime("%Y-%m-%d")
    n = 1
    while (REPORTS / f"{today}_{n}").exists():
        n += 1
    return f"{today}_{n}"


def notion_reachable(wait_minutes: int) -> bool:
    deadline = time.monotonic() + wait_minutes * 60
    while True:
        try:
            remote.stand("notion_cards", {"limit": 1}, timeout=180)
            return True
        except remote.RemoteError:
            if time.monotonic() > deadline:
                return False
            time.sleep(60)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("routes", nargs="+")
    parser.add_argument("--run-id")
    parser.add_argument("--wait-infra", type=int, default=10)
    args = parser.parse_args()
    run_id = args.run_id or next_run_id()
    for route_id in args.routes:
        if not notion_reachable(args.wait_infra):
            print(f"{route_id}: ⏸ пропущен — Notion недоступен дольше {args.wait_infra} мин")
            continue
        module = importlib.import_module(f"tests.e2e.routes.{route_id.lower()}")
        ctx = RouteCtx(route_id.upper(), module.TITLE, run_id, module.CATALOG, module.TARGET)
        path = run_route(ctx, module.body)
        print(f"{route_id}: {ctx.verdict()} -> {path}")


if __name__ == "__main__":
    main()
