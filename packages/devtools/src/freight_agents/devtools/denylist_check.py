"""The private clean-room gate, run before every push on the author's machine.

It reads terms from a file kept outside the repository (default
~/.config/freight-agents/denylist.txt, one term per line): employer and
customer names, internal tool names, personal details. The list never ships,
because a public denylist would name what it protects. No list, no check.
Usage: freight-denylist [root]
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

DEFAULT_LIST = Path.home() / ".config" / "freight-agents" / "denylist.txt"
SKIP_DIRS = {".git", ".venv", "__pycache__", "var", ".superpowers", "node_modules"}


def load_terms(path: Path) -> list[str]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [t.strip().lower() for t in lines if t.strip() and not t.startswith("#")]


def find(root: Path, terms: list[str]) -> list[tuple[str, str]]:
    hits: list[tuple[str, str]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or SKIP_DIRS & set(path.relative_to(root).parts):
            continue
        try:
            text = path.read_text(encoding="utf-8").lower()
        except (UnicodeDecodeError, OSError):
            continue
        hits.extend((str(path.relative_to(root)), t) for t in terms if t in text)
    return hits


def main(argv: list[str]) -> int:
    terms = load_terms(Path(os.environ.get("FREIGHT_AGENTS_DENYLIST", DEFAULT_LIST)))
    if not terms:
        print("denylist: no private list on this machine; skipped")
        return 0
    hits = find(Path(argv[0]) if argv else Path.cwd(), terms)
    for path, _term in hits:
        print(f"{path}: contains a denied term")  # the term itself is never printed
    print(f"denylist: {len(hits)} hit(s) against {len(terms)} terms")
    return 1 if hits else 0


def run() -> int:
    """Console entry point: freight-purity, freight-links or freight-denylist."""
    return main(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
