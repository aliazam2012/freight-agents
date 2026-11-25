import re
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
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.read_on)
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


def test_topic_corpora_stay_out_of_the_default_one() -> None:
    from freight_agents.knowledge.index import default_corpus, topic_corpus

    orders = topic_corpus("orders")
    assert orders
    assert all(p.source_url.startswith("https://") and p.read_on for p in orders)
    default_docs = {p.doc_id for p in default_corpus()}
    assert not default_docs & {p.doc_id for p in orders}


def _section(heading: str) -> str:
    (passage,) = [p for p in default_corpus() if p.heading == heading]
    return passage.text


def test_the_370_summary_says_what_the_regulation_says() -> None:
    # Checked against the official 2024 edition (govinfo.gov), 2026-11-24.
    filing = _section("370.3 Filing a claim: what counts")
    assert "the carrier has reasonable access to the documents that support" in filing
    investigating = _section("370.7 Investigating a claim")
    assert "promptly and thoroughly investigated" in investigating
    assert "bill of lading, evidence of any freight charges" in investigating
    assert "destination value" in investigating
    assert "may not be declined" not in investigating  # 370.7 has no such rule
    verifying = _section("370.7(c) Verifying the loss of a whole package or shipment")
    assert "certified statement in writing from the consignee" in verifying


def test_salvage_question_finds_370_11() -> None:
    index = Bm25Index(default_corpus())
    top, _ = index.search("damaged goods refused by the consignee sold as salvage lot number")[0]
    assert top.heading.startswith("370.11")


def test_the_salvage_summary_claims_no_credit_rule() -> None:
    (claim_file,) = [
        p for p in default_corpus() if p.heading == "370.11(c) Salvage and the claim file"
    ]
    assert "lot number, the money recovered" in claim_file.text
    assert "does not say how salvage proceeds change the amount of a claim" in claim_file.text
