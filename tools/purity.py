"""The public clean-room gate: fail on anything that looks real.

Flags email addresses outside the documentation domains (RFC 2606), phone
numbers outside the fictional 555 exchange, home-directory paths, and key-like
strings. A plain scan, no regex: the inputs are every file in the repository.
Usage: python tools/purity.py [root]
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

SKIP_DIRS = {
    ".git",
    ".venv",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    "var",
    ".superpowers",
    "node_modules",
}
SKIP_FILES = {"uv.lock"}
DOC_DOMAINS = ("example.com", "example.net", "example.org")
KEY_PREFIXES = ("sk-ant-", "ghp_", "github_pat_", "AKIA", "xoxb-", "-----BEGIN")
HOME_PATHS = ("/Users/", "/home/")  # purity: allow
WORD_BREAKS = frozenset(" \t\n\r\"'`<>()[]{},;|=\\")
ALLOW_MARK = "purity: allow"


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    kind: str
    text: str


def _files(root: Path) -> list[Path]:
    found = []
    for path in sorted(root.rglob("*")):
        if (
            path.is_file()
            and path.name not in SKIP_FILES
            and not (SKIP_DIRS & set(path.relative_to(root).parts))
        ):
            found.append(path)
    return found


def _words(line: str) -> list[str]:
    cleaned = "".join(" " if ch in WORD_BREAKS else ch for ch in line)
    return [w.strip(".:") for w in cleaned.split()]


def _bad_email(word: str) -> bool:
    local, at, domain = word.partition("@")
    if not (at and local and "." in domain):
        return False
    labels = f".{domain.lower()}."
    # A documentation domain as whole labels: x@example.net, x@sub.example.org,
    # and a file named after one, x@example.net.pdf.
    return not any(f".{d}." in labels for d in DOC_DOMAINS)


def _phones(line: str) -> list[str]:
    """Ten-digit numbers written as phone numbers, outside the 555 exchange."""
    found, i, n = [], 0, len(line)
    while i < n:
        if not line[i].isdigit():
            i += 1
            continue
        j, digits = i, ""
        while j < n and (
            line[j].isdigit() or (line[j] in " -.()" and j + 1 < n and line[j + 1].isdigit())
        ):
            if line[j].isdigit():
                digits += line[j]
            j += 1
        if len(digits) == 10 and digits[3:6] != "555" and any(c in line[i:j] for c in " -.()"):
            found.append(line[i:j])
        i = j
    return found


def scan(root: Path) -> list[Finding]:
    findings = []
    for path in _files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        rel = str(path.relative_to(root))
        for number, line in enumerate(text.splitlines(), 1):
            if ALLOW_MARK in line:
                continue
            for word in _words(line):
                if _bad_email(word):
                    findings.append(Finding(rel, number, "email", word))
                if any(word.startswith(p) for p in KEY_PREFIXES) and len(word) >= 16:
                    findings.append(Finding(rel, number, "key", word[:12] + "..."))
            for phone in _phones(line):
                findings.append(Finding(rel, number, "phone", phone))
            if any(p in line for p in HOME_PATHS):
                findings.append(Finding(rel, number, "home_path", line.strip()[:60]))
    return findings


def main(argv: list[str]) -> int:
    root = Path(argv[0]) if argv else Path.cwd()
    findings = scan(root)
    for f in findings:
        print(f"{f.path}:{f.line}: {f.kind}: {f.text}")
    print(f"purity: {len(findings)} finding(s)")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
