from email.message import EmailMessage as Mime
from pathlib import Path

from freight_agents.integrations.email import DirectoryInbox, parse_eml
from freight_agents.integrations.transport import FileTransport

PLAIN = (
    b"Message-ID: <a1@example.com>\r\nFrom: Dana Reyes <dana@example.com>\r\n"
    b"To: claims@example.org\r\nSubject: Damaged pallet\r\n"
    b"Date: Mon, 16 Nov 2026 09:30:00 -0800\r\n\r\nPRO 7741-2209 arrived crushed.\r\n"
)

HTML_ONLY = (
    b"Message-ID: <a2@example.com>\r\nFrom: ops@example.net\r\nTo: claims@example.org\r\n"
    b"Subject: Claim\r\nContent-Type: text/html; charset=utf-8\r\n\r\n"
    b"<html><head><style>p {color: red}</style></head><body><p>Two cartons</p>"
    b"<p>were <b>missing</b>.</p><script>alert(1)</script></body></html>\r\n"
)

LATIN1 = (
    b"Message-ID: <a3@example.com>\r\nFrom: cafe@example.com\r\nTo: claims@example.org\r\n"
    b"Subject: =?iso-8859-1?q?Caf=E9_order_damaged?=\r\n"
    b"Content-Type: text/plain; charset=iso-8859-1\r\n"
    b"Content-Transfer-Encoding: 8bit\r\n\r\nThe caf\xe9 tables arrived broken.\r\n"
)


def _nested() -> bytes:
    msg = Mime()
    msg["Message-ID"] = "<a4@example.com>"
    msg["From"] = "pat@example.com"
    msg["To"] = "claims@example.org"
    msg["Subject"] = "Claim with photos"
    msg.set_content("Plain body: 4 chairs damaged.")
    msg.add_alternative("<p>HTML body: 4 chairs damaged.</p>", subtype="html")
    msg.add_attachment(b"\x89PNG fake", maintype="image", subtype="png", filename="photo-1.png")
    return msg.as_bytes()


def test_plain_message() -> None:
    m = parse_eml(PLAIN)
    assert m.message_id == "<a1@example.com>"
    assert m.sender == "dana@example.com"
    assert m.to == ["claims@example.org"]
    assert m.subject == "Damaged pallet"
    assert m.date is not None
    assert m.date.isoformat() == "2026-11-16T09:30:00-08:00"
    assert "PRO 7741-2209 arrived crushed." in m.text


def test_html_only_message_becomes_readable_text() -> None:
    text = parse_eml(HTML_ONLY).text
    assert "Two cartons" in text
    assert "were missing." in text
    assert "alert" not in text
    assert "color" not in text


def test_declared_charsets_and_encoded_headers_decode() -> None:
    m = parse_eml(LATIN1)
    assert m.subject == "Café order damaged"
    assert "The café tables arrived broken." in m.text


def test_nested_multipart_prefers_plain_and_keeps_attachments() -> None:
    m = parse_eml(_nested())
    assert m.text.strip() == "Plain body: 4 chairs damaged."
    assert [(a.filename, a.media_type) for a in m.attachments] == [("photo-1.png", "image/png")]
    assert m.attachments[0].data == b"\x89PNG fake"


def test_a_message_without_an_id_gets_a_stable_one() -> None:
    raw = PLAIN.replace(b"Message-ID: <a1@example.com>\r\n", b"")
    assert parse_eml(raw).message_id == parse_eml(raw).message_id
    assert parse_eml(raw).message_id.startswith("<sha256-")


def test_inbox_reads_messages_oldest_first(tmp_path: Path) -> None:
    (tmp_path / "b.eml").write_bytes(PLAIN)
    later = PLAIN.replace(b"<a1@", b"<a9@").replace(b"Mon, 16 Nov", b"Tue, 17 Nov")
    (tmp_path / "a.eml").write_bytes(later)
    assert [m.message_id for m in DirectoryInbox(tmp_path).messages()] == [
        "<a1@example.com>",
        "<a9@example.com>",
    ]


def test_file_transport_writes_one_message_per_send(tmp_path: Path) -> None:
    transport = FileTransport(tmp_path / "sent")
    sent_id = transport.send(
        sender="claims@example.org", to="dana@example.com", subject="More info", body="Hello"
    )
    files = list((tmp_path / "sent").glob("*.eml"))
    assert len(files) == 1
    back = parse_eml(files[0].read_bytes())
    assert (back.message_id, back.to, back.subject) == (sent_id, ["dana@example.com"], "More info")
