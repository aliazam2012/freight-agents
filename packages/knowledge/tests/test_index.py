from datetime import UTC, datetime

from freight_agents.agentcore.hooks import HookContext, run_tool
from freight_agents.agentcore.tools import ToolRegistry
from freight_agents.knowledge.index import Bm25Index, default_corpus, search_tool
from freight_agents.llm import ToolCall


def test_loading_keeps_sources_per_passage() -> None:
    passages = default_corpus()
    assert len(passages) >= 8
    for p in passages:
        assert p.source_url.startswith("https://www.law.cornell.edu/")
        assert p.read_on == "2026-11-22"
        assert p.heading
        assert p.text


def test_acknowledgment_question_finds_370_5() -> None:
    index = Bm25Index(default_corpus())
    top, _ = index.search("how long does the carrier have to acknowledge a claim")[0]
    assert top.heading.startswith("370.5 ")


def test_filing_deadline_question_finds_14706_e() -> None:
    index = Bm25Index(default_corpus())
    top, _ = index.search("minimum months to file a claim")[0]
    assert top.heading.startswith("14706(e)")


def test_disposition_question_finds_370_9() -> None:
    index = Bm25Index(default_corpus())
    top, _ = index.search("120 days to pay or decline")[0]
    assert top.heading.startswith("370.9")


def test_no_matching_terms_returns_nothing() -> None:
    assert Bm25Index(default_corpus()).search("zebra xylophone") == []


def test_the_search_tool_returns_citations() -> None:
    tool = search_tool(Bm25Index(default_corpus()))
    ctx = HookContext(run_id="r", agent="a", now=datetime(2026, 11, 22, tzinfo=UTC))
    call = ToolCall(id="1", name="search_knowledge", args={"query": "acknowledge claim 30 days"})
    out = run_tool(call, ToolRegistry([tool]), [], [], ctx)
    assert out.status == "ok"
    assert out.output is not None
    first = out.output["passages"][0]
    assert set(first) == {"text", "title", "section", "source_url"}
    assert first["source_url"].startswith("https://")
