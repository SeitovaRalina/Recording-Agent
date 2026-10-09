"""Unit tests for app.services.summary_email, against a fake MailIMAPClient (never real IMAP)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import SecretStr

from app.config import Settings
from app.db.models.recording import Recording
from app.db.models.recruiter_config import RecruiterConfig
from app.services.summary_email import (
    SummaryEmailOutcome,
    SummaryEmailService,
    search_deadline_exceeded,
)
from app.tools.mail_imap import MailIMAPAuthError, MailIMAPConnectionError, MailMessage


def _recording(
    *,
    telemost_url: str | None = "https://telemost.360.yandex.ru/j/9589671710",
    calendar_dtstart: datetime | None = None,
) -> Recording:
    return Recording(
        disk_file_id="rec-1",
        disk_path="disk:/rec-1.webm",
        disk_filename="rec-1.webm",
        disk_owner_email="r@example.com",
        candidate_name="Ivan Ivanov",
        candidate_email="ivan@candidate.test",
        calendar_telemost_url=telemost_url,
        calendar_dtstart=calendar_dtstart,
        found_at=datetime(2026, 10, 1, tzinfo=UTC),
    )


def _recruiter() -> RecruiterConfig:
    return RecruiterConfig(
        email="r@example.com", notion_database_id="db", synology_base_folder="root"
    )


def _settings(**overrides: object) -> Settings:
    return Settings(
        yandex_mail_app_passwords={"r@example.com": SecretStr("app-password")}, **overrides
    )


class FakeClient:
    def __init__(self, messages: list[MailMessage] | Exception) -> None:
        self._messages = messages

    async def search_inbox(self, **kwargs: object) -> list[MailMessage]:
        if isinstance(self._messages, Exception):
            raise self._messages
        return self._messages

    async def fetch_by_message_id(self, **kwargs: object) -> MailMessage | None:
        if isinstance(self._messages, Exception):
            raise self._messages
        return self._messages[0] if self._messages else None


def _message(message_id: str = "<a@mail>") -> MailMessage:
    return MailMessage(
        message_id=message_id,
        subject="Interview summary",
        sender="hr@example.com",
        received_at=datetime(2026, 10, 2, tzinfo=UTC),
        body="Candidate did well.",
    )


@pytest.mark.anyio
async def test_find_returns_found_for_exactly_one_match() -> None:
    service = SummaryEmailService(_settings(), client=FakeClient([_message()]))

    result = await service.find(_recording(), _recruiter())

    assert result.outcome == SummaryEmailOutcome.FOUND
    assert result.message is not None
    assert result.message.message_id == "<a@mail>"


@pytest.mark.anyio
async def test_find_returns_not_found_when_no_messages() -> None:
    service = SummaryEmailService(_settings(), client=FakeClient([]))

    result = await service.find(_recording(), _recruiter())

    assert result.outcome == SummaryEmailOutcome.NOT_FOUND


@pytest.mark.anyio
async def test_find_returns_ambiguous_for_multiple_matches() -> None:
    messages = [_message("<a@mail>"), _message("<b@mail>")]
    service = SummaryEmailService(_settings(), client=FakeClient(messages))

    result = await service.find(_recording(), _recruiter())

    assert result.outcome == SummaryEmailOutcome.AMBIGUOUS
    assert len(result.candidates) == 2


@pytest.mark.anyio
async def test_find_disambiguates_same_link_candidates_by_start_time() -> None:
    """Regression: found live against Lilia's real calendar — a recruiter can have one
    *permanent* personal Telemost room, so several different real interviews all carry the
    identical calendar_telemost_url, and an exact-link search legitimately returns more than
    one candidate email. The one candidate whose own "Конспектирование началось" timestamp
    actually lines up with this recording's scheduled start must be picked instead of just
    escalating every time."""
    other_interview = MailMessage(
        message_id="<other@mail>",
        subject="Interview summary",
        sender="hr@example.com",
        received_at=datetime(2026, 10, 7, tzinfo=UTC),
        body="Конспектирование началось 07.10.2026 в 08:00 (MSK)\n\nДругое собеседование.",
    )
    this_interview = MailMessage(
        message_id="<this@mail>",
        subject="Interview summary",
        sender="hr@example.com",
        received_at=datetime(2026, 10, 7, tzinfo=UTC),
        body="Конспектирование началось 07.10.2026 в 11:02 (MSK)\n\nЭто собеседование.",
    )
    service = SummaryEmailService(
        _settings(), client=FakeClient([other_interview, this_interview])
    )
    recording = _recording(
        calendar_dtstart=datetime(2026, 10, 7, 8, 0, tzinfo=UTC)  # 11:00 MSK
    )

    result = await service.find(recording, _recruiter())

    assert result.outcome == SummaryEmailOutcome.FOUND
    assert result.message is not None
    assert result.message.message_id == "<this@mail>"


@pytest.mark.anyio
async def test_find_stays_ambiguous_when_two_candidates_match_the_start_window() -> None:
    close_a = MailMessage(
        message_id="<a@mail>",
        subject="s",
        sender="hr@example.com",
        received_at=datetime(2026, 10, 7, tzinfo=UTC),
        body="Конспектирование началось 07.10.2026 в 10:55 (MSK)",
    )
    close_b = MailMessage(
        message_id="<b@mail>",
        subject="s",
        sender="hr@example.com",
        received_at=datetime(2026, 10, 7, tzinfo=UTC),
        body="Конспектирование началось 07.10.2026 в 11:05 (MSK)",
    )
    service = SummaryEmailService(_settings(), client=FakeClient([close_a, close_b]))
    recording = _recording(calendar_dtstart=datetime(2026, 10, 7, 8, 0, tzinfo=UTC))

    result = await service.find(recording, _recruiter())

    assert result.outcome == SummaryEmailOutcome.AMBIGUOUS
    assert len(result.candidates) == 2


@pytest.mark.anyio
async def test_find_returns_unavailable_when_password_is_missing() -> None:
    service = SummaryEmailService(Settings(), client=FakeClient([_message()]))

    result = await service.find(_recording(), _recruiter())

    assert result.outcome == SummaryEmailOutcome.UNAVAILABLE


@pytest.mark.anyio
async def test_find_returns_unavailable_when_no_telemost_url_was_parsed() -> None:
    """Regression: matching is by the exact Telemost call link in the email body against
    Recording.calendar_telemost_url (found live — the real "Хранитель встреч" email's Subject
    is the meeting's own title, not the candidate name, so subject/candidate-name matching was
    wrong). With no link ever parsed from the calendar event, there is no reliable key at all —
    this is permanent, not a reason to keep retrying."""
    service = SummaryEmailService(_settings(), client=FakeClient([_message()]))

    result = await service.find(_recording(telemost_url=None), _recruiter())

    assert result.outcome == SummaryEmailOutcome.UNAVAILABLE


@pytest.mark.anyio
async def test_find_searches_by_telemost_keeper_sender_and_call_link() -> None:
    captured: dict[str, object] = {}

    class CapturingClient(FakeClient):
        async def search_inbox(self, **kwargs: object) -> list[MailMessage]:
            captured.update(kwargs)
            return await super().search_inbox(**kwargs)

    service = SummaryEmailService(_settings(), client=CapturingClient([_message()]))

    await service.find(_recording(), _recruiter())

    assert captured["from_contains"] == "keeper@telemost.yandex.ru"
    assert captured["body_contains"] == "https://telemost.360.yandex.ru/j/9589671710"


@pytest.mark.anyio
async def test_find_returns_unavailable_on_non_transient_imap_error() -> None:
    service = SummaryEmailService(_settings(), client=FakeClient(MailIMAPAuthError("bad password")))

    result = await service.find(_recording(), _recruiter())

    assert result.outcome == SummaryEmailOutcome.UNAVAILABLE


@pytest.mark.anyio
async def test_find_returns_not_found_on_transient_imap_error() -> None:
    service = SummaryEmailService(
        _settings(), client=FakeClient(MailIMAPConnectionError("timeout", transient=True))
    )

    result = await service.find(_recording(), _recruiter())

    assert result.outcome == SummaryEmailOutcome.NOT_FOUND


@pytest.mark.anyio
async def test_fetch_found_message_returns_none_without_message_id() -> None:
    service = SummaryEmailService(_settings(), client=FakeClient([_message()]))

    message = await service.fetch_found_message(_recording(), _recruiter())

    assert message is None


@pytest.mark.anyio
async def test_fetch_found_message_returns_body_once_message_id_is_known() -> None:
    recording = _recording()
    recording.summary_email_message_id = "<a@mail>"
    service = SummaryEmailService(_settings(), client=FakeClient([_message()]))

    message = await service.fetch_found_message(recording, _recruiter())

    assert message is not None
    assert message.body == "Candidate did well."


def test_search_deadline_exceeded_true_when_missing() -> None:
    recording = _recording()
    assert search_deadline_exceeded(recording, now=datetime.now(UTC)) is True


def test_search_deadline_exceeded_false_before_deadline() -> None:
    recording = _recording()
    recording.summary_email_search_deadline_at = datetime(2026, 12, 31, tzinfo=UTC)
    assert search_deadline_exceeded(recording, now=datetime(2026, 10, 1, tzinfo=UTC)) is False


def test_search_deadline_exceeded_true_after_deadline() -> None:
    recording = _recording()
    recording.summary_email_search_deadline_at = datetime(2026, 1, 1, tzinfo=UTC)
    assert search_deadline_exceeded(recording, now=datetime(2026, 10, 1, tzinfo=UTC)) is True
