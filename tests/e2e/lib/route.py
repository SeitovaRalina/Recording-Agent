# ruff: noqa: E501
"""Route context: seeding, Mila turns + judge, deterministic checks, report rendering.

Cleanup policy (catalog §4, D1):
- calendar events created by the runner (`e2e-` UID) are deleted automatically;
- non-terminal recordings of the route are settled (ignored) so they do not leak into later
  routes' questions;
- Disk files, Synology files/markers/folders and Notion test cards are only *registered* in
  `reports/<run>/cleanup.json`; they are removed in one batch after the user confirms.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from tests.e2e.lib import judge as judge_mod
from tests.e2e.lib import mila, remote

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
MSK = ZoneInfo("Europe/Moscow")
OMSK = ZoneInfo("Asia/Omsk")
TELEMOST_LINK = "Ссылка на видеовстречу: https://telemost.360.yandex.ru/j/55{digits}"


class RouteBlocker(RuntimeError):
    """Stop the route: a blocker defect (catalog §2)."""


@dataclass
class Check:
    name: str
    expected: str
    actual: str
    ok: bool


@dataclass
class TurnRecord:
    turn: mila.Turn
    verdict: judge_mod.Verdict | None
    checks: list[Check] = field(default_factory=list)


@dataclass
class Defect:
    id: str
    severity: str  # "блокер" | "не блокер"
    description: str
    status: str = "открыт"
    commit: str = ""


@dataclass
class Interview:
    candidate: str
    summary: str
    disk_name: str
    start_utc: datetime
    event: dict[str, Any] | None = None
    file: dict[str, Any] | None = None
    card: dict[str, Any] | None = None
    expected_folder: str | None = None
    extra_events: list[dict[str, Any]] = field(default_factory=list)


class RouteCtx:
    def __init__(self, route_id: str, title: str, run_id: str, catalog: str, target_messages: str):
        self.route_id = route_id
        self.title = title
        self.run_id = run_id
        self.catalog = catalog
        self.target_messages = target_messages
        self.session = f"{run_id}-{route_id}".lower().replace("_", "-")
        self.started = datetime.now(UTC)
        self.finished: datetime | None = None
        self.turns: list[TurnRecord] = []
        self.checks: list[Check] = []
        self.defects: list[Defect] = []
        self.seed_rows: list[tuple[str, str]] = []
        self.stand_notes: list[str] = []
        self.cleanup_rows: list[tuple[str, str, str]] = []
        self.interviews: list[Interview] = []
        self.conclusions: list[str] = []
        self.error: str = ""
        self._stopped: set[str] = set()
        self._env_restore: dict[str, str] = {}
        self.dir = REPORTS / run_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.attempt = 1
        report = self.dir / f"{route_id}.md"
        if report.exists():
            while (self.dir / f"{route_id}.attempt{self.attempt}.md").exists():
                self.attempt += 1
            report.rename(self.dir / f"{route_id}.attempt{self.attempt}.md")
            artifacts = self.dir / "artifacts" / route_id
            if artifacts.exists():
                artifacts.rename(self.dir / "artifacts" / f"{route_id}.attempt{self.attempt}")
            self.attempt += 1
            self.session += f"-a{self.attempt}"
        (self.dir / "artifacts" / route_id).mkdir(parents=True, exist_ok=True)
        # Test candidates get a per-run/route/attempt tag so leftovers of earlier attempts never
        # become namesakes (they stay in Notion until the batch cleanup).
        self.tag = f"{route_id}-{run_id[5:].replace('-', '')}a{self.attempt}"
        known = self.dir / "defects.json"
        if known.exists():
            for d in json.loads(known.read_text(encoding="utf-8")).get(route_id, []):
                self.defects.append(Defect(**d))

    # ------------------------------------------------------------ seeding

    def unique_minute(self, offset_min: int = 0) -> datetime:
        """Recording start in the recent past, second precision, unique per call."""
        base = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=20 - offset_min)
        return base

    def interview(
        self,
        candidate: str,
        *,
        spot_ids: list[str] | None = None,
        create_card: bool = True,
        summary: str | None = None,
        description: str | None = None,
        start_utc: datetime | None = None,
        event: bool = True,
        calendar: str = "default",
        disk_name: str | None = None,
        file_offset_s: int = 60,
        expected_folder: str | None = None,
        duplicate_event: bool = False,
        file_title: str | None = None,
    ) -> Interview:
        candidate = self.person(candidate)
        start = start_utc or self.unique_minute(len(self.interviews) * 3)
        summary = summary or f"Собеседование ({candidate})"
        rec_start = (start + timedelta(seconds=file_offset_s)).astimezone(MSK)
        name = disk_name or f"{rec_start:%Y-%m-%d_%H%M%S}_{file_title or summary}.webm"
        item = Interview(candidate, summary, name, start, expected_folder=expected_folder)
        if create_card:
            item.card = remote.stand(
                "notion_card_create", {"name": candidate, "spot_ids": spot_ids or []}
            )
            self.register_cleanup("Notion-карточка", item.card["url"], "в корзину Notion")
            self.seed_rows.append(
                (
                    "Карточка Notion",
                    f"`{candidate}`, 📍 Spots: "
                    f"`{', '.join(s['title'] for s in item.card['spots']) or '—'}`, {item.card['url']}",
                )
            )
        digits = hashlib.sha1(name.encode()).hexdigest()[:11]
        digits = "".join(str(int(c, 16) % 10) for c in digits)
        payload: dict[str, Any] = {"run": self.session, "events": [], "files": [{"name": name}]}
        if event:
            for _ in range(2 if duplicate_event else 1):
                payload["events"].append(
                    {
                        "calendar": calendar,
                        "summary": summary,
                        "description": description
                        if description is not None
                        else TELEMOST_LINK.format(digits=digits),
                        "start_utc": start.isoformat(),
                        "minutes": 30,
                    }
                )
        seeded = remote.stand("seed", payload)
        item.event = seeded["events"][0] if seeded["events"] else None
        item.extra_events = seeded["events"][1:]
        item.file = seeded["files"][0]
        if item.event:
            self.seed_rows.append(
                (
                    "Событие календаря",
                    f"`{summary}`, {start.astimezone(OMSK):%Y-%m-%d %H:%M} Омск, "
                    f"календарь `{calendar}`",
                )
            )
        self.seed_rows.append(("Файл на Диске", f"`{item.file['path']}`"))
        self.register_cleanup("Файл на Диске", item.file["path"], "в корзину Диска")
        if expected_folder:
            self.seed_rows.append(("Ожидаемая папка Synology", f"`{expected_folder}`"))
        self.interviews.append(item)
        return item

    def person(self, name: str) -> str:
        """Unique test candidate name: `E2E Олег Тестов` -> `E2E Олег Тестов R01-0924_1a2`."""
        return f"{name} {self.tag}" if name.startswith("E2E ") and self.tag not in name else name

    def card(self, name: str, *, spot_ids: list[str] | None = None) -> dict[str, Any]:
        """Extra Notion card without a recording (namesakes, reassignment targets)."""
        name = self.person(name)
        card = remote.stand("notion_card_create", {"name": name, "spot_ids": spot_ids or []})
        self.register_cleanup("Notion-карточка", card["url"], "в корзину Notion")
        self.seed_rows.append(
            (
                "Карточка Notion (без записи)",
                f"`{name}`, 📍 Spots: `{', '.join(s['title'] for s in card['spots']) or '—'}`, "
                f"{card['url']}",
            )
        )
        return card

    def register_cleanup(self, kind: str, ref: str, action: str) -> None:
        self.cleanup_rows.append((kind, ref, action))

    # ------------------------------------------------------------ Mila

    def say(self, text: str, *, scenario: str, expected: str, judge: bool = True) -> mila.Turn:
        history = [r.turn for r in self.turns]
        turn = mila.turn(self.session, text)
        verdict = judge_mod.judge(scenario, expected, turn, history) if judge else None
        self.turns.append(TurnRecord(turn, verdict))
        if not turn.ok:
            raise RouteBlocker(f"ход Милы не завершился: {turn.error[:300]}")
        return turn

    # ------------------------------------------------------------ checks

    def check(self, name: str, expected: Any, actual: Any, ok: bool | None = None) -> bool:
        passed = (expected == actual) if ok is None else ok
        item = Check(name, str(expected), str(actual), bool(passed))
        self.checks.append(item)
        if self.turns:
            self.turns[-1].checks.append(item)
        return item.ok

    def observe(self, *, notion: bool = True, routing: bool = False) -> dict[str, Any]:
        return remote.stand(
            "observe",
            {
                "disk_names": [i.disk_name for i in self.interviews],
                "outbox_since": self.started.isoformat(),
                "notion": notion,
                "routing": routing,
            },
        )

    def wait_for(
        self, predicate: Callable[[dict[str, Any]], bool], *, timeout: int = 180, every: int = 10
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        state = self.observe(notion=False)
        while not predicate(state) and time.monotonic() < deadline:
            time.sleep(every)
            state = self.observe(notion=False)
        return self.observe()

    def recording(self, state: dict[str, Any], item: Interview) -> dict[str, Any] | None:
        return next((r for r in state["recordings"] if r["disk_filename"] == item.disk_name), None)

    def check_completed(self, state: dict[str, Any], item: Interview) -> None:
        rec = self.recording(state, item)
        self.check(f"{item.candidate}: статус в БД", "completed", rec and rec["status"])
        if not rec:
            return
        path = rec.get("synology_file_path") or ""
        if item.expected_folder:
            self.check(
                f"{item.candidate}: папка Synology",
                item.expected_folder,
                rec.get("synology_folder_path"),
            )
        storage = state["storage"].get(path, {})
        self.check(f"{item.candidate}: файл в Synology", True, storage.get("file"))
        self.check(f"{item.candidate}: маркер владельца", True, storage.get("marker"))
        card = state["cards"].get(rec.get("notion_page_id") or "", {})
        self.check(
            f"{item.candidate}: ссылка в Notion = ссылка записи",
            rec.get("synology_share_url"),
            card.get("recording"),
        )
        event_date = item.start_utc.astimezone(OMSK).date().isoformat()
        self.check(
            f"{item.candidate}: дата интервью в Notion", event_date, (card.get("date") or "")[:10]
        )
        terminal = [
            o
            for o in state["outbox"]
            if str(o.get("dedupe_key", "")).startswith(f"terminal:{rec['id']}:completed:")
        ]
        self.check(
            f"{item.candidate}: одно уведомление бэкенда «готово»",
            "1 × sent",
            f"{len(terminal)} × {','.join(sorted({o['status'] for o in terminal})) or '—'}",
            ok=len(terminal) == 1 and terminal[0]["status"] == "sent",
        )
        if terminal:
            (self.dir / "artifacts" / self.route_id / f"dm-{item.candidate}.txt").write_text(
                str(terminal[0]["payload"].get("message") or terminal[0]["payload"]),
                encoding="utf-8",
            )
        if path:
            self.register_cleanup("Файл Synology", path, "удалить (с маркером)")
            folder, _, name = path.rpartition("/")
            self.register_cleanup(
                "Маркер Synology", f"{folder}/.{name}.recording-agent-owner.json", "удалить"
            )

    def container(self, action: str, name: str = "recording-agent-notion-proxy-1") -> None:
        """Stop/start a stand container to inject an infrastructure failure (R09, R15)."""
        if action not in ("stop", "start") or not name.startswith("recording-agent-"):
            raise ValueError("unsupported container action")
        remote.bash(f"docker {action} {name} >/dev/null")
        self.stand_notes.append(f"`docker {action} {name}` в {datetime.now(OMSK):%H:%M:%S}")
        if action == "stop":
            self._stopped.add(name)
        else:
            self._stopped.discard(name)

    # ------------------------------------------------------------ stand switches

    def backend_env(self, name: str, value: str) -> None:
        """Temporarily set one backend.env flag and recreate the backend on the SAME image.

        The original value is restored in teardown. Only allow-listed flags.
        """
        allowed = {
            "AUTONOMOUS_ROUTING_ENABLED",
            "YANDEX_SOURCE_MUTATION_ENABLED",
            "SUMMARY_LOCAL_TIME",
        }
        if name not in allowed:
            raise ValueError(f"flag {name} is not allowed")
        current = remote.bash(
            f"sed -n 's/^{name}=//p' /etc/recording-agent/backend.env | tail -1", check=False
        ).strip()
        if name not in self._env_restore:
            self._env_restore[name] = current
        remote.bash(_SET_ENV.format(name=name, value=value), timeout=300)
        self.stand_notes.append(f"`{name}={value}` (было `{current or '—'}`), backend пересоздан")

    def skill_cli(self, *args: str) -> dict[str, Any]:
        """Run the skill CLI on the server without an LLM turn (as a scheduled scan would)."""
        quoted = " ".join(f"'{a}'" for a in args)
        out = remote.bash(
            "set -a; . /etc/openclaw/gateway.env; set +a; "
            "cd /srv/openclaw/workspaces/recordings-saver/skills/recording-agent && "
            "runuser -u openclaw -- env RECORDING_AGENT_BACKEND_URL=$RECORDING_AGENT_BACKEND_URL "
            "RECORDING_AGENT_BACKEND_SECRET=$RECORDING_AGENT_BACKEND_SECRET "
            f"python3 scripts/recording_agent.py {quoted}",
            timeout=400,
            check=False,
        )
        try:
            return json.loads(out)
        except json.JSONDecodeError:
            return {"ok": False, "message": out[-500:]}

    def cron_run(self, name: str = "recordings-saver-rout") -> str:
        """Force one run of the Gateway cron job (the autonomous routing dispatcher)."""
        return remote.bash(
            mila.OC
            + f"ID=$(oc cron list 2>/dev/null | awk '/{name}/ {{print $1; exit}}'); "
            + 'oc cron run "$ID" 2>&1 | tail -3',
            timeout=300,
            check=False,
        )

    def syno_exists(self, paths: list[str]) -> dict[str, bool]:
        return remote.stand("syno_exists", {"paths": [p for p in paths if p]})

    def check_completed_after_retry(
        self, state: dict[str, Any], item: Interview, uploaded_before: str | None
    ) -> None:
        self.check_completed(state, item)
        rec = self.recording(state, item) or {}
        if uploaded_before:
            self.check(
                f"{item.candidate}: повтор использовал уже загруженный файл (F2)",
                uploaded_before,
                rec.get("synology_file_path"),
            )

    def open_reviews(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        return [r for r in state["reviews"] if r["status"] == "pending"]

    @staticmethod
    def cli(turn: mila.Turn) -> list[str]:
        """Skill CLI subcommands Mila ran in this turn, in order (chained `&&` calls included)."""
        out: list[str] = []
        for call in turn.tool_calls:
            out.extend(re.findall(r"scripts/recording_agent\.py\s+([a-z][a-z-]*)", call.command))
        return out

    def check_cli(
        self,
        turn: mila.Turn,
        *,
        must: tuple[str, ...] = (),
        must_not: tuple[str, ...] = (),
    ) -> None:
        ran = self.cli(turn)
        shown = " → ".join(ran) or "—"
        if must:
            self.check(
                f"Мила вызвала {', '.join(must)}",
                " + ".join(must),
                shown,
                ok=all(m in ran for m in must),
            )
        for name in must_not:
            self.check(f"Мила не вызывала {name}", f"без {name}", shown, ok=name not in ran)
        # I7: only SKILL.md reads, skill CLI calls and polling of a still-running exec.
        stray = [
            c.command[:80]
            for c in turn.tool_calls
            if "recording_agent.py" not in c.command
            and "SKILL.md" not in c.command
            and "references/" not in c.command
            and '"action": "poll"' not in c.command
            and '"action": "log"' not in c.command
        ]
        self.check(
            "Мила не лезет в файлы воркспейса (I7)",
            "только SKILL.md/references и CLI навыка",
            "; ".join(stray) or "ок",
            ok=not stray,
        )

    def check_waiting(self, state: dict[str, Any], item: Interview, reason: str | None) -> None:
        """Recording is parked on a question: nothing stored yet."""
        rec = self.recording(state, item) or {}
        self.check(
            f"{item.candidate}: ждёт ответа рекрутера",
            f"manual_review_required ({reason or 'любой'})",
            f"{rec.get('status')} ({rec.get('manual_review_reason')})",
            ok=rec.get("status") == "manual_review_required"
            and (reason is None or rec.get("manual_review_reason") == reason),
        )
        self.check(f"{item.candidate}: файл ещё не загружен", None, rec.get("synology_file_path"))

    def defect(self, severity: str, description: str) -> None:
        self.defects.append(
            Defect(f"{self.route_id}-D{len(self.defects) + 1}", severity, description)
        )

    # ------------------------------------------------------------ teardown

    def teardown(self) -> None:
        for name in list(self._stopped):
            self.container("start", name)
        for name, value in self._env_restore.items():
            remote.bash(_SET_ENV.format(name=name, value=value), timeout=300)
            self.stand_notes.append(f"`{name}` возвращён в `{value or '—'}`")
        self._env_restore.clear()
        urls = [
            e["url"]
            for i in self.interviews
            for e in ([i.event] if i.event else []) + i.extra_events
        ]
        if urls:
            try:
                res = remote.stand("calendar_delete", {"urls": urls})
                ok = all(r["status"] in (200, 204, 404) for r in res)
                self.cleanup_rows.insert(
                    0, ("События календаря", f"{len(urls)} шт.", "удалены" if ok else "ошибка")
                )
            except Exception as exc:  # noqa: BLE001
                self.cleanup_rows.insert(0, ("События календаря", str(exc)[:80], "ошибка"))
        names = [i.disk_name for i in self.interviews]
        if names:
            remote.stand(
                "settle", {"disk_names": names, "reason": f"e2e {self.run_id} {self.route_id}"}
            )
            parked = remote.stand("disk_park", {"disk_names": names}).get("parked", [])
            if parked:
                self.cleanup_rows.append(
                    (
                        "Файлы на Диске (маршрут прерван до скана)",
                        ", ".join(parked)[:200],
                        "перенесены в disk:/E2E/aborted",
                    )
                )

    # ------------------------------------------------------------ report

    def recruiter_messages(self) -> int:
        return len(self.turns)

    def verdict(self) -> str:
        if self.error or any(not c.ok for c in self.checks):
            return "❌ провален"
        if any(r.verdict and not r.verdict.passed for r in self.turns):
            return "❌ провален"
        if self.defects:
            return "⚠️ пройден с дефектами"
        return "✅ пройден"

    def write_report(self) -> Path:
        self.finished = self.finished or datetime.now(UTC)
        image = _backend_image()
        skill = _skill_hash()
        min_turn = min(
            (r.verdict for r in self.turns if r.verdict), key=lambda v: v.total, default=None
        )
        mandatory = (
            "—"
            if min_turn is None
            else (
                "ok"
                if all(
                    all(r.verdict.scores.get(c) == 2 for c in judge_mod.MANDATORY)
                    for r in self.turns
                    if r.verdict
                )
                else "fail"
            )
        )
        lines = [
            f"# {self.route_id} — {self.title}",
            "",
            "## 1. Итог",
            "",
            "| Поле | Значение |",
            "|---|---|",
            f"| Вердикт | {self.verdict()} |",
            f"| Прогон | `{self.run_id}`, попытка {self.attempt} |",
            f"| Дата и время (Asia/Omsk) | `{self.started.astimezone(OMSK):%Y-%m-%d %H:%M}–"
            f"{self.finished.astimezone(OMSK):%H:%M}` |",
            f"| Коммит / образ backend | `{_git_sha()}` / `{image}` |",
            f"| Версия навыка | `{skill}` |",
            f"| Пункты каталога | `{self.catalog}` |",
            f"| Сообщений рекрутера | факт **{self.recruiter_messages()}** / цель "
            f"**{self.target_messages}** |",
            f"| Оценка судьи (мин. по ходам) | "
            f"{'—' if min_turn is None else f'`{min_turn.total}/12`'}, критерии 1–3: `{mandatory}` |",
            "",
        ]
        if self.error:
            lines += [f"> Маршрут остановлен: {self.error}", ""]
        lines += ["## 2. Подготовка данных", "", "| Объект | Значение |", "|---|---|"]
        lines += [f"| {k} | {v} |" for k, v in self.seed_rows] or ["| — | — |"]
        for note in self.stand_notes:
            lines.append(f"| Настройки стенда | {note} |")
        lines += [
            "",
            "## 3. Ход маршрута",
            "",
            "| # | Рекрутер | Ответ Милы (кратко) | Команды навыка | Судья | Проверки |",
            "|---|---|---|---|---|---|",
        ]
        for n, rec in enumerate(self.turns, 1):
            cmds = ", ".join(f"`{_cmd_name(c.command)}`" for c in rec.turn.tool_calls) or "—"
            score = f"{rec.verdict.total}/12" if rec.verdict else "—"
            checks = " ".join(("✅ " if c.ok else "❌ ") + c.name for c in rec.checks) or "—"
            lines.append(
                f"| {n} | «{_cell(rec.turn.user, 120)}» | {_cell(rec.turn.reply, 220)} | {cmds} | "
                f"{score} | {_cell(checks, 400)} |"
            )
        if not self.turns:
            lines.append("| — | — | — | — | — | — |")
        lines += [
            "",
            f"Полный текст ответов Милы — в `artifacts/{self.route_id}/transcript.md`.",
            "",
            "## 4. Детерминированные проверки",
            "",
            "| Проверка | Ожидание | Факт | Итог |",
            "|---|---|---|---|",
        ]
        lines += [
            f"| {_cell(c.name, 120)} | {_cell(c.expected, 160)} | {_cell(c.actual, 160)} | "
            f"{'✅' if c.ok else '❌'} |"
            for c in self.checks
        ] or ["| — | — | — | — |"]
        lines += [
            "",
            "## 5. Оценка судьи",
            "",
            "| Ход | 1 Действие | 2 Факты | 3 Безопасность | 4 Уточнение | 5 Понятность | "
            "6 Проактивность | Сумма |",
            "|---|---|---|---|---|---|---|---|",
        ]
        reasons: list[str] = []
        served = ""
        for n, rec in enumerate(self.turns, 1):
            v = rec.verdict
            if v is None:
                lines.append(f"| {n} | — | — | — | — | — | — | не оценивался |")
                continue
            served = v.served_by or served
            if v.error:
                lines.append(f"| {n} | ошибка судьи: {_cell(v.error, 120)} ||||||| 0 |")
                continue
            s = v.scores
            lines.append(
                f"| {n} | {s['action']} | {s['facts']} | {s['safety']} | {s['clarification']} | "
                f"{s['clarity']} | {s['proactivity']} | {v.total} |"
            )
            reasons += [f"Ход {n}, {k}: {_cell(r, 300)}" for k, r in v.reasons.items() if r]
        lines += [
            "",
            f"Судья: `{served or judge_mod.MODEL}`. Обоснования судьи "
            "(по одной строке на сниженный балл):",
            "",
        ]
        lines += [f"- {r}" for r in reasons] or ["- —"]
        lines += [
            "",
            "## 6. Дефекты",
            "",
            "| ID | Класс | Описание | Статус | Коммит |",
            "|---|---|---|---|---|",
        ]
        lines += [
            f"| {d.id} | {d.severity} | {_cell(d.description, 400)} | {d.status} | {d.commit} |"
            for d in self.defects
        ] or ["| — | — | — | — | — |"]
        lines += ["", "## 7. Уборка", "", "| Объект | Действие | Итог |", "|---|---|---|"]
        for kind, ref, action in self.cleanup_rows:
            done = action in ("удалены", "ошибка")
            lines.append(
                f"| {kind}: {_cell(ref, 160)} | {action} | "
                f"{'✅' if action == 'удалены' else ('❌' if action == 'ошибка' else '⏳ ждёт подтверждения')} |"
                if not done
                else f"| {kind}: {_cell(ref, 160)} | {action} | {'✅' if action == 'удалены' else '❌'} |"
            )
        lines += ["", "## 8. Выводы", ""]
        lines += [f"- {c}" for c in self.conclusions] or ["- —"]
        path = self.dir / f"{self.route_id}.md"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        self._write_transcript()
        self._write_cleanup_manifest()
        return path

    def _write_transcript(self) -> None:
        out = [f"# {self.route_id} — стенограмма", ""]
        for n, rec in enumerate(self.turns, 1):
            out += [f"## Ход {n} ({rec.turn.duration_s:.0f} с)", "", "**Рекрутер:**", ""]
            out += ["> " + line for line in rec.turn.user.splitlines()] + [""]
            out += ["**Команды:**", ""]
            for c in rec.turn.tool_calls:
                out += ["```text", c.command[:1500], "```", ""]
                if c.result:
                    out += [
                        "<details><summary>ответ</summary>",
                        "",
                        "```text",
                        c.result[:3000],
                        "```",
                        "",
                        "</details>",
                        "",
                    ]
            out += ["**Мила:**", ""] + ["> " + line for line in rec.turn.reply.splitlines()] + [""]
            if rec.verdict:
                out += [f"**Судья:** {rec.verdict.total}/12 — {rec.verdict.summary}", ""]
        (self.dir / "artifacts" / self.route_id / "transcript.md").write_text(
            "\n".join(out) + "\n", encoding="utf-8"
        )

    def _write_cleanup_manifest(self) -> None:
        path = self.dir / "cleanup.json"
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        data[self.route_id] = [
            {"kind": k, "ref": r, "action": a}
            for k, r, a in self.cleanup_rows
            if a not in ("удалены", "ошибка")
        ]
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


_SET_ENV = r"""
set -e
F=/etc/recording-agent/backend.env
[ -f /root/backend.env.e2e-backup ] || cp -a $F /root/backend.env.e2e-backup
V='{value}'
if [ -z "$V" ]; then sed -i '/^{name}=/d' $F
elif grep -q '^{name}=' $F; then sed -i "s|^{name}=.*|{name}=$V|" $F; else echo "{name}=$V" >> $F; fi
IMG=$(docker inspect -f '{{{{.Config.Image}}}}' recording-agent-backend-1)
cd /opt/recording-agent/hotfix-abe9942
RECORDING_AGENT_IMAGE=$IMG docker compose -p recording-agent -f compose.prod.yml --env-file $F up -d --no-deps --force-recreate backend >/dev/null 2>&1
for i in $(seq 1 40); do s=$(docker inspect -f '{{{{.State.Health.Status}}}}' recording-agent-backend-1 || true); [ "$s" = healthy ] && break; sleep 3; done
echo health=$s
"""


def run_route(ctx: RouteCtx, body: Callable[[RouteCtx], None]) -> Path:
    try:
        body(ctx)
    except RouteBlocker as exc:
        ctx.error = str(exc)
    except Exception as exc:  # noqa: BLE001
        ctx.error = f"{type(exc).__name__}: {exc}"
        (ctx.dir / "artifacts" / ctx.route_id / "error.txt").write_text(
            traceback.format_exc(), encoding="utf-8"
        )
    finally:
        try:
            ctx.teardown()
        except Exception as exc:  # noqa: BLE001
            ctx.conclusions.append(f"Ошибка уборки: {exc}")
        ctx.finished = datetime.now(UTC)
    return ctx.write_report()


# ---------------------------------------------------------------- helpers


def _cell(value: str, limit: int) -> str:
    text = " ".join(str(value).split())
    text = text.replace("|", "\\|")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _cmd_name(command: str) -> str:
    parts = command.split()
    if "scripts/recording_agent.py" in parts:
        i = parts.index("scripts/recording_agent.py")
        return parts[i + 1] if i + 1 < len(parts) else "?"
    if command.startswith("{"):
        return "read"
    return parts[0] if parts else "?"


_CACHE: dict[str, str] = {}


def _git_sha() -> str:
    if "git" not in _CACHE:
        _CACHE["git"] = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=False
        ).stdout.strip()
    return _CACHE["git"]


def _backend_image() -> str:
    if "image" not in _CACHE:
        out = remote.bash(
            f"docker inspect --format '{{{{.Image}}}}' {remote.BACKEND_CONTAINER}", check=False
        )
        _CACHE["image"] = out.strip().replace("sha256:", "")[:12]
    return f"sha256:{_CACHE['image']}"


def _skill_hash() -> str:
    if "skill" not in _CACHE:
        out = remote.bash(
            "sha256sum /srv/openclaw/workspaces/recordings-saver/skills/recording-agent/SKILL.md",
            check=False,
        )
        _CACHE["skill"] = out.split()[0][:12] if out else "?"
    return _CACHE["skill"]
