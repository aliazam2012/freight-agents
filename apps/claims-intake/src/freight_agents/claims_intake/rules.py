"""The claim rules this package ships: 49 CFR Part 370 and 49 U.S.C. 14706, summarized with
their sources in docs/. carrier-filing and damage-assessor cite the same passages."""

from __future__ import annotations

from freight_agents.knowledge.index import Passage, package_corpus


def claim_rules() -> list[Passage]:
    return package_corpus("freight_agents.claims_intake")
