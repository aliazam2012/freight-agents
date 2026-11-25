"""Check that every relative link in the Markdown files points at a file that exists.

Offline and deterministic: web links and in-page anchors are not fetched.
Usage: freight-links [root]
"""

from __future__ import annotations

import sys
from pathlib import Path

SKIP_DIRS = {".git", ".venv", "var", ".superpowers", "node_modules"}


def _targets(text: str) -> list[str]:
    found, start = [], 0
    while (open_at := text.find("](", start)) != -1:
        close_at = text.find(")", open_at + 2)
        if close_at == -1:
            break
        found.append(text[open_at + 2 : close_at].strip())
        start = close_at + 1
    return found


def broken(root: Path) -> list[tuple[str, str]]:
    problems = []
    for path in sorted(root.rglob("*.md")):
        if SKIP_DIRS & set(path.relative_to(root).parts):
            continue
        for target in _targets(path.read_text(encoding="utf-8")):
            if not target or target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            local = target.split("#", 1)[0]
            if not (path.parent / local).exists():
                problems.append((str(path.relative_to(root)), target))
    return problems


def main(argv: list[str]) -> int:
    problems = broken(Path(argv[0]) if argv else Path.cwd())
    for source, target in problems:
        print(f"{source}: broken link {target}")
    print(f"links: {len(problems)} broken")
    return 1 if problems else 0


def run() -> int:
    """Console entry point: freight-purity, freight-links or freight-denylist."""
    return main(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
