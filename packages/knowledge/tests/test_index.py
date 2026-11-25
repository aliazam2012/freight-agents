import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from freight_agents.agentcore.hooks import HookContext, run_tool
from freight_agents.agentcore.tools import ToolRegistry
from freight_agents.knowledge.index import Bm25Index, package_corpus, search_tool
from freight_agents.llm import ToolCall

DOC = """---
title: Example Rules
source_url: https://example.com/rules
read_on: 2026-11-25
---

Plain-language summary for tests.

## Rule 1 Acknowledging a request

A request is acknowledged in writing within 30 days of receipt.

## Rule 2 Deciding a request

A request is paid or declined within 120 days.
"""


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list:  # type: ignore[type-arg]
    package = tmp_path / "rules_pkg"
    (package / "docs").mkdir(parents=True)
    (package / "__init__.py").write_text("")
    (package / "docs" / "example-rules.md").write_text(DOC)
    (package / "docs" / "notes.txt").write_text("not a document")
    monkeypatch.syspath_prepend(str(tmp_path))
    return package_corpus("rules_pkg")


def test_a_packages_docs_load_with_their_sources(corpus: list) -> None:  # type: ignore[type-arg]
    assert [p.heading for p in corpus] == [
        "Rule 1 Acknowledging a request",
        "Rule 2 Deciding a request",
    ]
    for p in corpus:
        assert p.doc_id == "example-rules"
        assert p.title == "Example Rules"
        assert p.source_url == "https://example.com/rules"
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.read_on)


def test_search_ranks_the_matching_passage_first(corpus: list) -> None:  # type: ignore[type-arg]
    top, _ = Bm25Index(corpus).search("acknowledged in writing within 30 days")[0]
    assert top.heading.startswith("Rule 1")


def test_no_matching_terms_returns_nothing(corpus: list) -> None:  # type: ignore[type-arg]
    assert Bm25Index(corpus).search("zebra xylophone") == []


def test_the_search_tool_returns_citations(corpus: list) -> None:  # type: ignore[type-arg]
    tool = search_tool(Bm25Index(corpus))
    ctx = HookContext(run_id="r", agent="a", now=datetime(2026, 11, 22, tzinfo=UTC))
    call = ToolCall(id="1", name="search_knowledge", args={"query": "paid or declined"})
    out = run_tool(call, ToolRegistry([tool]), [], [], ctx)
    assert out.status == "ok"
    assert out.output is not None
    first = out.output["passages"][0]
    assert set(first) == {"text", "title", "section", "source_url"}
    assert first["source_url"] == "https://example.com/rules"
