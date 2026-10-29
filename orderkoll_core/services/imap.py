# Copyright 2026 Maamoon Mara
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
"""IMAP fetch of new purchase-order mails (week-1 intake; the mail alias comes later).

Messages are read read-only and tracked by UID, so nothing in the mailbox is
marked or moved and a crash never loses a mail: the inbox only advances its
``last_uid`` after the documents are stored.
"""

from __future__ import annotations

import email
import email.policy
import imaplib
import logging
import ssl as ssl_module
from dataclasses import dataclass, field
from datetime import datetime
from email.utils import parseaddr, parsedate_to_datetime

_logger = logging.getLogger(__name__)


@dataclass
class Attachment:
    name: str
    data: bytes
    mimetype: str


@dataclass
class FetchedMail:
    uid: int
    message_id: str
    sender_email: str
    sender_name: str
    subject: str
    date: datetime | None
    body_text: str
    body_html: str
    attachments: list[Attachment] = field(default_factory=list)


class ImapError(Exception):
    """The server refused a step (bad folder, failed login…); message is user-readable."""


@dataclass
class FetchResult:
    mails: list[FetchedMail]
    client: object
    uidvalidity: int | None
    max_uid: int  # highest UID this run consumed (fetched or skipped); 0 when none
    mailbox_max_uid: int  # highest UID present in the folder, even if not consumed
    skipped: list[tuple[int, int]] = field(default_factory=list)  # (uid, size) over max_bytes


def _text_of(part) -> str:
    """Decoded text even when the charset is unknown or wrong (then utf-8 with replacement)."""
    try:
        return part.get_content()
    except (LookupError, UnicodeDecodeError, TypeError, ValueError):
        payload = part.get_payload(decode=True) or b""
        return payload.decode("utf-8", errors="replace")


def parse_message(raw: bytes, uid: int) -> FetchedMail:
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    name, addr = parseaddr(str(msg.get("From", "")))
    date = None
    if msg.get("Date"):
        try:
            date = parsedate_to_datetime(str(msg["Date"]))
        except (TypeError, ValueError):
            date = None
    body_text, body_html, attachments = "", "", []
    for part in msg.walk():
        if part.is_multipart():
            continue
        ctype = part.get_content_type()
        filename = part.get_filename()
        if filename or part.get_content_disposition() == "attachment":
            attachments.append(
                Attachment(filename or "attachment", part.get_payload(decode=True) or b"", ctype)
            )
        elif ctype == "text/plain" and not body_text:
            body_text = _text_of(part)
        elif ctype == "text/html" and not body_html:
            body_html = _text_of(part)
    return FetchedMail(
        uid=uid,
        message_id=(str(msg.get("Message-ID") or "")).strip(),
        sender_email=addr.lower(),
        sender_name=name.strip(),
        subject=str(msg.get("Subject") or "").strip(),
        date=date,
        body_text=body_text,
        body_html=body_html,
        attachments=attachments,
    )


def fetch_new(
    host: str,
    port: int,
    user: str,
    password: str,
    ssl: bool = True,
    folder: str = "INBOX",
    last_uid: int = 0,
    limit: int = 50,
    max_bytes: int = 25 * 1024 * 1024,
    client_factory=None,
) -> FetchResult:
    """Fetch UIDs above ``last_uid``, oldest first, at most ``limit``.

    Sizes are checked with RFC822.SIZE before any download: mails over
    ``max_bytes`` are skipped (listed in ``skipped``) but still consumed, so a
    huge mail never blocks the ones after it. ``limit=0`` fetches nothing and
    only reports the mailbox state (used to start a new inbox at "now").
    ``client_factory(host, port)`` lets tests inject a fake IMAP4 object.
    """
    context = ssl_module.create_default_context()  # verifies the server certificate
    if client_factory:
        client = client_factory(host, port)
    elif ssl:
        client = imaplib.IMAP4_SSL(host, port, ssl_context=context)
    else:
        client = imaplib.IMAP4(host, port)
        client.starttls(context)  # never send credentials in clear text
    mails: list[FetchedMail] = []
    skipped: list[tuple[int, int]] = []
    max_uid = 0
    try:
        typ, data = client.login(user, password)
        if typ != "OK":
            raise ImapError(f"login refused for {user}: {_msg(data)}")
        typ, data = client.select(folder, readonly=True)
        if typ != "OK":
            raise ImapError(f"folder {folder!r} cannot be opened: {_msg(data)}")
        uidvalidity = _int_or_none(client.response("UIDVALIDITY")[1])
        typ, data = client.uid("SEARCH", None, "ALL")
        if typ != "OK":
            raise ImapError(f"search failed: {_msg(data)}")
        all_uids = sorted(int(u) for u in (data[0] or b"").split())
        mailbox_max_uid = all_uids[-1] if all_uids else 0
        for uid in [u for u in all_uids if u > last_uid][:limit]:
            size = _size_of(client, uid)
            max_uid = uid
            if size is not None and size > max_bytes:
                skipped.append((uid, size))
                _logger.warning("IMAP uid %s is %d bytes, over the cap; skipped", uid, size)
                continue
            typ, data = client.uid("FETCH", str(uid), "(RFC822)")
            raw = next((item[1] for item in data if isinstance(item, tuple)), b"")
            if typ != "OK" or not raw:
                _logger.info("IMAP uid %s vanished between search and fetch; skipped", uid)
                continue
            mails.append(parse_message(raw, uid))
    finally:
        try:
            client.logout()
        except Exception as exc:  # noqa: BLE001 - a failed logout changes nothing
            _logger.debug("IMAP logout failed: %s", exc)
    return FetchResult(
        mails=mails,
        client=client,
        uidvalidity=uidvalidity,
        max_uid=max_uid,
        mailbox_max_uid=mailbox_max_uid,
        skipped=skipped,
    )


def _msg(data) -> str:
    try:
        return (data[0] or b"").decode("utf-8", "replace") if data else ""
    except Exception:  # noqa: BLE001 - diagnostics only
        return str(data)


def _int_or_none(values):
    try:
        return int(values[0]) if values and values[0] is not None else None
    except (TypeError, ValueError):
        return None


def _size_of(client, uid: int) -> int | None:
    typ, data = client.uid("FETCH", str(uid), "(RFC822.SIZE)")
    if typ != "OK":
        return None
    for item in data:
        text = item[0] if isinstance(item, tuple) else item
        if isinstance(text, bytes):
            text = text.decode("ascii", "replace")
        if isinstance(text, str) and "RFC822.SIZE" in text:
            try:
                return int(text.split("RFC822.SIZE", 1)[1].split()[0].strip(")"))
            except (IndexError, ValueError):
                return None
    return None
