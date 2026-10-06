"""Unit tests for app.tools.mail_imap — always against a mocked imaplib, never a real IMAP
connection (AGENTS.md / meeting-summary plan test requirements)."""

from __future__ import annotations

import imaplib
from datetime import UTC, datetime
from email.message import EmailMessage
from typing import Any

import pytest

from app.tools.mail_imap import (
    MailIMAPAuthError,
    MailIMAPClient,
    MailIMAPConnectionError,
    MailIMAPSearchError,
)


def _raw_message(message_id: str, subject: str, sender: str, body: str = "Hello") -> bytes:
    message = EmailMessage()
    message["Message-Id"] = message_id
    message["Subject"] = subject
    message["From"] = sender
    message["Date"] = "Tue, 06 Oct 2026 10:00:00 +0000"
    message.set_content(body)
    return message.as_bytes()


class FakeIMAP4SSL:
    """Minimal stand-in for imaplib.IMAP4_SSL covering only what MailIMAPClient calls."""

    instances: list[FakeIMAP4SSL] = []

    def __init__(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        *,
        login_error: bool = False,
        search_ids: tuple[bytes, ...] = (),
        messages: dict[bytes, bytes] | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.login_error = login_error
        self.search_ids = search_ids
        self.messages = messages or {}
        self.logged_in = False
        self.closed = False
        self.logged_out = False
        self.received_criteria: tuple[str, ...] = ()
        FakeIMAP4SSL.instances.append(self)

    def login(self, username: str, password: str) -> None:
        if self.login_error:
            raise imaplib.IMAP4.error("auth failed")
        self.logged_in = True

    def select(self, mailbox: str, readonly: bool = False) -> tuple[str, list[bytes]]:
        return "OK", [b"1"]

    def search(self, charset: str | None, *criteria: str) -> tuple[str, list[bytes]]:
        self.received_criteria = criteria
        return "OK", [b" ".join(self.search_ids)]

    def fetch(self, message_id: str | bytes, parts: str) -> tuple[str, list[Any]]:
        key = message_id.encode() if isinstance(message_id, str) else message_id
        raw = self.messages.get(key)
        if raw is None:
            return "NO", [None]
        return "OK", [(key, raw)]

    def close(self) -> None:
        self.closed = True

    def logout(self) -> None:
        self.logged_out = True


@pytest.fixture(autouse=True)
def _reset_instances() -> None:
    FakeIMAP4SSL.instances.clear()


@pytest.mark.anyio
async def test_search_inbox_returns_parsed_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = _raw_message("<msg-1@mail>", "Interview summary", "Candidate <c@example.com>")

    def factory(host: str, port: int, timeout: float | None = None) -> FakeIMAP4SSL:
        return FakeIMAP4SSL(host, port, timeout, search_ids=(b"1",), messages={b"1": raw})

    monkeypatch.setattr("app.tools.mail_imap.imaplib.IMAP4_SSL", factory)

    client = MailIMAPClient("imap.example.test")
    messages = await client.search_inbox(
        username="r@example.com", password="x", since=datetime.now(UTC)
    )

    assert len(messages) == 1
    assert messages[0].message_id == "<msg-1@mail>"
    assert messages[0].subject == "Interview summary"
    assert "Candidate" in messages[0].sender
    assert "Hello" in messages[0].body


@pytest.mark.anyio
async def test_search_inbox_returns_empty_list_when_no_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def factory(host: str, port: int, timeout: float | None = None) -> FakeIMAP4SSL:
        return FakeIMAP4SSL(host, port, timeout, search_ids=())

    monkeypatch.setattr("app.tools.mail_imap.imaplib.IMAP4_SSL", factory)

    client = MailIMAPClient("imap.example.test")
    messages = await client.search_inbox(
        username="r@example.com", password="x", since=datetime.now(UTC)
    )

    assert messages == []


@pytest.mark.anyio
async def test_search_inbox_filters_by_body_contains_client_side(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """body_contains (the exact Telemost call link to match) is never sent to IMAP SEARCH —
    only FROM/SINCE are (see test_search_inbox_only_sends_ascii_criteria) — it is matched
    against each fetched candidate's body in Python, so it is also safe for Cyrillic content."""
    matching = _raw_message(
        "<msg-1@mail>", "Конспект встречи «Собеседование»", "keeper@telemost.yandex.ru",
        body="Ссылка на встречу: https://telemost.360.yandex.ru/j/9589671710\n\nКонспект...",
    )
    other = _raw_message(
        "<msg-2@mail>", "Конспект встречи «Другая встреча»", "keeper@telemost.yandex.ru",
        body="Ссылка на встречу: https://telemost.360.yandex.ru/j/0000000000\n\nДругое",
    )

    def factory(host: str, port: int, timeout: float | None = None) -> FakeIMAP4SSL:
        return FakeIMAP4SSL(
            host,
            port,
            timeout,
            search_ids=(b"1", b"2"),
            messages={b"1": matching, b"2": other},
        )

    monkeypatch.setattr("app.tools.mail_imap.imaplib.IMAP4_SSL", factory)

    client = MailIMAPClient("imap.example.test")
    messages = await client.search_inbox(
        username="r@example.com",
        password="x",
        since=datetime.now(UTC),
        from_contains="keeper@telemost.yandex.ru",
        body_contains="https://telemost.360.yandex.ru/j/9589671710",
    )

    assert len(messages) == 1
    assert messages[0].message_id == "<msg-1@mail>"
    criteria = FakeIMAP4SSL.instances[0].received_criteria
    assert all(part.isascii() for part in criteria), (
        f"non-ASCII criterion would crash real imaplib: {criteria!r}"
    )
    assert criteria == ("SINCE", since_date(), "FROM", '"keeper@telemost.yandex.ru"')


def since_date() -> str:
    return datetime.now(UTC).strftime("%d-%b-%Y")


@pytest.mark.anyio
async def test_html_only_body_is_stripped_to_plain_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: Telemost's "Хранитель встреч" sends the real summary as an inline
    multipart/related text/html body (styled, with an embedded base64 image) plus a separate
    text/plain ATTACHMENT (the full call transcript, filename set) that the user explicitly
    does not want read. _extract_body must skip the filenamed attachment, fall through to the
    inline HTML, and strip it down to plain text — not return raw markup."""
    message = EmailMessage()
    message["Message-Id"] = "<html-only@mail>"
    message["Subject"] = "Конспект встречи «Воркшоп»"
    message["From"] = "keeper@telemost.yandex.ru"
    message["Date"] = "Tue, 06 Oct 2026 10:00:00 +0000"
    message.make_mixed()
    related = EmailMessage()
    related.make_related()
    html_part = EmailMessage()
    html_part.set_content(
        "<body><style>.x{color:red}</style>"
        "<p>Ссылка на встречу: https://telemost.360.yandex.ru/j/123 &amp; детали</p>"
        '<img src="data:image/png;base64,AAAA"></body>',
        subtype="html",
    )
    related.attach(html_part)
    message.attach(related)
    attachment = EmailMessage()
    attachment.set_content("full transcript, not to be read")
    attachment.add_header(
        "Content-Disposition", "attachment", filename="2026-10-06 транскрипт.txt"
    )
    message.attach(attachment)
    raw = message.as_bytes()

    def factory(host: str, port: int, timeout: float | None = None) -> FakeIMAP4SSL:
        return FakeIMAP4SSL(host, port, timeout, search_ids=(b"1",), messages={b"1": raw})

    monkeypatch.setattr("app.tools.mail_imap.imaplib.IMAP4_SSL", factory)

    client = MailIMAPClient("imap.example.test")
    messages = await client.search_inbox(
        username="r@example.com", password="x", since=datetime.now(UTC)
    )

    assert len(messages) == 1
    body = messages[0].body
    assert "https://telemost.360.yandex.ru/j/123" in body
    assert "&" in body and "&amp;" not in body
    assert "<" not in body and "data:image" not in body
    assert "full transcript" not in body


@pytest.mark.anyio
async def test_search_inbox_raises_auth_error_on_bad_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def factory(host: str, port: int, timeout: float | None = None) -> FakeIMAP4SSL:
        return FakeIMAP4SSL(host, port, timeout, login_error=True)

    monkeypatch.setattr("app.tools.mail_imap.imaplib.IMAP4_SSL", factory)

    client = MailIMAPClient("imap.example.test")
    with pytest.raises(MailIMAPAuthError) as excinfo:
        await client.search_inbox(username="r@example.com", password="bad", since=datetime.now(UTC))
    assert excinfo.value.transient is False


@pytest.mark.anyio
async def test_search_inbox_raises_connection_error_when_connect_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def factory(host: str, port: int, timeout: float | None = None) -> FakeIMAP4SSL:
        raise OSError("network unreachable")

    monkeypatch.setattr("app.tools.mail_imap.imaplib.IMAP4_SSL", factory)

    client = MailIMAPClient("imap.example.test")
    with pytest.raises(MailIMAPConnectionError) as excinfo:
        await client.search_inbox(username="r@example.com", password="x", since=datetime.now(UTC))
    assert excinfo.value.transient is True


@pytest.mark.anyio
async def test_fetch_by_message_id_returns_none_when_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def factory(host: str, port: int, timeout: float | None = None) -> FakeIMAP4SSL:
        return FakeIMAP4SSL(host, port, timeout, search_ids=())

    monkeypatch.setattr("app.tools.mail_imap.imaplib.IMAP4_SSL", factory)

    client = MailIMAPClient("imap.example.test")
    message = await client.fetch_by_message_id(
        username="r@example.com",
        password="x",
        message_id="<missing@mail>",
        since=datetime.now(UTC),
    )

    assert message is None


@pytest.mark.anyio
async def test_fetch_by_message_id_returns_the_full_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = _raw_message("<msg-2@mail>", "Re: Interview", "HR <hr@example.com>", body="Body text")

    def factory(host: str, port: int, timeout: float | None = None) -> FakeIMAP4SSL:
        return FakeIMAP4SSL(host, port, timeout, search_ids=(b"5",), messages={b"5": raw})

    monkeypatch.setattr("app.tools.mail_imap.imaplib.IMAP4_SSL", factory)

    client = MailIMAPClient("imap.example.test")
    message = await client.fetch_by_message_id(
        username="r@example.com",
        password="x",
        message_id="<msg-2@mail>",
        since=datetime.now(UTC),
    )

    assert message is not None
    assert message.subject == "Re: Interview"
    assert "Body text" in message.body


@pytest.mark.anyio
async def test_fetch_by_message_id_never_sends_header_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: Yandex's IMAP server rejects HEADER "Message-ID" "..." outright with
    [UNAVAILABLE] SEARCH Backend error, confirmed live. fetch_by_message_id must use SINCE
    (server-accepted) and match the target message client-side instead."""
    raw = _raw_message("<msg-3@mail>", "Re: Interview", "HR <hr@example.com>")
    other = _raw_message("<msg-other@mail>", "Unrelated", "HR <hr@example.com>")

    def factory(host: str, port: int, timeout: float | None = None) -> FakeIMAP4SSL:
        return FakeIMAP4SSL(
            host, port, timeout, search_ids=(b"1", b"2"), messages={b"1": other, b"2": raw}
        )

    monkeypatch.setattr("app.tools.mail_imap.imaplib.IMAP4_SSL", factory)

    client = MailIMAPClient("imap.example.test")
    message = await client.fetch_by_message_id(
        username="r@example.com",
        password="x",
        message_id="<msg-3@mail>",
        since=datetime.now(UTC),
    )

    assert message is not None
    assert message.message_id == "<msg-3@mail>"
    criteria = FakeIMAP4SSL.instances[0].received_criteria
    assert "HEADER" not in criteria
    assert criteria[0] == "SINCE"


def test_search_raises_search_error_on_imap_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    class BrokenSearch(FakeIMAP4SSL):
        def search(self, charset: str | None, *criteria: str) -> tuple[str, list[bytes]]:
            raise imaplib.IMAP4.error("search failed")

    def factory(host: str, port: int, timeout: float | None = None) -> FakeIMAP4SSL:
        return BrokenSearch(host, port, timeout)

    monkeypatch.setattr("app.tools.mail_imap.imaplib.IMAP4_SSL", factory)

    client = MailIMAPClient("imap.example.test")
    with pytest.raises(MailIMAPSearchError):
        client._search_inbox_sync("r@example.com", "secret", datetime.now(UTC), None, None)
