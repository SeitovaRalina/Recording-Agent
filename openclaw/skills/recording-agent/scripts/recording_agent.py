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

STATUS_LABELS = {
    "found": "найдена, ожидает сопоставления с календарём",
    "calendar_event_found": "событие календаря найдено",
    "candidate_matched": "кандидат найден в Notion",
    "manual_review_required": "требуется review",
    "transfer_started": "перенос начат",
    "uploaded_to_synology": "файл загружен в хранилище",
    "synology_link_created": "ссылка на файл создана",
    "notion_updated": "Notion обновлён",
    "source_marked_processed": "обработка завершена",
    "source_deleted": "исходный файл удалён по retention policy",
    "completed": "обработка завершена",
    "ignored": "запись проигнорирована",
    "failed": "ошибка обработки",
}

REVIEW_REASON_LABELS = {
    "low_confidence": "недостаточно уверенное совпадение с событием календаря",
    "no_compatible_event": "подходящее событие календаря не найдено",
    "multiple_compatible_events": "найдено несколько подходящих событий календаря",
    "no_candidate_name_in_event": "в названии события не указано имя кандидата",
    "no_candidate_found": "кандидат с нужным именем и датой не найден в Notion",
    "multiple_candidates": "в Notion найдено несколько подходящих кандидатов",
    "storage_key_collision": "путь в хранилище уже занят другой записью",
}


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


def _add_recruiter_user_id_argument(parser: argparse.ArgumentParser) -> None:
    trusted_user_id = os.environ.get("RECORDING_AGENT_RECRUITER_USER_ID", "").strip()
    parser.add_argument(
        "--recruiter-user-id",
        default=trusted_user_id or None,
        required=not trusted_user_id,
    )


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
    _add_recruiter_user_id_argument(status)
    status.add_argument("--date")
    status.add_argument("--candidate")
    status.add_argument("--recording-id", type=uuid.UUID)
    status.add_argument("--status")
    status.add_argument("--limit", type=int, default=20, choices=range(1, 51), metavar="1..50")

    review = subparsers.add_parser("review", help="get bounded review context")
    review.add_argument("--review-id", required=True, type=uuid.UUID)
    _add_recruiter_user_id_argument(review)
    review.add_argument("--mattermost-thread-id", required=True)
    review.add_argument("--token", required=True)

    for name in ("resolve", "ignore"):
        mutation = subparsers.add_parser(name, help=f"{name} one manual review")
        mutation.add_argument("--review-id", required=True, type=uuid.UUID)
        _add_recruiter_user_id_argument(mutation)
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


def _status_label(status: object) -> str:
    value = str(status or "unknown")
    return STATUS_LABELS.get(value, value)


def _review_reason(reason: object) -> str:
    value = str(reason or "manual_review_required")
    return REVIEW_REASON_LABELS.get(value, value)


def _item_line(item: dict[str, Any], *, review: bool = False) -> str:
    filename = str(item.get("filename") or "запись без имени")
    parts = [filename]
    candidate = item.get("candidate_name")
    if candidate:
        parts.append(f"кандидат: {candidate}")
    if "is_new" in item:
        parts.append("новая запись" if item.get("is_new") else "повторная обработка")
    if review:
        parts.append(f"review: {_review_reason(item.get('review_reason'))}")
    else:
        parts.append(f"статус: {_status_label(item.get('status'))}")
    recording_id = item.get("id") or item.get("recording_id")
    if recording_id:
        parts.append(f"recording ID: {recording_id}")
    generated_filename = item.get("generated_filename")
    if generated_filename:
        parts.append(f"имя в хранилище: {generated_filename}")
    if item.get("error"):
        parts.append(f"ошибка: {item['error']}")
    if item.get("safe_link"):
        parts.append(f"ссылка: {item['safe_link']}")
    return "- " + "; ".join(parts)


def _scan_message(result: dict[str, Any]) -> str:
    items = [item for item in result.get("items", []) if isinstance(item, dict)]
    review_items = [item for item in items if item.get("requires_review")]
    failed_items = [item for item in items if item.get("status") == "failed"]
    clear_items = [
        item for item in items if not item.get("requires_review") and item.get("status") != "failed"
    ]
    lines = [
        "Проверка завершена.",
        f"Новых записей добавлено: {int(result.get('inserted', 0))}.",
        f"Обнаружено файлов для проверки: {int(result.get('discovered', 0))}.",
    ]
    skipped = int(result.get("skipped_legacy", 0))
    if skipped:
        lines.append(f"Старых записей пропущено по правилу canary: {skipped}.")
    lines.append(f"Обработано в этом запуске: {int(result.get('processed', len(items)))}.")
    lines.append(f"Требуют review: {int(result.get('manual_review', len(review_items)))}.")
    lines.extend(_item_line(item, review=True) for item in review_items)
    lines.append(f"Не требуют review: {int(result.get('without_review', len(clear_items)))}.")
    lines.extend(_item_line(item) for item in clear_items)
    failed_recordings = int(result.get("failed_recordings", len(failed_items)))
    lines.append(f"С ошибкой: {failed_recordings}.")
    lines.extend(_item_line(item) for item in failed_items)
    if result.get("items_truncated"):
        lines.append(
            f"Показано результатов: {len(items)} из "
            f"{int(result.get('processed', len(items)))}. "
            "Остальные не включены в ответ; сузьте status-запрос по дате, кандидату, "
            "recording ID или статусу."
        )
    backend_failures = int(result.get("failed", 0))
    additional_failures = max(0, backend_failures - failed_recordings)
    if additional_failures:
        lines.append(f"Дополнительных ошибок текущего запуска: {additional_failures}.")
    return "\n".join(lines)


def _status_message(result: dict[str, Any]) -> str:
    items = [item for item in result.get("items", []) if isinstance(item, dict)]
    if not items:
        return "По заданным фильтрам записей не найдено."
    lines = [f"Найдено записей: {len(items)}."]
    lines.extend(
        _item_line(item, review=item.get("status") == "manual_review_required") for item in items
    )
    return "\n".join(lines)


def _review_message(result: dict[str, Any]) -> str:
    lines = [
        f"Для записи {result.get('filename', 'без имени')} требуется review: "
        f"{_review_reason(result.get('reason'))}.",
        f"recording ID: {result.get('recording_id', '')}.",
    ]
    choices = [choice for choice in result.get("choices", []) if isinstance(choice, dict)]
    if choices:
        lines.append("Доступные варианты:")
        for index, choice in enumerate(choices, start=1):
            label = str(choice.get("name") or choice.get("summary") or choice.get("id") or index)
            project = choice.get("project_or_spot")
            url = choice.get("url")
            details = [label]
            if project:
                details.append(str(project))
            if url:
                details.append(str(url))
            lines.append(f"{index}. " + " — ".join(details))
        lines.append("Ответьте номером одного варианта или попросите проигнорировать запись.")
    else:
        lines.append("Автоматических вариантов нет; требуется ручная проверка данных.")
    return "\n".join(lines)


def _mutation_message(command: str, result: dict[str, Any]) -> str:
    action = "Выбор принят" if command == "resolve" else "Запись проигнорирована"
    replay = (
        " Повторный запрос не создал дополнительную обработку." if result.get("replayed") else ""
    )
    return (
        f"{action}. recording ID: {result.get('recording_id', '')}; "
        f"статус: {_status_label(result.get('status'))}.{replay}"
    )


def _message_for(command: str, result: Any) -> str:
    if not isinstance(result, dict):
        return "Backend выполнил запрос, но вернул результат неизвестного формата."
    if command == "scan":
        return _scan_message(result)
    if command == "status":
        return _status_message(result)
    if command == "review":
        return _review_message(result)
    return _mutation_message(command, result)


def _error_message(error: str) -> str:
    if "HTTP 401" in error or "HTTP 403" in error:
        return "Не удалось выполнить запрос: backend отклонил авторизацию. Обратитесь к оператору."
    if "HTTP 404" in error:
        return "Запрошенная запись или review недоступны либо уже не существуют."
    if "HTTP 409" in error:
        return (
            "Данные review уже изменились или запрос был повторён с другим контекстом. "
            "Обновите статус."
        )
    if "HTTP 410" in error:
        return "Срок действия review истёк. Запросите актуальный статус записи."
    if error.startswith("Backend unavailable"):
        return "Backend Recording Agent сейчас недоступен. Повторите запрос позже."
    return f"Не удалось выполнить запрос Recording Agent: {error}"


def main() -> int:
    try:
        args = _parser().parse_args()
        result = _execute(args)
        print(
            json.dumps(
                {"ok": True, "message": _message_for(args.command, result), "result": result},
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
        return 0
    except ClientError as exc:
        error = str(exc)
        print(
            json.dumps(
                {"ok": False, "message": _error_message(error), "error": error},
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
