# ruff: noqa: E501
"""Read-only inspection of production data sources for one recruiter.

    python -u -X utf8 -m tests.e2e.inspect_prod <command> [options]

Commands (all read-only; nothing is written to any service, secrets are never printed):

    notion-search                         databases the Notion connection can see
    notion-db <database id or URL>        fields, relations, last edit of one database
    disk --email E [--folder F] [--limit N] [--token-file PATH]
                                          files in a Yandex Disk folder
    calendar --email E [--env .env.X] [--days-back N] [--days-ahead N] [--full]
                                          CalDAV calendars and events (title, start, links)
    synology <path> [<path> ...]          whether Synology paths exist
    mattermost --email E                  Mattermost user id and the DM channel with the bot
    mail --email E [--env .env.X]         IMAP login check (imap.yandex.ru) + INBOX message count

Credentials:
- Notion: NOTION_TOKEN_PROD (or NOTION_TOKEN) from the local `.env`; calls go straight to Notion.
- Yandex Disk: by default the backend's own token manager for an onboarded recruiter; before
  onboarding pass `--token-file /root/<name>-yandex-refresh-token` (server path). Yandex rotates
  refresh tokens on every refresh; the file is rewritten on the server when that happens.
- CalDAV: the backend's YANDEX_CALDAV_PASSWORDS for an onboarded recruiter, or
  `--env .env.<name>` (local file with <PREFIX>_CALDAV_APP_PASSWORD) before onboarding.
- Synology and Mattermost: the backend container's settings.
- Mail: not wired into the backend yet (meeting-summary feature, not built). Reads the app
  password straight from the local `.env` (`YANDEX_MAIL_APP_PASSWORDS` JSON map, keyed by email)
  or from `--env .env.<name>` (`<PREFIX>_MAIL_APP_PASSWORD`). Never printed.

Output can contain real candidate names and meeting titles: keep it in the session, never commit
it or paste it into shared chats.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import httpx

from tests.e2e.lib import remote

ROOT = Path(__file__).resolve().parents[2]
NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2026-03-11"


# ---------------------------------------------------------------------------- helpers


def _local_env(path: Path, pattern: str) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(rf"^({pattern})=(.*)$", line.strip())
        if match:
            values[match.group(1)] = match.group(2).strip().strip('"').strip("'")
    return values


def _notion() -> httpx.Client:
    env = _local_env(ROOT / ".env", "NOTION_TOKEN_PROD|NOTION_TOKEN")
    token = env.get("NOTION_TOKEN_PROD") or env.get("NOTION_TOKEN")
    if not token:
        raise SystemExit("NOTION_TOKEN_PROD / NOTION_TOKEN not found in the local .env")
    return httpx.Client(
        headers={"Authorization": f"Bearer {token}", "Notion-Version": NOTION_VERSION},
        timeout=30,
    )


def _notion_id(value: str) -> str:
    """Database id from a raw id or a Notion URL (the last id of the path, not the `?v=` view)."""
    path = value.lower().split("?")[0].replace("-", "")
    ids = re.findall(r"[0-9a-f]{32}", path)
    if not ids:
        raise SystemExit(f"no Notion id in {value!r}")
    raw = ids[-1]
    return f"{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:]}"


NL = "\n"


def _wrap(code: str, params: dict[str, Any]) -> str:
    """Python source: `P` holds the parameters; any error is printed instead of lost on stderr."""
    return (
        "import json, traceback\n"
        f"P = json.loads({json.dumps(json.dumps(params, ensure_ascii=False))})\n"
        "try:\n"
        + "\n".join("    " + line for line in code.strip("\n").splitlines())
        + "\nexcept Exception as error:\n"
        "    print('ERROR', type(error).__name__, str(error)[:400])\n"
    )


def _in_backend(code: str, params: dict[str, Any], timeout: int = 180) -> str:
    """Run Python inside the backend container (app settings and secrets stay on the server)."""
    wrapped = _wrap(code, params)
    script = (
        f"docker exec -i {remote.BACKEND_CONTAINER} python - 2>&1 <<'PYEOF'\n{wrapped}\nPYEOF\n"
    )
    return remote.bash(script, timeout=timeout, check=False)


# ---------------------------------------------------------------------------- Notion


def notion_search() -> None:
    client = _notion()
    cursor: str | None = None
    rows: list[tuple[str, str]] = []
    while True:
        body: dict[str, Any] = {
            "filter": {"property": "object", "value": "data_source"},
            "page_size": 100,
        }
        if cursor:
            body["start_cursor"] = cursor
        data = client.post(f"{NOTION_API}/search", json=body).json()
        for item in data.get("results", []):
            title = "".join(t.get("plain_text", "") for t in item.get("title", []))
            rows.append((title or "(без названия)", (item.get("parent") or {}).get("database_id")))
        if not data.get("has_more"):
            break
        cursor = data["next_cursor"]
    print(f"Connection видит баз: {len(rows)}")
    for title, database_id in sorted(rows):
        print(f"  {title} | {database_id}")


def notion_db(target: str) -> None:
    client = _notion()
    database_id = _notion_id(target)
    response = client.get(f"{NOTION_API}/databases/{database_id}")
    if response.status_code != 200:
        code = response.json().get("code")
        print(f"{database_id}: HTTP {response.status_code} {code}")
        if response.status_code == 404:
            print("Connection не подключён к этой базе (или это не база, а страница).")
        return
    data = response.json()
    title = "".join(t.get("plain_text", "") for t in data.get("title", []))
    print(f"База «{title}» {database_id}, источников данных: {len(data.get('data_sources', []))}")
    for source in data.get("data_sources", []):
        schema = client.get(f"{NOTION_API}/data_sources/{source['id']}").json()
        for name, prop in schema.get("properties", {}).items():
            extra = ""
            if prop["type"] == "relation":
                extra = f" -> {prop['relation'].get('database_id')}"
            print(f"  {name}: {prop['type']}{extra}")
        query = client.post(
            f"{NOTION_API}/data_sources/{source['id']}/query",
            json={
                "page_size": 1,
                "sorts": [{"timestamp": "last_edited_time", "direction": "descending"}],
            },
        ).json()
        results = query.get("results", [])
        print("  последняя правка:", results[0]["last_edited_time"][:10] if results else "пусто")


# ---------------------------------------------------------------------------- Yandex Disk

DISK_LIST = r"""
h = {"Authorization": "OAuth " + token}
q = urllib.parse.urlencode({"path": "disk:/" + P["folder"], "limit": P["limit"], "sort": "-created"})
req = urllib.request.Request("https://cloud-api.yandex.net/v1/disk/resources?" + q, headers=h)
emb = json.load(urllib.request.urlopen(req, timeout=30))["_embedded"]
print(f"«{P['folder']}»: файлов {emb['total']}, последние {len(emb['items'])}:")
for i in emb["items"]:
    props = i.get("custom_properties") or {}
    print(" ", i["created"][:16], "|", i["name"], "| processed" if props.get("processed") else "")
"""

# Before onboarding: refresh token kept in a root-only file on the host; client id/secret from
# backend.env. Yandex rotates the refresh token, so a new one is written back to the file.
DISK_FROM_FILE = (
    r"""
import re, urllib.parse, urllib.request
env = {}
for line in open("/etc/recording-agent/backend.env", encoding="utf-8"):
    m = re.match(r"^(YANDEX_CLIENT_ID|YANDEX_CLIENT_SECRET)=(.*)$", line.strip())
    if m:
        env[m.group(1)] = m.group(2).strip().strip('"').strip("'")
refresh = open(P["token_file"]).read().strip()
body = urllib.parse.urlencode({"grant_type": "refresh_token", "refresh_token": refresh,
    "client_id": env["YANDEX_CLIENT_ID"], "client_secret": env["YANDEX_CLIENT_SECRET"]}).encode()
tok = json.load(urllib.request.urlopen("https://oauth.yandex.ru/token", body, timeout=30))
if tok.get("refresh_token") and tok["refresh_token"] != refresh:
    open(P["token_file"], "w").write(tok["refresh_token"])
    print("refresh-токен обновлён Яндексом, файл на сервере перезаписан")
token = tok["access_token"]
"""
    + DISK_LIST
)

# After onboarding: the backend's own token manager (tokens in its database).
DISK_FROM_BACKEND = (
    r"""
import asyncio, urllib.parse, urllib.request
from app.config import get_settings
from app.db.engine import create_engine, create_session_factory
from app.services.yandex_token_manager import YandexTokenManager

async def access_token():
    settings = get_settings(); engine = create_engine(settings)
    try:
        return await YandexTokenManager(create_session_factory(engine), settings).get_access_token(P["email"])
    finally:
        await engine.dispose()

token = asyncio.run(access_token())
"""
    + DISK_LIST
)


def _on_host(code: str, params: dict[str, Any], timeout: int = 120) -> str:
    """Run Python 3 on the host as root (for root-only files such as a pre-onboarding token)."""
    script = "python3 - 2>&1 <<'PYEOF'" + NL + _wrap(code, params) + NL + "PYEOF" + NL
    return remote.bash(script, timeout=timeout, check=False)


def disk(email: str, folder: str, limit: int, token_file: str | None) -> None:
    params = {"email": email, "folder": folder, "limit": limit, "token_file": token_file}
    if token_file:
        print(_on_host(DISK_FROM_FILE, params))
    else:
        print(_in_backend(DISK_FROM_BACKEND, params))


# ---------------------------------------------------------------------------- CalDAV

CALENDAR_CODE = r"""
import datetime as dt, re, urllib.parse
import httpx
from app.config import get_settings
password = P.get("password")
if not password:
    secret = get_settings().yandex_caldav_passwords.get(P["email"])
    if secret is None:
        raise KeyError("CalDAV password for this recruiter is not in backend.env; pass --env")
    password = secret.get_secret_value()
auth = (P["email"], password)
home = f"https://caldav.yandex.ru/calendars/{urllib.parse.quote(P['email'])}/"
r = httpx.request("PROPFIND", home, auth=auth, headers={"Depth": "1"}, timeout=30,
    content='<?xml version="1.0"?><d:propfind xmlns:d="DAV:"><d:prop><d:displayname/></d:prop></d:propfind>')
if r.status_code == 401:
    raise PermissionError("CalDAV 401: wrong app password or CalDAV disabled for the account")
r.raise_for_status()
cals = re.findall(r"<href[^>]*>([^<]*/events-\d+/)</href>.*?<D:displayname>([^<]*)<", r.text, re.S)
print("Календари:", [name for _, name in cals])
now = dt.datetime.now(dt.UTC)
start = (now - dt.timedelta(days=P["back"])).strftime("%Y%m%dT000000Z")
end = (now + dt.timedelta(days=P["ahead"])).strftime("%Y%m%dT000000Z")
query = ('<?xml version="1.0"?><c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
    '<d:prop><c:calendar-data/></d:prop><c:filter><c:comp-filter name="VCALENDAR"><c:comp-filter name="VEVENT">'
    f'<c:time-range start="{start}" end="{end}"/></c:comp-filter></c:comp-filter></c:filter></c:calendar-query>')
for href, name in cals:
    if P.get("calendar") and name != P["calendar"]:
        continue
    rep = httpx.request("REPORT", "https://caldav.yandex.ru" + href, auth=auth, headers={"Depth": "1"},
                        content=query, timeout=60)
    text = rep.text.replace("&#13;", "").replace("\r\n ", "").replace("\n ", "")
    events = re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", text, re.S)
    recurring = [e for e in events if re.search(r"^(RRULE|RECURRENCE-ID)", e, re.M)]
    if not P["recurring"]:
        events = [e for e in events if e not in recurring]
    print(f"«{name}»: событий {len(events)} (−{P['back']} … +{P['ahead']} дн.)"
          + ("" if P["recurring"] else f", повторяющихся скрыто: {len(recurring)}"))
    for e in sorted(events, key=lambda e: (re.search(r"\nDTSTART[^:]*:(\S+)", e) or [None, ""])[1]):
        get = lambda key: (re.search(rf"\n{key}[^:\n]*:(.*)", e) or [None, ""])[1].strip()
        desc = get("DESCRIPTION").replace("\\n", " ")
        hosts = sorted(set(re.findall(r"https?://([a-z0-9.\-]+)", desc)))
        print(" ", get("DTSTART"), "|", get("SUMMARY")[:100], "| ссылки:", hosts)
        if P["full"]:
            print("     описание:", desc[:400])
            print("     место:", get("LOCATION")[:200], "| организатор:", get("ORGANIZER")[:80])
"""


def calendar(
    email: str,
    env_file: str | None,
    back: int,
    ahead: int,
    full: bool,
    name: str | None,
    recurring: bool = False,
) -> None:
    password = None
    if env_file:
        values = _local_env(ROOT / env_file, r"[A-Z_]+_CALDAV_APP_PASSWORD")
        password = next(iter(values.values()), None)
        if not password:
            raise SystemExit(f"no *_CALDAV_APP_PASSWORD in {env_file}")
    params = {
        "email": email,
        "password": password,
        "back": back,
        "ahead": ahead,
        "full": full,
        "calendar": name,
        "recurring": recurring,
    }
    print(_in_backend(CALENDAR_CODE, params))


# ---------------------------------------------------------------------------- Synology, Mattermost


def synology(paths: list[str]) -> None:
    result = remote.stand("syno_exists", {"paths": paths})
    for path in paths:
        print(f"  {path} -> {result.get(path) if isinstance(result, dict) else result}")


MATTERMOST_CODE = r"""
import datetime as dt
import httpx
from app.config import get_settings
s = get_settings()
base = s.mattermost_url.rstrip("/"); bot = s.mattermost_bot_user_id
h = {"Authorization": "Bearer " + s.mattermost_bot_token.get_secret_value()}
u = httpx.get(f"{base}/api/v4/users/email/{P['email']}", headers=h, timeout=20)
if u.status_code != 200:
    print("Пользователь по почте не найден:", u.status_code)
else:
    uid = u.json()["id"]; print("user id:", uid, "| username:", u.json().get("username"))
    name = "__".join(sorted([bot, uid]))
    chans = httpx.get(f"{base}/api/v4/users/{bot}/channels", headers=h, timeout=30).json()
    dm = [c for c in chans if c.get("name") == name]
    if dm:
        c = dm[0]; last = dt.datetime.fromtimestamp(c.get("last_post_at", 0) / 1000, dt.UTC)
        print("DM с ботом:", c["id"], "| сообщений:", c.get("total_msg_count"), "| последнее:", last.isoformat()[:16])
    else:
        print("Лички с ботом нет: рекрутеру нужно написать боту")
"""


def mattermost(email: str) -> None:
    print(_in_backend(MATTERMOST_CODE, {"email": email}))


# ---------------------------------------------------------------------------- Mail (IMAP)


def _mail_password(email: str, env_file: str | None) -> str:
    if env_file:
        values = _local_env(ROOT / env_file, r"[A-Z_]+_MAIL_APP_PASSWORD")
        password = next(iter(values.values()), None)
        if not password:
            raise SystemExit(f"no *_MAIL_APP_PASSWORD in {env_file}")
        return password
    values = _local_env(ROOT / ".env", "YANDEX_MAIL_APP_PASSWORDS")
    raw = values.get("YANDEX_MAIL_APP_PASSWORDS")
    if not raw:
        raise SystemExit("YANDEX_MAIL_APP_PASSWORDS not found in the local .env")
    passwords = json.loads(raw)
    password = passwords.get(email)
    if not password:
        raise SystemExit(f"no app password for {email!r} in YANDEX_MAIL_APP_PASSWORDS")
    return password


def mail(email: str, env_file: str | None) -> None:
    import imaplib

    password = _mail_password(email, env_file)
    try:
        with imaplib.IMAP4_SSL("imap.yandex.ru", 993, timeout=30) as conn:
            conn.login(email, password)
            status, mailboxes = conn.list()
            box_count = len(mailboxes) if status == "OK" and mailboxes else 0
            print(f"{email}: IMAP login OK, папок: {box_count}")
            status, data = conn.select("INBOX", readonly=True)
            count = int(data[0]) if status == "OK" and data and data[0] else 0
            print("  INBOX: писем", count)
    except imaplib.IMAP4.error as error:
        print(f"{email}: IMAP login FAILED: {error}")


# ---------------------------------------------------------------------------- CLI


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only production data inspection")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("notion-search")
    db = sub.add_parser("notion-db")
    db.add_argument("target")
    dk = sub.add_parser("disk")
    dk.add_argument("--email", required=True)
    dk.add_argument("--folder", default="Записи Телемоста")
    dk.add_argument("--limit", type=int, default=30)
    dk.add_argument("--token-file")
    cal = sub.add_parser("calendar")
    cal.add_argument("--email", required=True)
    cal.add_argument("--env", dest="env_file")
    cal.add_argument("--calendar", help="only this calendar (display name)")
    cal.add_argument("--days-back", type=int, default=14)
    cal.add_argument("--days-ahead", type=int, default=3)
    cal.add_argument("--full", action="store_true", help="also print description and location")
    cal.add_argument("--recurring", action="store_true", help="include recurring series")
    syn = sub.add_parser("synology")
    syn.add_argument("paths", nargs="+")
    mm = sub.add_parser("mattermost")
    mm.add_argument("--email", required=True)
    ml = sub.add_parser("mail")
    ml.add_argument("--email", required=True)
    ml.add_argument("--env", dest="env_file")
    args = parser.parse_args()

    if args.command == "notion-search":
        notion_search()
    elif args.command == "notion-db":
        notion_db(args.target)
    elif args.command == "disk":
        disk(args.email, args.folder, args.limit, args.token_file)
    elif args.command == "calendar":
        calendar(
            args.email, args.env_file, args.days_back, args.days_ahead, args.full, args.calendar
        )
    elif args.command == "synology":
        synology(args.paths)
    elif args.command == "mail":
        mail(args.email, args.env_file)
    else:
        mattermost(args.email)


if __name__ == "__main__":
    main()
