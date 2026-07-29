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


def _add_trusted_argument(
    parser: argparse.ArgumentParser,
    option: str,
    environment_name: str,
    conflict_label: str,
    *,
    trusted_only: bool = False,
) -> None:
    trusted_value = os.environ.get(environment_name, "").strip()

    def verified_value(explicit_value: str) -> str:
        if trusted_only and not trusted_value:
            raise ClientError(f"Trusted {conflict_label} metadata is required")
        if trusted_value and explicit_value != trusted_value:
            raise ClientError(f"Explicit value conflicts with trusted {conflict_label}")
        return trusted_value or explicit_value

    parser.add_argument(
        option,
        default=trusted_value or None,
        required=not trusted_value,
        type=verified_value,
    )


def _add_recruiter_email_argument(
    parser: argparse.ArgumentParser, *, trusted_only: bool = False
) -> None:
    _add_trusted_argument(
        parser,
        "--recruiter-email",
        "RECORDING_AGENT_RECRUITER_EMAIL",
        "recruiter email",
        trusted_only=trusted_only,
    )


def _add_recruiter_user_id_argument(
    parser: argparse.ArgumentParser, *, trusted_only: bool = False
) -> None:
    _add_trusted_argument(
        parser,
        "--recruiter-user-id",
        "RECORDING_AGENT_RECRUITER_USER_ID",
        "recruiter identity",
        trusted_only=trusted_only,
    )


def _add_dm_channel_argument(
    parser: argparse.ArgumentParser, *, trusted_only: bool = False
) -> None:
    _add_trusted_argument(
        parser,
        "--mattermost-dm-channel-id",
        "RECORDING_AGENT_MATTERMOST_DM_CHANNEL_ID",
        "DM channel",
        trusted_only=trusted_only,
    )


def _request(
    method: str,
    path: str,
    *,
    query: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    authenticate: bool = True,
) -> Any:
    base = urlsplit(_backend_url())
    query_string = urlencode(
        [(key, str(value)) for key, value in (query or {}).items() if value is not None]
    )
    url = urlunsplit((base.scheme, base.netloc, f"{base.path.rstrip('/')}{path}", query_string, ""))
    data = None if body is None else json.dumps(body, separators=(",", ":")).encode("utf-8")
    request_headers = {
        "Accept": "application/json",
        **({"Content-Type": "application/json"} if data is not None else {}),
        **(headers or {}),
    }
    if authenticate:
        request_headers["Authorization"] = f"Bearer {_secret()}"
    request = Request(
        url,
        data=data,
        method=method,
        headers=request_headers,
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
    _add_recruiter_email_argument(scan, trusted_only=True)
    _add_recruiter_user_id_argument(scan, trusted_only=True)
    _add_dm_channel_argument(scan, trusted_only=True)
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

    questions = subparsers.add_parser("questions", help="list active DM questions")
    _add_recruiter_user_id_argument(questions, trusted_only=True)
    _add_dm_channel_argument(questions, trusted_only=True)
    questions.add_argument("--question-set-id", type=uuid.UUID)
    questions.add_argument("--limit", type=int, default=50, choices=range(1, 51), metavar="1..50")

    answer = subparsers.add_parser("answer", help="submit bounded partial question actions")
    _add_recruiter_user_id_argument(answer, trusted_only=True)
    _add_dm_channel_argument(answer, trusted_only=True)
    answer.add_argument("--actions-json", required=True)

    destinations = subparsers.add_parser("destinations", help="list safe storage destinations")
    _add_recruiter_user_id_argument(destinations)
    _add_dm_channel_argument(destinations)

    create_destination = subparsers.add_parser(
        "create-destination", help="create one folder below an opaque destination"
    )
    _add_recruiter_user_id_argument(create_destination)
    _add_dm_channel_argument(create_destination)
    create_destination.add_argument("--parent-destination-id", required=True, type=uuid.UUID)
    create_destination.add_argument("--name", required=True)

    non_interview = subparsers.add_parser(
        "non-interview", help="route one recording to a safe non-interview destination"
    )
    _add_recruiter_user_id_argument(non_interview)
    _add_dm_channel_argument(non_interview)
    non_interview.add_argument("--recording-id", required=True, type=uuid.UUID)
    non_interview.add_argument("--destination-id", required=True, type=uuid.UUID)
    non_interview.add_argument("--expected-version", required=True, type=int)
    non_interview.add_argument("--idempotency-key", required=True)

    route_interview = subparsers.add_parser(
        "route-interview", help="route one interview recording to a safe Synology destination"
    )
    _add_recruiter_user_id_argument(route_interview)
    _add_dm_channel_argument(route_interview)
    route_interview.add_argument("--recording-id", required=True, type=uuid.UUID)
    route_interview.add_argument("--destination-id", required=True, type=uuid.UUID)
    route_interview.add_argument("--expected-version", required=True, type=int)
    route_interview.add_argument("--idempotency-key", required=True)

    cleanup_preview = subparsers.add_parser(
        "cleanup-preview", help="preview eligible completed source recordings"
    )
    _add_recruiter_user_id_argument(cleanup_preview)
    _add_dm_channel_argument(cleanup_preview)
    cleanup_preview.add_argument(
        "--limit", type=int, default=50, choices=range(1, 101), metavar="1..100"
    )

    cleanup_confirm = subparsers.add_parser(
        "cleanup-confirm", help="confirm one immutable cleanup preview"
    )
    _add_recruiter_user_id_argument(cleanup_confirm)
    _add_dm_channel_argument(cleanup_confirm)
    cleanup_confirm.add_argument("--preview-id", required=True, type=uuid.UUID)
    cleanup_confirm.add_argument("--capability", required=True)
    cleanup_confirm.add_argument("--snapshot-hash", required=True)
    cleanup_confirm.add_argument("--idempotency-key", required=True)

    for name in ("routing-activate", "routing-resolve", "routing-defer"):
        routing = subparsers.add_parser(name, help=f"{name} one autonomous routing job")
        routing.add_argument("--job-id", required=True, type=uuid.UUID)
        routing.add_argument("--dispatch-nonce", required=True)
        if name == "routing-resolve":
            routing.add_argument("--snapshot-hash", required=True)
            routing.add_argument("--destination-id", required=True, type=uuid.UUID)
        if name == "routing-defer":
            routing.add_argument("--snapshot-hash", required=True)
            routing.add_argument(
                "--reason", required=True, choices=("ambiguous", "no_match", "model_error")
            )
    return parser


def _question_actions(raw: str) -> list[dict[str, Any]]:
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        raise ClientError("Question actions must be valid JSON") from None
    if not isinstance(decoded, list) or not 1 <= len(decoded) <= 50:
        raise ClientError("Question actions must contain 1..50 items")
    allowed = {
        "question_id",
        "question_set_id",
        "action",
        "capability",
        "expected_version",
        "idempotency_key",
        "choice",
    }
    actions: list[dict[str, Any]] = []
    for item in decoded:
        if not isinstance(item, dict) or set(item) - allowed:
            raise ClientError("Question action contains unsupported fields")
        try:
            action = str(item["action"])
            normalized = {
                "question_id": str(uuid.UUID(str(item["question_id"]))),
                "question_set_id": str(uuid.UUID(str(item["question_set_id"]))),
                "action": action,
                "capability": str(item["capability"]),
                "expected_version": int(item["expected_version"]),
                "idempotency_key": str(item["idempotency_key"]),
            }
        except (KeyError, TypeError, ValueError):
            raise ClientError("Question action is malformed") from None
        choice = item.get("choice")
        if action == "resolve":
            if not isinstance(choice, int) or not 1 <= choice <= 10:
                raise ClientError("Resolve action requires choice 1..10")
            normalized["choice"] = choice
        elif action != "ignore" or choice is not None:
            raise ClientError("Question action must be resolve or ignore")
        if not normalized["capability"] or len(normalized["idempotency_key"]) < 8:
            raise ClientError("Question action capability or idempotency key is invalid")
        actions.append(normalized)
    return actions


def _execute(args: argparse.Namespace) -> Any:
    if args.command == "routing-activate":
        return _request(
            "POST",
            f"/internal/routing-jobs/{args.job_id}/activate",
            body={"worker_id": "recordings-saver", "dispatch_nonce": args.dispatch_nonce},
            authenticate=False,
        )
    if args.command == "routing-resolve":
        if len(args.snapshot_hash) != 64 or any(
            character not in "0123456789abcdef" for character in args.snapshot_hash
        ):
            raise ClientError("Snapshot hash must be a lowercase SHA-256 hex value")
        return _request(
            "POST",
            f"/internal/routing-jobs/{args.job_id}/resolve",
            body={
                "worker_id": "recordings-saver",
                "dispatch_nonce": args.dispatch_nonce,
                "snapshot_hash": args.snapshot_hash,
                "destination_id": str(args.destination_id),
            },
            authenticate=False,
        )
    if args.command == "routing-defer":
        if len(args.snapshot_hash) != 64 or any(
            character not in "0123456789abcdef" for character in args.snapshot_hash
        ):
            raise ClientError("Snapshot hash must be a lowercase SHA-256 hex value")
        return _request(
            "POST",
            f"/internal/routing-jobs/{args.job_id}/defer",
            body={
                "worker_id": "recordings-saver",
                "dispatch_nonce": args.dispatch_nonce,
                "snapshot_hash": args.snapshot_hash,
                "reason": args.reason,
            },
            authenticate=False,
        )
    if args.command == "scan":
        return _request(
            "POST",
            "/tools/scans/trigger",
            body={
                "recruiter_email": args.recruiter_email,
                "recruiter_user_id": args.recruiter_user_id,
                "mattermost_dm_channel_id": args.mattermost_dm_channel_id,
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
    if args.command == "questions":
        return _request(
            "GET",
            "/tools/questions",
            query={
                "recruiter_user_id": args.recruiter_user_id,
                "mattermost_dm_channel_id": args.mattermost_dm_channel_id,
                "question_set_id": str(args.question_set_id) if args.question_set_id else None,
                "limit": args.limit,
            },
        )
    if args.command == "answer":
        return _request(
            "POST",
            "/tools/questions/answer",
            body={
                "recruiter_user_id": args.recruiter_user_id,
                "mattermost_dm_channel_id": args.mattermost_dm_channel_id,
                "actions": _question_actions(args.actions_json),
            },
        )
    if args.command == "destinations":
        return _request(
            "GET",
            "/tools/storage/destinations",
            query={
                "recruiter_user_id": args.recruiter_user_id,
                "mattermost_dm_channel_id": args.mattermost_dm_channel_id,
            },
        )
    if args.command == "create-destination":
        return _request(
            "POST",
            "/tools/storage/destinations",
            body={
                "recruiter_user_id": args.recruiter_user_id,
                "mattermost_dm_channel_id": args.mattermost_dm_channel_id,
                "parent_destination_id": str(args.parent_destination_id),
                "name": args.name,
            },
        )
    if args.command == "non-interview":
        return _request(
            "POST",
            f"/tools/recordings/{args.recording_id}/route-non-interview",
            body={
                "recruiter_user_id": args.recruiter_user_id,
                "mattermost_dm_channel_id": args.mattermost_dm_channel_id,
                "destination_id": str(args.destination_id),
                "expected_version": args.expected_version,
                "idempotency_key": args.idempotency_key,
            },
        )
    if args.command == "route-interview":
        return _request(
            "POST",
            f"/tools/recordings/{args.recording_id}/route-interview",
            body={
                "recruiter_user_id": args.recruiter_user_id,
                "mattermost_dm_channel_id": args.mattermost_dm_channel_id,
                "destination_id": str(args.destination_id),
                "expected_version": args.expected_version,
                "idempotency_key": args.idempotency_key,
            },
        )
    if args.command == "cleanup-preview":
        return _request(
            "POST",
            "/tools/cleanup/previews",
            body={
                "recruiter_user_id": args.recruiter_user_id,
                "mattermost_dm_channel_id": args.mattermost_dm_channel_id,
                "limit": args.limit,
            },
        )
    if args.command == "cleanup-confirm":
        return _request(
            "POST",
            f"/tools/cleanup/previews/{args.preview_id}/confirm",
            body={
                "recruiter_user_id": args.recruiter_user_id,
                "mattermost_dm_channel_id": args.mattermost_dm_channel_id,
                "capability": args.capability,
                "snapshot_hash": args.snapshot_hash,
                "idempotency_key": args.idempotency_key,
            },
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
    pending_items = [item for item in items if item.get("status") == "found"]
    clear_items = [
        item
        for item in items
        if not item.get("requires_review") and item.get("status") not in {"failed", "found"}
    ]
    if result.get("aborted"):
        errors = [item for item in result.get("errors", []) if isinstance(item, dict)]
        message = "Проверка остановлена до сканирования записей."
        if any(item.get("stage") == "calendar_discovery" for item in errors):
            message += (
                " Не удалось обновить список календарей. "
                "Проверьте доступ к Яндекс.Календарю и повторите проверку новым запросом."
            )
        return message
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
    lines.append(f"Ожидают повторной обработки: {int(result.get('pending', len(pending_items)))}.")
    lines.extend(_item_line(item) for item in pending_items)
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
                details.append(f"📍 Spots: {project}")
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
        f"status: {_status_label(result.get('status'))}.{replay}"
    )


def _questions_message(result: dict[str, Any]) -> str:
    items = [item for item in result.get("items", []) if isinstance(item, dict)]
    if not items:
        return "No active Recording Agent questions."
    lines = [f"Active Recording Agent questions: {len(items)}."]
    for number, item in enumerate(items, start=1):
        lines.append(
            f"{number}. {str(item.get('filename') or 'recording')[:240]} — "
            f"{str(item.get('reason') or 'clarification required')[:240]}"
        )
        choices = [choice for choice in item.get("choices", []) if isinstance(choice, dict)]
        for choice_number, choice in enumerate(choices[:10], start=1):
            details = [str(choice.get("name") or choice.get("summary") or "option")[:160]]
            if choice.get("project_or_spot"):
                details.append(f"📍 Spots: {str(choice['project_or_spot'])[:160]}")
            if choice.get("url"):
                details.append(str(choice["url"])[:500])
            lines.append(f"   {choice_number}) " + " — ".join(details))
    return "\n".join(lines)


def _answer_message(result: dict[str, Any]) -> str:
    accepted = [item for item in result.get("accepted", []) if isinstance(item, dict)]
    rejected = [item for item in result.get("rejected", []) if isinstance(item, dict)]
    pending = [item for item in result.get("pending", []) if item]
    lines = [
        f"Answers accepted: {len(accepted)}; rejected: {len(rejected)}; "
        f"still pending: {len(pending)}."
    ]
    for item in rejected:
        reason = str(item.get("reason") or "rejected")[:300]
        lines.append(f"- Question {item.get('question_id', '')}: {reason}")
    if accepted:
        lines.append("Processing started for the accepted answers.")
    return "\n".join(lines)


def _destinations_message(result: dict[str, Any]) -> str:
    items = [item for item in result.get("items", []) if isinstance(item, dict)]
    if not items:
        return "No writable storage destinations are available."
    lines = [f"Writable storage destinations: {len(items)}."]
    for number, item in enumerate(items, start=1):
        label = str(item.get("path_label") or item.get("display_name") or "folder")
        lines.append(f"{number}. {label[:240]}")
    return "\n".join(lines)


def _cleanup_preview_message(result: dict[str, Any]) -> str:
    items = [item for item in result.get("items", []) if isinstance(item, dict)]
    lines = [f"Cleanup preview contains {len(items)} completed recordings."]
    for number, item in enumerate(items, start=1):
        lines.append(
            f"{number}. {str(item.get('filename') or 'recording')[:240]} "
            f"(recording ID: {item.get('recording_id', '')})"
        )
    lines.append("Nothing has been moved. Explicit confirmation is required.")
    return "\n".join(lines)


def _cleanup_confirm_message(result: dict[str, Any]) -> str:
    items = [item for item in result.get("items", []) if isinstance(item, dict)]
    states: dict[str, int] = {}
    for item in items:
        state = str(item.get("state") or "unknown")
        states[state] = states.get(state, 0) + 1
    summary = ", ".join(f"{state}: {count}" for state, count in sorted(states.items()))
    return f"Cleanup confirmation completed. {summary or 'No eligible recordings.'}"


def _message_for(command: str, result: Any) -> str:
    if not isinstance(result, dict):
        return "Backend выполнил запрос, но вернул результат неизвестного формата."
    if command == "scan":
        return _scan_message(result)
    if command == "status":
        return _status_message(result)
    if command == "review":
        return _review_message(result)
    if command == "questions":
        return _questions_message(result)
    if command == "answer":
        return _answer_message(result)
    if command == "destinations":
        return _destinations_message(result)
    if command == "create-destination":
        return f"Storage destination created: {str(result.get('display_name') or 'folder')[:200]}."
    if command == "non-interview":
        return (
            f"Working-meeting recording processed; status: {_status_label(result.get('status'))}; "
            f"link: {result.get('safe_link') or 'unavailable'}."
        )
    if command == "route-interview":
        return (
            f"Interview recording processed; status: {_status_label(result.get('status'))}; "
            f"link: {result.get('safe_link') or 'unavailable'}."
        )
    if command == "cleanup-preview":
        return _cleanup_preview_message(result)
    if command == "cleanup-confirm":
        return _cleanup_confirm_message(result)
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
