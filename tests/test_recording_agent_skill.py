from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest


def _load_client() -> ModuleType:
    path = (
        Path(__file__).parents[1]
        / "openclaw"
        / "skills"
        / "recording-agent"
        / "scripts"
        / "recording_agent.py"
    )
    spec = importlib.util.spec_from_file_location("recording_agent_skill_client", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


CLIENT = _load_client()


def test_status_uses_trusted_recruiter_identity_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RECORDING_AGENT_RECRUITER_USER_ID", "trusted-user-id")

    args = CLIENT._parser().parse_args(["status", "--date", "2026-07-21"])

    assert args.recruiter_user_id == "trusted-user-id"


def test_conflicting_explicit_recruiter_identity_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RECORDING_AGENT_RECRUITER_USER_ID", "environment-user-id")

    with pytest.raises(CLIENT.ClientError, match="trusted recruiter identity"):
        CLIENT._parser().parse_args(["status", "--recruiter-user-id", "metadata-user-id"])


def test_scan_uses_trusted_recruiter_email_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RECORDING_AGENT_RECRUITER_EMAIL", "trusted@example.com")
    captured: dict[str, object] = {}

    def request(method: str, path: str, **kwargs: object) -> dict[str, object]:
        captured.update(method=method, path=path, **kwargs)
        return {}

    monkeypatch.setattr(CLIENT, "_request", request)

    args = CLIENT._parser().parse_args(["scan", "--idempotency-key", "scan-0001"])
    CLIENT._execute(args)

    assert args.recruiter_email == "trusted@example.com"
    assert captured["body"] == {
        "recruiter_email": "trusted@example.com",
        "scope": "test",
        "idempotency_key": "scan-0001",
    }


def test_scan_rejects_conflicting_explicit_recruiter_email(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RECORDING_AGENT_RECRUITER_EMAIL", "trusted@example.com")

    with pytest.raises(CLIENT.ClientError, match="trusted recruiter email"):
        CLIENT._parser().parse_args(
            [
                "scan",
                "--recruiter-email",
                "attacker@example.com",
                "--idempotency-key",
                "scan-0001",
            ]
        )


def test_scan_accepts_explicit_recruiter_email_without_trusted_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("RECORDING_AGENT_RECRUITER_EMAIL", raising=False)

    args = CLIENT._parser().parse_args(
        [
            "scan",
            "--recruiter-email",
            "local-codex@example.com",
            "--idempotency-key",
            "scan-0001",
        ]
    )

    assert args.recruiter_email == "local-codex@example.com"


def test_scan_message_reports_counts_and_every_category() -> None:
    message = CLIENT._message_for(
        "scan",
        {
            "discovered": 9,
            "inserted": 3,
            "skipped_legacy": 6,
            "processed": 3,
            "manual_review": 1,
            "without_review": 1,
            "failed_recordings": 1,
            "failed": 3,
            "items": [
                {
                    "id": "review-id",
                    "filename": "review.webm",
                    "status": "manual_review_required",
                    "is_new": True,
                    "requires_review": True,
                    "review_reason": "no_candidate_found",
                    "generated_filename": "stored-interview.webm",
                },
                {
                    "id": "complete-id",
                    "filename": "complete.webm",
                    "candidate_name": "Иван Иванов",
                    "status": "completed",
                    "is_new": True,
                    "requires_review": False,
                    "generated_filename": "stored-complete.webm",
                    "safe_link": "https://storage.test/complete",
                },
                {
                    "id": "failed-id",
                    "filename": "failed.webm",
                    "status": "failed",
                    "is_new": True,
                    "requires_review": False,
                    "error": "Notion query failed",
                },
            ],
        },
    )

    assert "Новых записей добавлено: 3." in message
    assert "Старых записей пропущено по правилу canary: 6." in message
    assert "Требуют review: 1." in message
    assert "Не требуют review: 1." in message
    assert "С ошибкой: 1." in message
    assert "review.webm" in message
    assert "complete.webm" in message
    assert "имя в хранилище: stored-complete.webm" in message
    assert "failed.webm" in message
    assert "Дополнительных ошибок текущего запуска: 2." in message
    assert "новых записей не обнаружено" not in message.casefold()


def test_empty_scan_message_is_explicit_without_claiming_disk_is_empty() -> None:
    message = CLIENT._message_for(
        "scan",
        {
            "discovered": 7,
            "inserted": 0,
            "skipped_legacy": 7,
            "failed": 0,
            "items": [],
        },
    )

    assert "Новых записей добавлено: 0." in message
    assert "Обнаружено файлов для проверки: 7." in message
    assert "Старых записей пропущено по правилу canary: 7." in message


def test_scan_message_explains_truncation_without_double_counting_failures() -> None:
    message = CLIENT._message_for(
        "scan",
        {
            "discovered": 51,
            "inserted": 51,
            "processed": 51,
            "manual_review": 0,
            "without_review": 50,
            "failed_recordings": 1,
            "failed": 1,
            "items_truncated": True,
            "items": [
                {
                    "id": "failed-id",
                    "filename": "failed.webm",
                    "status": "failed",
                    "requires_review": False,
                }
            ],
        },
    )

    assert "Показано результатов: 1 из 51." in message
    assert "сузьте status-запрос по дате, кандидату, recording ID или статусу" in message
    assert "Полный список доступен через status" not in message
    assert "Дополнительных ошибок" not in message


def test_status_message_lists_identity_status_and_error() -> None:
    message = CLIENT._message_for(
        "status",
        {
            "items": [
                {
                    "id": "recording-id",
                    "filename": "interview.webm",
                    "candidate_name": "Иван Иванов",
                    "status": "manual_review_required",
                    "requires_review": True,
                    "review_reason": "no_candidate_found",
                    "generated_filename": "stored-interview.webm",
                }
            ]
        },
    )

    assert "Найдено записей: 1." in message
    assert "interview.webm" in message
    assert "Иван Иванов" in message
    assert "кандидат с нужным именем и датой не найден в Notion" in message
    assert "имя в хранилище: stored-interview.webm" in message


def test_review_message_lists_only_returned_choices() -> None:
    message = CLIENT._message_for(
        "review",
        {
            "recording_id": "recording-id",
            "filename": "ambiguous.webm",
            "reason": "multiple_candidates",
            "choices": [
                {"name": "Иван Иванов", "project_or_spot": "Spot", "url": "https://notion/1"},
                {"name": "Иван Петров", "url": "https://notion/2"},
            ],
        },
    )

    assert "1. Иван Иванов — 📍 Spots: Spot — https://notion/1" in message
    assert "2. Иван Петров — https://notion/2" in message
    assert "Ответьте номером" in message


def test_mutation_and_error_messages_are_actionable() -> None:
    resolved = CLIENT._message_for(
        "resolve",
        {
            "recording_id": "recording-id",
            "status": "completed",
            "replayed": True,
        },
    )

    assert "Выбор принят" in resolved
    assert "обработка завершена" in resolved
    assert "не создал дополнительную обработку" in resolved
    assert "авторизацию" in CLIENT._error_message(
        "Backend rejected request (HTTP 403): request failed"
    )
    assert "Срок действия review истёк" in CLIENT._error_message(
        "Backend rejected request (HTTP 410): expired"
    )
