# ruff: noqa: E501
"""E2E stand helper. Runs INSIDE the prod backend container (prod settings, prod DB).

Invoked by tests/e2e/lib/remote.py: the request JSON arrives on stdin after the source.
Prints `@@E2E@@<json>` as the last line. Never prints credentials.

Destructive commands (Synology delete, Notion archive) require payload["confirm"] is True;
the runner sets it only after the user approved the cleanup list.
"""

from __future__ import annotations

import asyncio
import base64
import json
import sys
import traceback
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import text

from app.config import get_settings
from app.db.engine import create_engine, create_session_factory
from app.services.yandex_token_manager import YandexTokenManager
from app.tools.disk import DISK_API_BASE, TELEMOST_ROOT
from app.tools.notion import NOTION_API_BASE, NOTION_API_VERSION, build_notion_http_client
from app.tools.synology import SynologyBackend

TEMPLATE_PATH = "disk:/E2E/template.webm"
TEMPLATE_DIR = "disk:/E2E"


# ---------------------------------------------------------------- context


class Ctx:
    def __init__(self) -> None:
        self.s = get_settings()
        self.engine = create_engine(self.s)
        self.sf = create_session_factory(self.engine)
        self.http = httpx.AsyncClient(timeout=120, trust_env=False)
        self._recruiter: dict[str, Any] | None = None
        self._disk_token: str | None = None
        self._syno: SynologyBackend | None = None
        self._notion: httpx.AsyncClient | None = None

    async def close(self) -> None:
        await self.http.aclose()
        if self._notion is not None:
            await self._notion.aclose()
        await self.engine.dispose()

    async def sql(self, query: str, **params: Any) -> list[dict[str, Any]]:
        async with self.sf() as session:
            result = await session.execute(text(query), params)
            if result.returns_rows:
                return [dict(row._mapping) for row in result]
            await session.commit()
            return []

    async def recruiter(self) -> dict[str, Any]:
        if self._recruiter is None:
            rows = await self.sql("select * from recruiter_config where active order by created_at")
            if not rows:
                raise RuntimeError("no active recruiter")
            self._recruiter = rows[0]
        return self._recruiter

    async def disk_headers(self) -> dict[str, str]:
        if self._disk_token is None:
            email = (await self.recruiter())["email"]
            tokens = YandexTokenManager(self.sf, self.s, self.http)
            self._disk_token = await tokens.get_access_token(email)
        return {"Authorization": f"OAuth {self._disk_token}"}

    def caldav_auth(self, email: str) -> tuple[str, str]:
        secret = self.s.yandex_caldav_passwords[email]
        value = secret.get_secret_value() if hasattr(secret, "get_secret_value") else secret
        return email, value

    def syno(self) -> SynologyBackend:
        if self._syno is None:
            s = self.s
            self._syno = SynologyBackend(
                s.synology_base_url,
                s.synology_api_key,
                self.http,
                username=s.synology_user,
                password=s.synology_pass,
                device_id=s.synology_device_id,
            )
        return self._syno

    def notion(self) -> httpx.AsyncClient:
        if self._notion is None:
            self._notion = build_notion_http_client(self.s, 60)
            self._notion.headers.update(
                {
                    "Authorization": f"Bearer {self.s.notion_token.get_secret_value()}",
                    "Notion-Version": NOTION_API_VERSION,
                }
            )
        return self._notion


def jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [jsonable(v) for v in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


def prop_text(prop: dict[str, Any] | None) -> Any:
    if not prop:
        return None
    kind = prop.get("type")
    value = prop.get(kind)
    if kind in ("title", "rich_text"):
        return "".join(x.get("plain_text", "") for x in value)
    if kind == "date":
        return value and value.get("start")
    if kind == "url":
        return value
    if kind == "relation":
        return [r["id"] for r in value]
    if kind in ("select", "status"):
        return value and value.get("name")
    if kind == "email":
        return value
    if kind == "files":
        # The recording link is stored as an external file: {"name": ..., "external": {"url": ...}}.
        urls = [(f.get("external") or f.get("file") or {}).get("url") for f in value]
        return urls[0] if len(urls) == 1 else (urls or None)
    return f"<{kind}>"


# ---------------------------------------------------------------- notion


async def notion_data_source(ctx: Ctx) -> str:
    db = (await ctx.recruiter())["notion_database_id"]
    response = await ctx.notion().get(f"{NOTION_API_BASE}/databases/{db}")
    response.raise_for_status()
    return response.json()["data_sources"][0]["id"]


async def notion_title(ctx: Ctx, page_id: str, cache: dict[str, str]) -> str:
    if page_id not in cache:
        page = (await ctx.notion().get(f"{NOTION_API_BASE}/pages/{page_id}")).json()
        title = next(
            (v for v in page.get("properties", {}).values() if v.get("type") == "title"), None
        )
        cache[page_id] = prop_text(title) or ""
    return cache[page_id]


async def notion_card(ctx: Ctx, page: dict[str, Any], cache: dict[str, str]) -> dict[str, Any]:
    s = ctx.s
    props = page["properties"]
    spot_ids = prop_text(props.get(s.notion_project_prop)) or []
    return {
        "id": page["id"],
        "url": page.get("url"),
        "archived": page.get("archived") or page.get("in_trash"),
        "name": prop_text(props.get(s.notion_name_prop)),
        "date": prop_text(props.get(s.notion_date_prop)),
        "recording": prop_text(props.get(s.notion_recording_prop)),
        "contacts": prop_text(props.get(s.notion_contacts_prop)),
        "spots": [{"id": sid, "title": await notion_title(ctx, sid, cache)} for sid in spot_ids],
        "created": page.get("created_time"),
    }


async def cmd_notion_cards(ctx: Ctx, p: dict[str, Any]) -> Any:
    ds = await notion_data_source(ctx)
    body: dict[str, Any] = {
        "page_size": int(p.get("limit", 50)),
        "sorts": [{"timestamp": "created_time", "direction": "descending"}],
    }
    if p.get("name"):
        body["filter"] = {"property": ctx.s.notion_name_prop, "title": {"equals": p["name"]}}
    response = await ctx.notion().post(f"{NOTION_API_BASE}/data_sources/{ds}/query", json=body)
    response.raise_for_status()
    cache: dict[str, str] = {}
    return [await notion_card(ctx, page, cache) for page in response.json().get("results", [])]


async def cmd_notion_card_get(ctx: Ctx, p: dict[str, Any]) -> Any:
    page = (await ctx.notion().get(f"{NOTION_API_BASE}/pages/{p['id']}")).json()
    return await notion_card(ctx, page, {})


async def cmd_notion_card_create(ctx: Ctx, p: dict[str, Any]) -> Any:
    """Create a test candidate card. Only in the recruiter's configured DB."""
    s = ctx.s
    ds = await notion_data_source(ctx)
    props: dict[str, Any] = {
        s.notion_name_prop: {"title": [{"text": {"content": p["name"]}}]},
    }
    if p.get("spot_ids"):
        props[s.notion_project_prop] = {"relation": [{"id": sid} for sid in p["spot_ids"]]}
    if p.get("date"):
        props[s.notion_date_prop] = {"date": {"start": p["date"]}}
    body = {"parent": {"type": "data_source_id", "data_source_id": ds}, "properties": props}
    response = await ctx.notion().post(f"{NOTION_API_BASE}/pages", json=body)
    if response.status_code >= 400:
        raise RuntimeError(f"notion create {response.status_code}: {response.text[:300]}")
    return await notion_card(ctx, response.json(), {})


async def cmd_notion_card_update(ctx: Ctx, p: dict[str, Any]) -> Any:
    """Set test-card fields (e.g. clear recording link). Requires confirm."""
    if p.get("confirm") is not True:
        raise RuntimeError("notion_card_update requires confirm")
    s = ctx.s
    props: dict[str, Any] = {}
    if "recording" in p:
        props[s.notion_recording_prop] = {"url": p["recording"]}
    if "date" in p:
        props[s.notion_date_prop] = {"date": {"start": p["date"]} if p["date"] else None}
    if "name" in p:
        props[s.notion_name_prop] = {"title": [{"text": {"content": p["name"]}}]}
    if "spot_ids" in p:
        props[s.notion_project_prop] = {"relation": [{"id": sid} for sid in p["spot_ids"]]}
    response = await ctx.notion().patch(
        f"{NOTION_API_BASE}/pages/{p['id']}", json={"properties": props}
    )
    if response.status_code >= 400:
        raise RuntimeError(f"notion update {response.status_code}: {response.text[:300]}")
    return await notion_card(ctx, response.json(), {})


async def cmd_notion_card_archive(ctx: Ctx, p: dict[str, Any]) -> Any:
    if p.get("confirm") is not True:
        raise RuntimeError("notion_card_archive requires confirm")
    response = await ctx.notion().patch(
        f"{NOTION_API_BASE}/pages/{p['id']}", json={"in_trash": True}
    )
    return {"id": p["id"], "status": response.status_code}


async def cmd_notion_spots(ctx: Ctx, p: dict[str, Any]) -> Any:
    """Spot pages referenced by recent cards (id -> title)."""
    cards = await cmd_notion_cards(ctx, {"limit": 100})
    spots: dict[str, str] = {}
    for card in cards:
        for spot in card["spots"]:
            spots[spot["id"]] = spot["title"]
    return spots


# ---------------------------------------------------------------- inventory


async def cmd_inventory(ctx: Ctx, p: dict[str, Any]) -> Any:
    recruiter = await ctx.recruiter()
    calendars = await ctx.sql(
        "select canonical_url, display_name, is_default, selected, available "
        "from recruiter_calendar where recruiter_id = :rid order by display_name",
        rid=recruiter["id"],
    )
    folders = []
    for root in ctx.s.synology_interview_roots:
        found = await ctx.syno().discover_folders(
            root, max_depth=int(p.get("depth", 2)), max_pages=5, max_results=200
        )
        folders.extend(
            {"root": root, "path": f.path, "writable": f.writable, "symlink": f.symlink}
            for f in found
        )
    return {
        "recruiter": {
            k: recruiter[k]
            for k in ("email", "timezone", "synology_base_folder", "notion_database_id")
        },
        "flags": {
            "storage_provider": ctx.s.storage_provider,
            "scheduler": ctx.s.scheduler_enabled,
            "notion_writes": ctx.s.notion_writes_enabled,
            "mattermost_delivery": ctx.s.mattermost_delivery_enabled,
            "source_mutation": ctx.s.yandex_source_mutation_enabled,
            "autonomous_routing": getattr(ctx.s, "autonomous_routing_enabled", None),
            "scan_local_timezone": ctx.s.scan_local_timezone,
        },
        "calendars": calendars,
        "roots": list(ctx.s.synology_interview_roots),
        "folders": folders,
        "cards": await cmd_notion_cards(ctx, {"limit": int(p.get("cards", 40))}),
    }


# ---------------------------------------------------------------- disk


async def disk_meta(ctx: Ctx, path: str) -> dict[str, Any] | None:
    response = await ctx.http.get(
        f"{DISK_API_BASE}/resources", headers=await ctx.disk_headers(), params={"path": path}
    )
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json()


async def disk_wait(ctx: Ctx, href: str) -> None:
    for _ in range(60):
        status = (await ctx.http.get(href, headers=await ctx.disk_headers())).json()
        if status.get("status") in ("success", "failed"):
            if status["status"] == "failed":
                raise RuntimeError("disk operation failed")
            return
        await asyncio.sleep(1)
    raise RuntimeError("disk operation timeout")


async def cmd_put_template(ctx: Ctx, p: dict[str, Any]) -> Any:
    if await disk_meta(ctx, TEMPLATE_PATH):
        return {"template": TEMPLATE_PATH, "created": False}
    h = await ctx.disk_headers()
    await ctx.http.put(f"{DISK_API_BASE}/resources", headers=h, params={"path": TEMPLATE_DIR})
    r = await ctx.http.get(
        f"{DISK_API_BASE}/resources/upload",
        headers=h,
        params={"path": TEMPLATE_PATH, "overwrite": "false"},
    )
    r.raise_for_status()
    up = await ctx.http.put(r.json()["href"], content=base64.b64decode(p["b64"]))
    return {"template": TEMPLATE_PATH, "created": True, "status": up.status_code}


async def disk_copy_template(ctx: Ctx, name: str, folder: str = TELEMOST_ROOT) -> dict[str, Any]:
    path = folder + name
    h = await ctx.disk_headers()
    r = await ctx.http.post(
        f"{DISK_API_BASE}/resources/copy",
        headers=h,
        params={"from": TEMPLATE_PATH, "path": path, "overwrite": "false"},
    )
    if r.status_code == 202:
        await disk_wait(ctx, r.json()["href"])
    elif r.status_code != 201:
        raise RuntimeError(f"disk copy {r.status_code}: {r.text[:200]}")
    for _ in range(20):
        meta = await disk_meta(ctx, path)
        if meta and meta.get("media_type") == "video":
            break
        await asyncio.sleep(2)
    return {
        "path": path,
        "resource_id": meta and meta.get("resource_id"),
        "media_type": meta and meta.get("media_type"),
        "created": meta and meta.get("created"),
    }


async def cmd_disk_list(ctx: Ctx, p: dict[str, Any]) -> Any:
    meta = await ctx.http.get(
        f"{DISK_API_BASE}/resources",
        headers=await ctx.disk_headers(),
        params={"path": p.get("path", TELEMOST_ROOT), "limit": 200},
    )
    meta.raise_for_status()
    items = meta.json().get("_embedded", {}).get("items", [])
    return [
        {
            "name": i["name"],
            "created": i.get("created"),
            "media_type": i.get("media_type"),
            "resource_id": i.get("resource_id"),
            "processed": (i.get("custom_properties") or {}).get("processed"),
        }
        for i in items
    ]


async def cmd_disk_trash(ctx: Ctx, p: dict[str, Any]) -> Any:
    """Move runner-created Disk files to trash (recoverable). Paths must be e2e-seeded."""
    results = []
    for path in p["paths"]:
        r = await ctx.http.delete(
            f"{DISK_API_BASE}/resources",
            headers=await ctx.disk_headers(),
            params={"path": path, "permanently": "false"},
        )
        if r.status_code == 202:
            await disk_wait(ctx, r.json()["href"])
        results.append({"path": path, "status": r.status_code})
    return results


# ---------------------------------------------------------------- calendar


def ics(uid: str, summary: str, description: str, start: datetime, end: datetime) -> str:
    fmt = "%Y%m%dT%H%M%SZ"
    stamp = datetime.now(UTC).strftime(fmt)

    def esc(value: str) -> str:
        return (
            value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")
        )

    return "\r\n".join(
        [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//recording-agent-e2e//EN",
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{stamp}",
            f"DTSTART:{start.strftime(fmt)}",
            f"DTEND:{end.strftime(fmt)}",
            f"SUMMARY:{esc(summary)}",
            f"DESCRIPTION:{esc(description)}",
            "END:VEVENT",
            "END:VCALENDAR",
            "",
        ]
    )


async def calendar_url(ctx: Ctx, which: str) -> str:
    recruiter = await ctx.recruiter()
    rows = await ctx.sql(
        "select canonical_url, display_name, is_default, selected from recruiter_calendar "
        "where recruiter_id = :rid",
        rid=recruiter["id"],
    )
    if which.startswith("https://"):
        return which
    for row in rows:
        if which == "selected" and row["selected"] and not row["is_default"]:
            return row["canonical_url"]
        if which == "default" and row["is_default"]:
            return row["canonical_url"]
        if which == row["display_name"]:
            return row["canonical_url"]
    raise RuntimeError(f"calendar {which!r} not found")


async def cmd_seed(ctx: Ctx, p: dict[str, Any]) -> Any:
    """Create calendar events and Telemost files. Returns identifiers for cleanup."""
    recruiter = await ctx.recruiter()
    email = recruiter["email"]
    out: dict[str, Any] = {"events": [], "files": []}
    for ev in p.get("events", []):
        start = datetime.fromisoformat(ev["start_utc"])
        end = start + timedelta(minutes=int(ev.get("minutes", 30)))
        uid = f"e2e-{p.get('run', 'x')}-{uuid.uuid4().hex[:12]}"
        base = await calendar_url(ctx, ev.get("calendar", "selected"))
        url = base.rstrip("/") + f"/{uid}.ics"
        r = await ctx.http.put(
            url,
            content=ics(uid, ev["summary"], ev.get("description", ""), start, end).encode(),
            headers={"Content-Type": "text/calendar; charset=utf-8", "If-None-Match": "*"},
            auth=ctx.caldav_auth(email),
        )
        if r.status_code not in (201, 204):
            raise RuntimeError(f"caldav PUT {r.status_code}")
        out["events"].append({"uid": uid, "url": url, "summary": ev["summary"]})
    for f in p.get("files", []):
        out["files"].append(
            await disk_copy_template(ctx, f["name"], f.get("folder", TELEMOST_ROOT))
        )
    return out


async def cmd_calendar_delete(ctx: Ctx, p: dict[str, Any]) -> Any:
    email = (await ctx.recruiter())["email"]
    results = []
    for url in p["urls"]:
        if "/e2e-" not in url:
            raise RuntimeError("refusing to delete a non-e2e event")
        r = await ctx.http.delete(url, auth=ctx.caldav_auth(email))
        results.append({"url": url, "status": r.status_code})
    return results


# ---------------------------------------------------------------- synology


async def syno_exists(ctx: Ctx, path: str) -> bool | str:
    """True/False, or the DSM error text after one retry with a fresh session."""
    from app.tools.synology import SynologyAPIError

    for attempt in range(2):
        try:
            return await ctx.syno()._file_size(path) is not None  # noqa: SLF001
        except SynologyAPIError as error:
            if attempt:
                return f"DSM error: {getattr(error, 'payload', error)}"[:200]
            ctx._syno = None  # noqa: SLF001 - re-login on the second attempt
    return False


async def cmd_syno_exists(ctx: Ctx, p: dict[str, Any]) -> Any:
    return {path: await syno_exists(ctx, path) for path in p["paths"]}


async def cmd_syno_delete(ctx: Ctx, p: dict[str, Any]) -> Any:
    """Delete runner-created files/folders. Requires confirm; paths must be under roots."""
    if p.get("confirm") is not True:
        raise RuntimeError("syno_delete requires confirm")
    roots = tuple(ctx.s.synology_interview_roots)
    for path in p["paths"]:
        if not any(path.startswith(root + "/") for root in roots) or ".." in path:
            raise RuntimeError(f"refusing to delete outside roots: {path}")
    b = ctx.syno()
    r = await b._get(  # noqa: SLF001
        "/webapi/entry.cgi",
        params={
            "api": "SYNO.FileStation.Delete",
            "version": "2",
            "method": "start",
            "path": json.dumps(p["paths"], ensure_ascii=False),
            "recursive": "true",
        },
    )
    task = r.json().get("data", {}).get("taskid")
    status: dict[str, Any] = {}
    for _ in range(30):
        s = await b._get(  # noqa: SLF001
            "/webapi/entry.cgi",
            params={
                "api": "SYNO.FileStation.Delete",
                "version": "2",
                "method": "status",
                "taskid": task,
            },
        )
        status = s.json()
        if status.get("data", {}).get("finished"):
            break
        await asyncio.sleep(1)
    return {"task": bool(task), "finished": status.get("data", {}).get("finished")}


# ---------------------------------------------------------------- observe


REC_FIELDS = (
    "id, disk_filename, disk_path, disk_file_id, status, version, route_type, "
    "manual_review_reason, candidate_name, project_or_spot, notion_page_id, notion_page_url, "
    "synology_folder_path, synology_file_path, synology_share_url, generated_filename, "
    "calendar_event_uid, calendar_event_summary, error_step, error_message, "
    "terminal_notified_at, completed_at, found_at, source_processed, deleted_from_disk_at"
)


async def cmd_observe(ctx: Ctx, p: dict[str, Any]) -> Any:
    names = p.get("disk_names") or []
    recs = await ctx.sql(
        f"select {REC_FIELDS} from recordings where disk_filename = any(:names) order by found_at",
        names=names,
    )
    ids = [r["id"] for r in recs]
    reviews = await ctx.sql(
        "select id, recording_id, status, question_type, question_context, result, "
        "created_at, resolved_at, suppressed_at, automatic_delivery_count, digest_id "
        "from manual_reviews where recording_id = any(:ids) order by created_at",
        ids=ids,
    )
    since = datetime.fromisoformat(p["outbox_since"]) if p.get("outbox_since") else None
    outbox = await ctx.sql(
        "select id, kind, dedupe_key, status, payload, created_at, sent_at, last_error "
        "from notification_outbox where created_at >= coalesce(cast(:since as timestamptz), "
        "now() - interval '1 day') order by created_at",
        since=since,
    )
    related = []
    id_strings = {str(i) for i in ids}
    for item in outbox:
        blob = json.dumps(jsonable(item), ensure_ascii=False)
        if any(i in blob for i in id_strings) or item["kind"] in p.get("outbox_kinds", []):
            related.append(item)
    storage = {}
    for rec in recs:
        path = rec.get("synology_file_path")
        if path:
            folder, _, name = path.rpartition("/")
            storage[path] = {
                "file": await syno_exists(ctx, path),
                "marker": await syno_exists(ctx, f"{folder}/.{name}.recording-agent-owner.json"),
            }
    cards = {}
    for rec in recs:
        if rec.get("notion_page_id") and p.get("notion", True):
            cards[rec["notion_page_id"]] = await cmd_notion_card_get(
                ctx, {"id": rec["notion_page_id"]}
            )
    routing = (
        await ctx.sql(
            "select * from routing_jobs where recording_id = any(:ids) order by created_at", ids=ids
        )
        if p.get("routing")
        else []
    )
    return jsonable(
        {
            "recordings": recs,
            "reviews": reviews,
            "outbox": related,
            "storage": storage,
            "cards": cards,
            "routing_jobs": routing,
        }
    )


async def cmd_sql(ctx: Ctx, p: dict[str, Any]) -> Any:
    """Read-only SQL for checks (SELECT only)."""
    query = p["query"].strip()
    if not query.lower().startswith(("select", "with")):
        raise RuntimeError("read-only")
    return jsonable(await ctx.sql(query, **p.get("params", {})))


async def cmd_db_forget(ctx: Ctx, p: dict[str, Any]) -> Any:
    """Delete DB rows of runner-created recordings (by exact e2e disk filenames)."""
    names = p["disk_names"]
    rows = await ctx.sql("select id from recordings where disk_filename = any(:names)", names=names)
    ids = [r["id"] for r in rows]
    if not ids:
        return {"deleted": 0}
    for table in ("notification_outbox",):
        await ctx.sql(
            f"delete from {table} where "  # noqa: S608
            "exists (select 1 from unnest(cast(:ids as text[])) i where dedupe_key like '%' || i || '%')",
            ids=[str(i) for i in ids],
        )
    await ctx.sql("delete from recordings where id = any(:ids)", ids=ids)
    return {"deleted": len(ids)}


async def cmd_settle(ctx: Ctx, p: dict[str, Any]) -> Any:
    """Close leftovers of runner-created recordings so they do not leak into later routes.

    Non-terminal recordings -> ignored; their pending questions -> suppressed. Test data only
    (exact e2e disk filenames). Completed/failed rows are left as they are.
    """
    names = p["disk_names"]
    rows = await ctx.sql(
        "select id from recordings where disk_filename = any(:names) "
        "and status not in ('completed', 'ignored', 'failed')",
        names=names,
    )
    ids = [r["id"] for r in rows]
    await ctx.sql(
        "update manual_reviews set status = 'suppressed', suppressed_at = now(), "
        "result = cast(:result as jsonb) where status in ('pending', 'answered') and "
        "recording_id in (select id from recordings where disk_filename = any(:names))",
        names=names,
        result=json.dumps({"closed_by": "e2e_settle", "reason": p.get("reason", "")}),
    )
    if ids:
        await ctx.sql(
            "update recordings set status = 'ignored', version = version + 1, "
            "processing_lease_token = null, processing_lease_expires_at = null, "
            "terminal_notified_at = coalesce(terminal_notified_at, now()) where id = any(:ids)",
            ids=ids,
        )
    return {"ignored": len(ids)}


async def cmd_backfill_durable(ctx: Ctx, p: dict[str, Any]) -> Any:
    """One-off repair for recordings stored before adec628: durable flag + active artifact.

    Mirrors cron._ensure_active_storage_artifact. Requires confirm.
    """
    if p.get("confirm") is not True:
        raise RuntimeError("backfill_durable requires confirm")
    from app.db.models.recording import Recording
    from app.scheduler.cron import _ensure_active_storage_artifact

    async with ctx.sf() as session:
        from sqlalchemy import select

        rows = (
            await session.scalars(
                select(Recording).where(
                    Recording.status == "completed",
                    Recording.synology_share_url.is_not(None),
                    Recording.storage_is_durable.is_(False),
                )
            )
        ).all()
        for recording in rows:
            recording.storage_is_durable = True
            await _ensure_active_storage_artifact(session, recording)
        await session.commit()
        return {"repaired": [r.disk_filename for r in rows]}


COMMANDS = {
    "backfill_durable": cmd_backfill_durable,
    "settle": cmd_settle,
    "inventory": cmd_inventory,
    "notion_cards": cmd_notion_cards,
    "notion_card_get": cmd_notion_card_get,
    "notion_card_create": cmd_notion_card_create,
    "notion_card_update": cmd_notion_card_update,
    "notion_card_archive": cmd_notion_card_archive,
    "notion_spots": cmd_notion_spots,
    "put_template": cmd_put_template,
    "disk_list": cmd_disk_list,
    "disk_trash": cmd_disk_trash,
    "seed": cmd_seed,
    "calendar_delete": cmd_calendar_delete,
    "syno_exists": cmd_syno_exists,
    "syno_delete": cmd_syno_delete,
    "observe": cmd_observe,
    "sql": cmd_sql,
    "db_forget": cmd_db_forget,
}


async def main() -> None:
    request = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    ctx = Ctx()
    try:
        result = await COMMANDS[request["command"]](ctx, request.get("payload") or {})
        out: Any = jsonable(result)
    except Exception as exc:  # noqa: BLE001
        out = {
            "error": f"{type(exc).__name__}: {str(exc)[:500]}",
            "trace": traceback.format_exc()[-1500:],
        }
    finally:
        await ctx.close()
    sys.stdout.write("\n@@E2E@@" + json.dumps(out, ensure_ascii=False, default=str) + "\n")


asyncio.run(main())
