"""Sourced documents, split into passages, searched with BM25.

Each document starts with a small front-matter block (title, source_url,
publisher, read_on) and has one passage per ``##`` section. Every search hit
carries its source, so an agent can cite what it used.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path

from freight_agents.agentcore.tools import Risk, Tool, tool
from pydantic import BaseModel

_STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "does",
        "for",
        "from",
        "have",
        "how",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "the",
        "to",
        "what",
        "when",
        "with",
        "do",
        "can",
    ]
)


@dataclass(frozen=True)
class Passage:
    doc_id: str
    title: str
    heading: str
    text: str
    source_url: str
    read_on: str


def tokens(text: str) -> list[str]:
    """Lowercase words and numbers, split on anything else; no regex needed."""
    cleaned = "".join(ch.lower() if ch.isalnum() else " " for ch in text)
    return [t for t in cleaned.split() if t not in _STOPWORDS]


def parse_document(doc_id: str, raw: str) -> list[Passage]:
    _, _, rest = raw.partition("---\n")
    header, _, body = rest.partition("\n---\n")
    meta = {}
    for line in header.splitlines():
        key, sep, value = line.partition(":")
        if sep:
            meta[key.strip()] = value.strip()
    passages = []
    for chunk in body.split("\n## ")[1:]:
        heading, _, text = chunk.partition("\n")
        passages.append(
            Passage(
                doc_id=doc_id,
                title=meta["title"],
                heading=heading.strip(),
                text=" ".join(text.split()),
                source_url=meta["source_url"],
                read_on=meta["read_on"],
            )
        )
    return passages


def load_corpus(directory: Path) -> list[Passage]:
    passages: list[Passage] = []
    for path in sorted(directory.glob("*.md")):
        passages.extend(parse_document(path.stem, path.read_text(encoding="utf-8")))
    return passages


def default_corpus() -> list[Passage]:
    """The claim rules: documents directly in docs/."""
    return _corpus(resources.files("freight_agents.knowledge") / "docs")


def topic_corpus(topic: str) -> list[Passage]:
    """One application's documents, in docs/<topic>/, kept out of the default corpus."""
    return _corpus(resources.files("freight_agents.knowledge") / "docs" / topic)


def _corpus(docs: Traversable) -> list[Passage]:
    passages: list[Passage] = []
    for entry in sorted(docs.iterdir(), key=lambda e: e.name):
        if entry.name.endswith(".md"):
            passages.extend(parse_document(entry.name[:-3], entry.read_text(encoding="utf-8")))
    return passages


class Bm25Index:
    def __init__(self, passages: list[Passage], k1: float = 1.5, b: float = 0.75) -> None:
        self.passages = passages
        self.k1, self.b = k1, b
        self._docs = [Counter(tokens(f"{p.heading} {p.text}")) for p in passages]
        self._lengths = [sum(d.values()) for d in self._docs]
        self._avg = sum(self._lengths) / len(self._lengths) if self._lengths else 0.0
        df: Counter[str] = Counter()
        for d in self._docs:
            df.update(d.keys())
        n = len(passages)
        self._idf = {t: math.log((n - f + 0.5) / (f + 0.5) + 1) for t, f in df.items()}

    def search(self, query: str, k: int = 3) -> list[tuple[Passage, float]]:
        terms = [t for t in tokens(query) if t in self._idf]
        scored = []
        for passage, doc, length in zip(self.passages, self._docs, self._lengths, strict=True):
            score = 0.0
            for term in terms:
                tf = doc.get(term, 0)
                if tf:
                    norm = tf + self.k1 * (1 - self.b + self.b * length / self._avg)
                    score += self._idf[term] * tf * (self.k1 + 1) / norm
            if score > 0:
                scored.append((passage, score))
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[:k]


class SearchIn(BaseModel):
    query: str


class Hit(BaseModel):
    text: str
    title: str
    section: str
    source_url: str


class SearchOut(BaseModel):
    passages: list[Hit]


def search_tool(index: Bm25Index) -> Tool:
    @tool(
        name="search_knowledge",
        description=(
            "Search the sourced rules on freight claims (49 CFR Part 370, 49 U.S.C. 14706). "
            "Returns passages with their section and source URL; cite the section you rely on."
        ),
        risk=Risk.READ,
    )
    def search(args: SearchIn) -> SearchOut:
        return SearchOut(
            passages=[
                Hit(text=p.text, title=p.title, section=p.heading, source_url=p.source_url)
                for p, _ in index.search(args.query)
            ]
        )

    return search
