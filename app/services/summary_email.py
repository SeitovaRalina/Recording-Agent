"""Best-effort per-recruiter search for the candidate's general-interview summary email.

Deliberately not `InterviewMatcher`: that service matches a *recording* to a calendar event
and Notion candidate card and can block the pipeline with a manual review. This service only
locates one already-matched candidate's summary email; a miss or ambiguity never blocks
`completed` (see `app/scheduler/cron.py`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum

from app.config import Settings
from app.db.models.recording import Recording
from app.db.models.recruiter_config import RecruiterConfig
from app.tools.mail_imap import MailIMAPClient, MailIMAPError, MailMessage

_MAX_AMBIGUOUS_CANDIDATES = 10


class SummaryEmailOutcome(StrEnum):
    FOUND = "found"
    NOT_FOUND = "not_found"
    AMBIGUOUS = "ambiguous"
    # Permanent misconfiguration (missing/invalid app password) for this recruiter: retrying on
    # later ticks cannot help, so the caller gives up immediately instead of waiting out the
    # full deadline (acceptance criterion #6 — this only fails the search step, never the
    # recording).
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class SummaryEmailResult:
    outcome: SummaryEmailOutcome
    message: MailMessage | None = None
    candidates: tuple[MailMessage, ...] = field(default_factory=tuple)


class SummaryEmailService:
    """Search one recruiter's mailbox for one recording's candidate summary email."""

    def __init__(self, settings: Settings, client: MailIMAPClient | None = None) -> None:
        self._settings = settings
        self._client = client or MailIMAPClient(settings.summary_email_imap_host)

    async def find(self, recording: Recording, recruiter: RecruiterConfig) -> SummaryEmailResult:
        password = self._settings.yandex_mail_app_passwords.get(recruiter.email)
        if password is None or not password.get_secret_value():
            return SummaryEmailResult(SummaryEmailOutcome.UNAVAILABLE)
        since = recording.calendar_dtstart or recording.found_at
        try:
            messages = await self._client.search_inbox(
                username=recruiter.email,
                password=password.get_secret_value(),
                since=since,
                from_contains=recording.candidate_email,
                subject_contains=self._subject_hint(recording),
            )
        except MailIMAPError as error:
            # A transient (connection) failure is worth retrying later; a non-transient one
            # (bad/revoked app password) is a permanent misconfiguration for this recruiter.
            if error.transient:
                return SummaryEmailResult(SummaryEmailOutcome.NOT_FOUND)
            return SummaryEmailResult(SummaryEmailOutcome.UNAVAILABLE)
        if not messages:
            return SummaryEmailResult(SummaryEmailOutcome.NOT_FOUND)
        if len(messages) > 1:
            return SummaryEmailResult(
                SummaryEmailOutcome.AMBIGUOUS,
                candidates=tuple(messages[:_MAX_AMBIGUOUS_CANDIDATES]),
            )
        return SummaryEmailResult(SummaryEmailOutcome.FOUND, message=messages[0])

    async def fetch_found_message(
        self, recording: Recording, recruiter: RecruiterConfig
    ) -> MailMessage | None:
        """Re-fetch the full body of an already-found message for `GET summary-source`.

        Only the lightweight identity (`summary_email_message_id`) is persisted on `Recording`;
        the body is re-read live so it is never stored at rest.
        """
        message_id = recording.summary_email_message_id
        if not message_id:
            return None
        password = self._settings.yandex_mail_app_passwords.get(recruiter.email)
        if password is None or not password.get_secret_value():
            return None
        since = (
            recording.summary_email_received_at
            or recording.calendar_dtstart
            or recording.found_at
        )
        try:
            return await self._client.fetch_by_message_id(
                username=recruiter.email,
                password=password.get_secret_value(),
                message_id=message_id,
                since=since - timedelta(days=1),
            )
        except MailIMAPError:
            return None

    @staticmethod
    def _subject_hint(recording: Recording) -> str | None:
        name = recording.candidate_name
        return name.strip() if isinstance(name, str) and name.strip() else None


def search_deadline_exceeded(recording: Recording, *, now: datetime) -> bool:
    deadline = recording.summary_email_search_deadline_at
    if deadline is None:
        return True
    if deadline.tzinfo is None:
        from datetime import UTC

        deadline = deadline.replace(tzinfo=UTC)
    return now >= deadline
