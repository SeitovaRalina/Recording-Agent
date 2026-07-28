from __future__ import annotations

import argparse
import json
import sys
from collections import deque
from typing import Any

import httpx

SOURCE_ROOTS = ("/Recruiting-E", "/Recruiting-NE")
TARGET_PARENT = "/home"
TARGET_ROOT_NAMES = {
    "Recruiting-E": "Recruiting-E",
    "Recruiting-NE": "Recruiting-NE",
}
PAGE_SIZE = 100
DEVICE_NAME = "recording-agent-codex"


def parse_env(path: str = ".env") -> dict[str, str]:
    values: dict[str, str] = {}
    with open(path, encoding="utf-8-sig") as file:
        for line in file.read().splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            values[key.strip()] = value
    return values


def canonical(path: str) -> str:
    if not path.startswith("/") or "\\" in path or "\x00" in path:
        raise ValueError(f"Invalid Synology path: {path!r}")
    parts = [part for part in path.split("/") if part]
    if any(part in {".", ".."} for part in parts):
        raise ValueError(f"Path traversal is forbidden: {path!r}")
    return "/" + "/".join(parts)


def validate(response: httpx.Response, *, allow_codes: set[int] | None = None) -> dict[str, Any]:
    payload = response.json()
    error = payload.get("error") if isinstance(payload, dict) else None
    code = error.get("code") if isinstance(error, dict) else None
    if code in (allow_codes or set()):
        return payload
    if response.is_error or not isinstance(payload, dict) or payload.get("success") is False:
        raise RuntimeError(json.dumps(payload, ensure_ascii=False)[:500])
    return payload


def login(
    client: httpx.Client, base_url: str, env: dict[str, str], otp: str | None
) -> tuple[str, bool]:
    params = {
        "api": "SYNO.API.Auth",
        "version": "6",
        "method": "login",
        "account": env["SYNOLOGY_USER"],
        "passwd": env["SYNOLOGY_PASS"],
        "session": "FileStation",
        "format": "sid",
    }
    if otp:
        params.update(
            {
                "otp_code": otp,
                "enable_device_token": "yes",
                "device_name": DEVICE_NAME,
            }
        )
    elif env.get("SYNOLOGY_DEVICE_ID"):
        params["device_id"] = env["SYNOLOGY_DEVICE_ID"]
    else:
        raise RuntimeError("Provide --otp once or set SYNOLOGY_DEVICE_ID in .env")

    payload = validate(client.get(f"{base_url}/webapi/entry.cgi", params=params))
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    sid = data.get("sid")
    if not isinstance(sid, str) or not sid:
        raise RuntimeError("Synology auth succeeded without SID")
    return sid, isinstance(data.get("did"), str)


def logout(client: httpx.Client, base_url: str, sid: str) -> None:
    client.get(
        f"{base_url}/webapi/entry.cgi",
        params={
            "api": "SYNO.API.Auth",
            "version": "6",
            "method": "logout",
            "session": "FileStation",
            "_sid": sid,
        },
    )


def list_dirs(client: httpx.Client, base_url: str, sid: str, folder_path: str) -> list[str]:
    output: list[str] = []
    offset = 0
    while True:
        payload = validate(
            client.get(
                f"{base_url}/webapi/entry.cgi",
                params={
                    "api": "SYNO.FileStation.List",
                    "method": "list",
                    "version": "2",
                    "folder_path": folder_path,
                    "filetype": "dir",
                    "offset": offset,
                    "limit": PAGE_SIZE,
                    "additional": '["perm","real_path"]',
                    "_sid": sid,
                },
            )
        )
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        files = data.get("files") if isinstance(data.get("files"), list) else []
        for item in files:
            if not isinstance(item, dict):
                continue
            path = item.get("path")
            if isinstance(path, str):
                output.append(canonical(path))
        total = data.get("total")
        offset += len(files)
        if not files or len(files) < PAGE_SIZE or (isinstance(total, int) and offset >= total):
            return output


def list_dirs_soft(
    client: httpx.Client,
    base_url: str,
    sid: str,
    folder_path: str,
    skipped: list[tuple[str, str]],
) -> list[str]:
    try:
        return list_dirs(client, base_url, sid, folder_path)
    except Exception as error:
        skipped.append((folder_path, str(error)))
        return []


def collect_tree(
    client: httpx.Client,
    base_url: str,
    sid: str,
    root: str,
    *,
    max_depth: int,
    skipped: list[tuple[str, str]],
) -> list[str]:
    output: list[str] = []
    queue: deque[tuple[str, int]] = deque([(root, 0)])
    seen = {root}
    while queue:
        parent, depth = queue.popleft()
        if depth >= max_depth:
            continue
        for path in list_dirs_soft(client, base_url, sid, parent, skipped):
            if path in seen:
                continue
            seen.add(path)
            output.append(path)
            queue.append((path, depth + 1))
    return output


def exists_dir(client: httpx.Client, base_url: str, sid: str, path: str) -> bool:
    canonical_path = canonical(path)
    parent_path, _, _ = canonical_path.rpartition("/")
    parent_path = parent_path or "/"
    try:
        return canonical_path in list_dirs(client, base_url, sid, parent_path)
    except Exception:
        pass

    response = client.get(
        f"{base_url}/webapi/entry.cgi",
        params={
            "api": "SYNO.FileStation.List",
            "method": "getinfo",
            "version": "2",
            "path": json.dumps([path]),
            "_sid": sid,
        },
    )
    try:
        payload = response.json()
    except ValueError:
        return False
    if not isinstance(payload, dict) or payload.get("success") is not True:
        return False
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    files = data.get("files") if isinstance(data.get("files"), list) else []
    for item in files:
        if not isinstance(item, dict):
            continue
        if item.get("isdir") is False:
            continue
        returned_path = item.get("path")
        if isinstance(returned_path, str) and canonical(returned_path) == canonical_path:
            return True
    return False


def create_dir(client: httpx.Client, base_url: str, sid: str, parent: str, name: str) -> None:
    if not name or name in {".", ".."} or "/" in name or "\\" in name:
        raise ValueError(f"Unsafe folder name: {name!r}")
    response = client.post(
        f"{base_url}/webapi/entry.cgi",
        params={
            "api": "SYNO.FileStation.CreateFolder",
            "method": "create",
            "version": "2",
            "_sid": sid,
        },
        data={"folder_path": parent, "name": name, "force_parent": "false"},
    )
    payload = response.json()
    error = payload.get("error") if isinstance(payload, dict) else None
    code = error.get("code") if isinstance(error, dict) else None
    if payload.get("success") is True or not name[:1].isdigit():
        validate(response, allow_codes={409, 1101})
        return
    if code in {409, 1101}:
        return

    # This DSM rejects CreateFolder names that start with a digit. Create a temporary
    # alphabetic folder, then rename it using the quoted query format File Station accepts.
    import uuid

    temp_name = f"tmp-recording-agent-{uuid.uuid4().hex[:12]}"
    temp_path = f"{parent.rstrip('/')}/{temp_name}"
    validate(
        client.post(
            f"{base_url}/webapi/entry.cgi",
            params={
                "api": "SYNO.FileStation.CreateFolder",
                "method": "create",
                "version": "2",
                "_sid": sid,
            },
            data={"folder_path": parent, "name": temp_name, "force_parent": "false"},
        )
    )
    validate(
        client.get(
            f"{base_url}/webapi/entry.cgi",
            params={
                "api": "SYNO.FileStation.Rename",
                "method": "rename",
                "version": "2",
                "_sid": sid,
                "path": f'"{temp_path}"',
                "name": f'"{name}"',
            },
        )
    )


def ensure_path(
    client: httpx.Client,
    base_url: str,
    sid: str,
    path: str,
    *,
    created: list[str],
    errors: list[tuple[str, str]],
) -> None:
    parts = [part for part in canonical(path).split("/") if part]
    parent = "/"
    for part in parts:
        target = f"/{part}" if parent == "/" else f"{parent.rstrip('/')}/{part}"
        if not exists_dir(client, base_url, sid, target):
            try:
                create_dir(client, base_url, sid, parent, part)
                created.append(target)
            except Exception as error:
                errors.append((target, str(error)))
                return
        parent = target


def list_home(client: httpx.Client, base_url: str, sid: str) -> None:
    rows = list_dirs(client, base_url, sid, TARGET_PARENT)
    print(f"{TARGET_PARENT} folders: {len(rows)}")
    for path in rows:
        print(path)


def mirror_home(client: httpx.Client, base_url: str, sid: str, *, max_depth: int) -> None:
    skipped: list[tuple[str, str]] = []
    source_dirs: list[str] = []
    for root in SOURCE_ROOTS:
        source_dirs.append(root)
        source_dirs.extend(
            collect_tree(client, base_url, sid, root, max_depth=max_depth, skipped=skipped)
        )

    desired: list[str] = []
    for source in source_dirs:
        parts = [part for part in canonical(source).split("/") if part]
        if parts and parts[0] in TARGET_ROOT_NAMES:
            target_parts = [TARGET_ROOT_NAMES[parts[0]], *parts[1:]]
            desired.append(f"{TARGET_PARENT}/{'/'.join(target_parts)}")

    created: list[str] = []
    errors: list[tuple[str, str]] = []
    for path in desired:
        ensure_path(client, base_url, sid, path, created=created, errors=errors)

    print(f"Source directories found: {len(source_dirs)}")
    print(f"Skipped source folders: {len(skipped)}")
    for path, error in skipped:
        print(f"SKIP {path} {error[:160]}")
    print(f"Desired {TARGET_PARENT} directories: {len(desired)}")
    print(f"Created directories: {len(created)}")
    for path in created:
        print(f"CREATED {path}")
    print(f"Create errors: {len(errors)}")
    for path, error in errors:
        print(f"CREATE_ERROR {path} {error[:160]}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Synology SID/OTP operator helper.")
    parser.add_argument("command", choices=("list-home", "mirror-home"))
    parser.add_argument("--otp", default=None)
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--max-depth", type=int, default=8)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    env = parse_env(args.env_file)
    for key in ("SYNOLOGY_BASE_URL", "SYNOLOGY_USER", "SYNOLOGY_PASS"):
        if not env.get(key):
            raise RuntimeError(f"Missing {key} in {args.env_file}")
    base_url = env["SYNOLOGY_BASE_URL"].rstrip("/")

    with httpx.Client(timeout=30, follow_redirects=True, verify=True, trust_env=False) as client:
        sid, device_token_returned = login(client, base_url, env, args.otp)
        try:
            print("Auth: OK")
            print(f"Device token returned: {'yes' if device_token_returned else 'no'}")
            if args.command == "list-home":
                list_home(client, base_url, sid)
            else:
                mirror_home(client, base_url, sid, max_depth=args.max_depth)
        finally:
            logout(client, base_url, sid)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1) from error
