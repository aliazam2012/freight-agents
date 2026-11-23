"""Read email: .eml bytes in, a plain EmailMessage out.

The standard library does the MIME work (multipart, charsets, encoded
headers). HTML-only mail is reduced to text with the standard HTML parser,
dropping scripts and styles. Everything here is untrusted input.
"""

from __future__ import annotations

import email
import email.policy
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from email.message import EmailMessage as Mime
from html.parser import HTMLParser
from pathlib import Path


@dataclass(frozen=True)
class Attachment:
    filename: str
    media_type: str
    data: bytes


@dataclass(frozen=True)
class EmailMessage:
    message_id: str
    sender: str
    to: list[str]
    subject: str
    date: datetime | None
    text: str
    attachments: list[Attachment]


def parse_eml(raw: bytes) -> EmailMessage:
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    if not isinstance(msg, Mime):  # policy.default always builds this class
        raise TypeError("email parser returned an unexpected message type")
    message_id = str(msg["Message-ID"] or "").strip()
    if not message_id:
        message_id = f"<sha256-{hashlib.sha256(raw).hexdigest()[:32]}>"
    date_header = msg["Date"]
    return EmailMessage(
        message_id=message_id,
        sender=_addresses(msg, "From")[0] if msg["From"] else "",
        to=_addresses(msg, "To"),
        subject=str(msg["Subject"] or ""),
        date=getattr(date_header, "datetime", None) if date_header else None,
        text=_body_text(msg),
        attachments=[
            Attachment(
                filename=part.get_filename() or "attachment",
                media_type=part.get_content_type(),
                data=_payload_bytes(part),
            )
            for part in msg.iter_attachments()
            if isinstance(part, Mime)
        ],
    )


def _payload_bytes(part: Mime) -> bytes:
    payload = part.get_payload(decode=True)
    return payload if isinstance(payload, bytes) else b""


def _addresses(msg: Mime, header: str) -> list[str]:
    value = msg[header]
    found = [a.addr_spec.lower() for a in getattr(value, "addresses", ())]
    return found or ([str(value).strip().lower()] if value else [])


def _body_text(msg: Mime) -> str:
    plain = msg.get_body(preferencelist=("plain",))
    if isinstance(plain, Mime):
        return str(plain.get_content())
    html = msg.get_body(preferencelist=("html",))
    if isinstance(html, Mime):
        return html_to_text(str(html.get_content()))
    return ""


class _TextExtractor(HTMLParser):
    _SKIP = frozenset({"script", "style", "head"})
    _BREAK = frozenset({"p", "br", "div", "li", "tr", "h1", "h2", "h3", "h4", "table"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.chunks: list[str] = []
        self._skipping = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIP:
            self._skipping += 1
        elif tag in self._BREAK:
            self.chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP and self._skipping:
            self._skipping -= 1
        elif tag in self._BREAK:
            self.chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skipping:
            self.chunks.append(data)


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    lines = (" ".join(line.split()) for line in "".join(parser.chunks).splitlines())
    return "\n".join(line for line in lines if line)


class DirectoryInbox:
    """Every .eml file in a folder, oldest first."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def messages(self) -> list[EmailMessage]:
        parsed = [parse_eml(p.read_bytes()) for p in sorted(self.path.glob("*.eml"))]
        oldest = datetime.min.replace(tzinfo=UTC)
        return sorted(parsed, key=lambda m: (m.date or oldest, m.message_id))
