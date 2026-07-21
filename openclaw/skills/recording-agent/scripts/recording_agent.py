#!/usr/bin/env python3
"""Deterministic loopback client for Recording Agent Backend intents."""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import uuid
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

DEFAULT_BACKEND_URL = "http://127.0.0.1:8000"
MAX_RESPONSE_BYTES = 65_536
TIMEOUT_SECONDS = 15.0


class ClientError(Exception):
    """Represent a safe client-facing failure."""


def _backend_url() -> str:
    raw = os.environ.get("RECORDING_AGENT_BACKEND_URL", DEFAULT_BACKEND_URL).rstrip("/")
    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ClientError("RECORDING_AGENT_BACKEND_URL must be an HTTP(S) URL")
    try:
        is_loopback = ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError:
        is_loopback = parsed.hostname.lower() == "localhost"
    if not is_loopback or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ClientError("RECORDING_AGENT_BACKEND_URL must be a loopback-only base URL")
    return raw


def _secret() -> str:
    secret = os.environ.get("RECORDING_AGENT_BACKEND_SECRET", "")
    if not secret:
        raise ClientError("RECORDING_AGENT_BACKEND_SECRET is required")
    return secret


def _request(
    method: str,
    path: str,
    *,
    query: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> Any:
    base = urlsplit(_backend_url())
    query_string = urlencode(
        [(key, str(value)) for key, value in (query or {}).items() if value is not None]
    )
    url = urlunsplit((base.scheme, base.netloc, f"{base.path.rstrip('/')}{path}", query_string, ""))
    data = None if body is None else json.dumps(body, separators=(",", ":")).encode("utf-8")
    request = Request(
        url,
        data=data,
        method=method,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {_secret()}",
            **({"Content-Type": "application/json"} if data is not None else {}),
            **(headers or {}),
        },
    )
    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            payload = response.read(MAX_RESPONSE_BYTES + 1)
            status = response.status
    except HTTPError as exc:
        payload = exc.read(MAX_RESPONSE_BYTES + 1)
        status = exc.code
    except (TimeoutError, URLError, OSError) as exc:
        raise ClientError(f"Backend unavailable: {type(exc).__name__}") from None
    if len(payload) > MAX_RESPONSE_BYTES:
        raise ClientError("Backend response exceeded size limit")
    try:
        decoded = json.loads(payload) if payload else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ClientError(f"Backend returned invalid JSON (HTTP {status})") from None
    if not 200 <= status < 300:
        detail = decoded.get("detail") if isinstance(decoded, dict) else None
        raise ClientError(f"Backend rejected request (HTTP {status}): {detail or 'request failed'}")
    return decoded


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Call bounded Recording Agent Backend intents")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan = subparsers.add_parser("scan", help="trigger one recruiter scan")
    scan.add_argument("--recruiter-email", required=True)
    scan.add_argument("--idempotency-key", required=True)

    status = subparsers.add_parser("status", help="query bounded recording statuses")
    status.add_argument("--recruiter-user-id", required=True)
    status.add_argument("--date")
    status.add_argument("--candidate")
    status.add_argument("--recording-id", type=uuid.UUID)
    status.add_argument("--status")
    status.add_argument("--limit", type=int, default=20, choices=range(1, 51), metavar="1..50")

    review = subparsers.add_parser("review", help="get bounded review context")
    review.add_argument("--review-id", required=True, type=uuid.UUID)
    review.add_argument("--recruiter-user-id", required=True)
    review.add_argument("--mattermost-thread-id", required=True)
    review.add_argument("--token", required=True)

    for name in ("resolve", "ignore"):
        mutation = subparsers.add_parser(name, help=f"{name} one manual review")
        mutation.add_argument("--review-id", required=True, type=uuid.UUID)
        mutation.add_argument("--recruiter-user-id", required=True)
        mutation.add_argument("--mattermost-thread-id", required=True)
        mutation.add_argument("--token", required=True)
        mutation.add_argument("--expected-version", required=True, type=int)
        mutation.add_argument("--idempotency-key", required=True)
        if name == "resolve":
            mutation.add_argument("--choice", required=True, type=int, choices=range(1, 11))
    return parser


def _execute(args: argparse.Namespace) -> Any:
    if args.command == "scan":
        return _request(
            "POST",
            "/tools/scans/trigger",
            body={
                "recruiter_email": args.recruiter_email,
                "scope": "test",
                "idempotency_key": args.idempotency_key,
            },
        )
    if args.command == "status":
        return _request(
            "GET",
            "/tools/recordings/status",
            query={
                "recruiter_user_id": args.recruiter_user_id,
                "on_date": args.date,
                "candidate": args.candidate,
                "recording_id": str(args.recording_id) if args.recording_id else None,
                "status": args.status,
                "limit": args.limit,
            },
        )
    if args.command == "review":
        return _request(
            "GET",
            f"/tools/reviews/{args.review_id}",
            query={
                "recruiter_user_id": args.recruiter_user_id,
                "mattermost_thread_id": args.mattermost_thread_id,
            },
            headers={"X-Review-Token": args.token},
        )
    body = {
        "recruiter_user_id": args.recruiter_user_id,
        "mattermost_thread_id": args.mattermost_thread_id,
        "token": args.token,
        "expected_version": args.expected_version,
        "idempotency_key": args.idempotency_key,
    }
    if args.command == "resolve":
        body["choice"] = args.choice
    return _request("POST", f"/tools/reviews/{args.review_id}/{args.command}", body=body)


def main() -> int:
    try:
        result = _execute(_parser().parse_args())
        print(json.dumps({"ok": True, "result": result}, ensure_ascii=False, separators=(",", ":")))
        return 0
    except ClientError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, separators=(",", ":")))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
