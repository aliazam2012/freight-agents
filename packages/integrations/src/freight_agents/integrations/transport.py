"""Outbound email. Callers reach a transport only after a person approved the send."""

from __future__ import annotations

import uuid
from email.message import EmailMessage as Mime
from pathlib import Path
from typing import Protocol


class Transport(Protocol):
    def send(self, *, sender: str, to: str, subject: str, body: str) -> str:
        """Send one message and return its Message-ID."""
        ...


class FileTransport:
    """Writes each message as a .eml file: the demo's stand-in for an SMTP server."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def send(self, *, sender: str, to: str, subject: str, body: str) -> str:
        self.directory.mkdir(parents=True, exist_ok=True)
        message_id = f"<{uuid.uuid4().hex}@freight-agents.example.org>"
        msg = Mime()
        msg["Message-ID"] = message_id
        msg["From"] = sender
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)
        name = message_id.strip("<>").split("@")[0]
        (self.directory / f"{name}.eml").write_bytes(msg.as_bytes())
        return message_id
