"""Minimal async-wrapped IMAP client used only to locate one candidate's summary email.

`imaplib` is synchronous; every call is offloaded to a worker thread via `asyncio.to_thread`
so it never blocks the event loop (AGENTS.md: no blocking I/O in the async path). This module
is a thin, typed wrapper — no caching, no retries, no business logic. `app/services/
summary_email.py` owns the matching/retry policy.
"""

from __future__ import annotations

import asyncio
import email as email_lib
import imaplib
from dataclasses import dataclass
from datetime import UTC, datetime
from email.header import decode_header
from email.utils import parsedate_to_datetime

IMAP_SOCKET_TIMEOUT_SECONDS = 30
_MAX_MESSAGES_PER_SEARCH = 25


class MailIMAPError(RuntimeError):
    """Sanitized base error for IMAP integration failures.

    `transient` marks failures worth retrying on the next scheduled attempt (connection/
    network); a non-transient failure (bad credentials) still never fails the recording —
    callers treat every outcome of this module as best-effort.
    """

    def __init__(self, message: str = "", *, transient: bool = False) -> None:
        super().__init__(message)
        self.transient = transient


class MailIMAPConnectionError(MailIMAPError):
    pass


class MailIMAPAuthError(MailIMAPError):
    pass


class MailIMAPSearchError(MailIMAPError):
    pass


@dataclass(frozen=True)
class MailMessage:
    message_id: str
    subject: str
    sender: str
    received_at: datetime
    body: str


class MailIMAPClient:
    """One-shot IMAP INBOX search client; a new connection is opened per search call."""

    def __init__(self, host: str, port: int = 993) -> None:
        self._host = host
        self._port = port

    async def fetch_by_message_id(
        self, *, username: str, password: str, message_id: str, since: datetime
    ) -> MailMessage | None:
        """Re-fetch one already-found message's full body by its RFC822 `Message-Id`.

        Yandex's IMAP server rejects `HEADER "Message-ID" "..."` outright — even quoted, even
        without angle brackets — with `[UNAVAILABLE] SEARCH Backend error`, confirmed live
        against a real mailbox. `SINCE` search works fine, so this re-runs that (the same
        server-accepted criterion `search_inbox` uses) and matches the target message
        client-side by its already-parsed `Message-Id`, instead of asking the server to do it.
        """
        return await asyncio.to_thread(
            self._fetch_by_message_id_sync, username, password, message_id, since
        )

    def _fetch_by_message_id_sync(
        self, username: str, password: str, message_id: str, since: datetime
    ) -> MailMessage | None:
        try:
            connection = imaplib.IMAP4_SSL(
                self._host, self._port, timeout=IMAP_SOCKET_TIMEOUT_SECONDS
            )
        except (OSError, imaplib.IMAP4.error) as error:
            raise MailIMAPConnectionError("IMAP connection failed", transient=True) from error
        try:
            try:
                connection.login(username, password)
            except imaplib.IMAP4.error as error:
                raise MailIMAPAuthError("IMAP authentication failed") from error
            try:
                status, _ = connection.select("INBOX", readonly=True)
                if status != "OK":
                    raise MailIMAPSearchError("IMAP INBOX select failed")
                try:
                    status, data = connection.search(
                        None, "SINCE", since.astimezone(UTC).strftime("%d-%b-%Y")
                    )
                except imaplib.IMAP4.error as error:
                    raise MailIMAPSearchError("IMAP search failed") from error
                if status != "OK":
                    raise MailIMAPSearchError("IMAP search failed")
                ids = data[0].split() if data and data[0] else []
                for raw_id in reversed(ids[-_MAX_MESSAGES_PER_SEARCH:]):
                    message = self._fetch_message(connection, raw_id)
                    if message is not None and message.message_id == message_id:
                        return message
                return None
            finally:
                try:
                    connection.close()
                except imaplib.IMAP4.error:
                    pass
        finally:
            try:
                connection.logout()
            except (OSError, imaplib.IMAP4.error):
                pass

    async def search_inbox(
        self,
        *,
        username: str,
        password: str,
        since: datetime,
        from_contains: str | None = None,
        subject_contains: str | None = None,
    ) -> list[MailMessage]:
        return await asyncio.to_thread(
            self._search_inbox_sync,
            username,
            password,
            since,
            from_contains,
            subject_contains,
        )

    def _search_inbox_sync(
        self,
        username: str,
        password: str,
        since: datetime,
        from_contains: str | None,
        subject_contains: str | None,
    ) -> list[MailMessage]:
        try:
            connection = imaplib.IMAP4_SSL(
                self._host, self._port, timeout=IMAP_SOCKET_TIMEOUT_SECONDS
            )
        except (OSError, imaplib.IMAP4.error) as error:
            raise MailIMAPConnectionError("IMAP connection failed", transient=True) from error
        try:
            try:
                connection.login(username, password)
            except imaplib.IMAP4.error as error:
                raise MailIMAPAuthError("IMAP authentication failed") from error
            try:
                status, _ = connection.select("INBOX", readonly=True)
                if status != "OK":
                    raise MailIMAPSearchError("IMAP INBOX select failed")
                # IMAP SEARCH criteria are sent through imaplib's command encoder, which is
                # hardcoded to ASCII (imaplib.IMAP4._encoding) regardless of any CHARSET
                # argument — a non-ASCII criterion (a Cyrillic candidate name in
                # `subject_contains`) raises UnicodeEncodeError deep inside imaplib, not a
                # catchable imaplib.IMAP4.error. `from_contains` is an email address (ASCII) and
                # stays server-side; `subject_contains` is matched client-side below instead.
                criteria: list[str] = ["SINCE", since.astimezone(UTC).strftime("%d-%b-%Y")]
                if from_contains:
                    criteria += ["FROM", _imap_literal(from_contains)]
                try:
                    status, data = connection.search(None, *criteria)
                except (imaplib.IMAP4.error, UnicodeEncodeError) as error:
                    raise MailIMAPSearchError("IMAP search failed") from error
                if status != "OK":
                    raise MailIMAPSearchError("IMAP search failed")
                ids = data[0].split() if data and data[0] else []
                needle = subject_contains.casefold() if subject_contains else None
                messages: list[MailMessage] = []
                for raw_id in ids[-_MAX_MESSAGES_PER_SEARCH:]:
                    message = self._fetch_message(connection, raw_id)
                    if message is None:
                        continue
                    if needle is not None and needle not in message.subject.casefold():
                        continue
                    messages.append(message)
                return messages
            finally:
                try:
                    connection.close()
                except imaplib.IMAP4.error:
                    pass
        finally:
            try:
                connection.logout()
            except (OSError, imaplib.IMAP4.error):
                pass

    @staticmethod
    def _fetch_message(connection: imaplib.IMAP4_SSL, raw_id: bytes) -> MailMessage | None:
        try:
            status, data = connection.fetch(raw_id.decode(), "(RFC822)")
        except imaplib.IMAP4.error:
            return None
        if status != "OK" or not data or not isinstance(data[0], tuple):
            return None
        raw_bytes = data[0][1]
        if not isinstance(raw_bytes, bytes):
            return None
        parsed = email_lib.message_from_bytes(raw_bytes)
        message_id = str(parsed.get("Message-Id") or raw_id.decode(errors="replace"))
        subject = _decode_header_value(parsed.get("Subject"))
        sender = _decode_header_value(parsed.get("From"))
        received_at = _parse_date(parsed.get("Date"))
        body = _extract_body(parsed)
        return MailMessage(
            message_id=message_id,
            subject=subject,
            sender=sender,
            received_at=received_at,
            body=body,
        )


def _imap_literal(value: str) -> str:
    """Quote a search term; IMAP SEARCH strings forbid a bare double quote or backslash."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _decode_header_value(value: object) -> str:
    if not value:
        return ""
    try:
        parts = decode_header(str(value))
    except (UnicodeDecodeError, LookupError, ValueError):
        return str(value)
    decoded: list[str] = []
    for part, charset in parts:
        if isinstance(part, bytes):
            try:
                decoded.append(part.decode(charset or "utf-8", errors="replace"))
            except (LookupError, UnicodeDecodeError):
                decoded.append(part.decode("utf-8", errors="replace"))
        else:
            decoded.append(part)
    return "".join(decoded)


def _parse_date(value: object) -> datetime:
    if value:
        try:
            parsed = parsedate_to_datetime(str(value))
            if parsed is not None:
                return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
        except (TypeError, ValueError):
            pass
    return datetime.now(UTC)


def _extract_body(parsed: email_lib.message.Message) -> str:
    if parsed.is_multipart():
        for part in parsed.walk():
            if part.get_content_type() == "text/plain" and not part.get_filename():
                return _decode_payload(part)
        for part in parsed.walk():
            if part.get_content_type() == "text/html" and not part.get_filename():
                return _decode_payload(part)
        return ""
    return _decode_payload(parsed)


def _decode_payload(part: email_lib.message.Message) -> str:
    payload = part.get_payload(decode=True)
    if not isinstance(payload, bytes):
        return str(part.get_payload() or "")
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except (LookupError, UnicodeDecodeError):
        return payload.decode("utf-8", errors="replace")
