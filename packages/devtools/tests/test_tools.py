from pathlib import Path

from freight_agents.devtools import check_links as links
from freight_agents.devtools import denylist_check as denylist
from freight_agents.devtools import purity

REPO = Path(__file__).resolve().parents[3]


def _tree(tmp_path: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return tmp_path


def test_purity_flags_each_bad_pattern(tmp_path: Path) -> None:
    root = _tree(
        tmp_path,
        {
            "a.py": "owner = 'someone@realcompany.com'\n",  # purity: allow
            "b.md": "call 212-736-5000 today\n",  # purity: allow
            "c.txt": "see /Users/alice/notes\n",  # purity: allow
            "d.env": "KEY=sk-ant-abc123def456ghi789jkl\n",  # purity: allow
        },
    )
    kinds = sorted(f.kind for f in purity.scan(root))
    assert kinds == ["email", "home_path", "key", "phone"]


def test_purity_allows_made_up_data(tmp_path: Path) -> None:
    root = _tree(
        tmp_path,
        {
            "a.py": "to = 'dana@example.com'; cc = 'x@sub.example.org'; owner = '@aliazam2012'\n",
            "b.md": "call 415-555-0134; PRO 7741-2209; BOL-55102\n",
        },
    )
    assert purity.scan(root) == []


def test_purity_flags_phone_numbers_in_their_usual_formats(tmp_path: Path) -> None:
    lines = [
        "(212) 736-5000",  # purity: allow
        "212.736.5000",  # purity: allow
        "1-212-736-5000",  # purity: allow
        "+1 212 736 5000",  # purity: allow
    ]
    root = _tree(tmp_path, {f"{i}.md": f"call {line}\n" for i, line in enumerate(lines)})
    assert sorted(f.kind for f in purity.scan(root)) == ["phone"] * 4


def test_purity_passes_numbers_shaped_otherwise(tmp_path: Path) -> None:
    root = _tree(
        tmp_path,
        {
            "a.json": '{"forecast": 2596.201117, "hi_95": 3088.941989, "lo": 1855.250001}\n',
            "b.md": "at 2026-11-23 10:15, near 37.7749, -122.4194, parcel 3512-001-0042\n",
        },
    )
    assert purity.scan(root) == []


def test_the_real_repository_is_clean() -> None:
    assert purity.scan(REPO) == []


def test_link_checker_finds_a_missing_target(tmp_path: Path) -> None:
    root = _tree(
        tmp_path,
        {
            "README.md": "[ok](docs/A.md) [web](https://example.com) "
            "[gone](docs/B.md) [anchor](#x)",
            "docs/A.md": "# A",
        },
    )
    assert links.broken(root) == [("README.md", "docs/B.md")]


def test_the_real_repository_has_no_broken_links() -> None:
    assert links.broken(REPO) == []


def test_denylist_finds_private_terms_case_insensitively(tmp_path: Path) -> None:
    root = _tree(tmp_path, {"a.md": "Built at ACME Widgets in 2026\n", "b.md": "nothing here\n"})
    hits = denylist.find(root, ["acme widgets"])
    assert hits == [("a.md", "acme widgets")]


def test_denylist_without_a_list_is_a_no_op(tmp_path: Path) -> None:
    assert denylist.load_terms(tmp_path / "missing.txt") == []
