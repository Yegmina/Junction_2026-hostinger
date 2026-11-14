"""Combine Cala graph lookups with sourced evidence: competitor backers, verified investors, conflicts."""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.cala import EvidenceBundle
from app.config import Settings
from app.graph import (
    PORTFOLIO_LIMIT,
    GraphClient,
    GraphEntity,
    InvestorGraph,
    competitor_backers,
    deals_since,
    investor_graph,
    latest_deal,
    norm,
    recent_year,
    resolve,
)
from app.models import Conflict, InvestorTarget, InvestorVerification, Source, StartupProfile

GRAPH_SOURCE = [Source(name="Cala knowledge graph")]
MAX_COMPETITORS = 8
SHOWN_COMPETITORS = 6
COMPETITOR_BUDGET = 45.0
INVESTOR_BUDGET = 60.0


@dataclass
class CompetitorMap:
    competitors: list[GraphEntity] = field(default_factory=list)
    backers: dict[str, list[GraphEntity]] = field(default_factory=dict)

    def as_payload(self) -> list[dict[str, Any]]:
        return [
            {"id": c.id, "name": c.name, "backers": [b.name for b in self.backers.get(c.id, [])]}
            for c in self.competitors
        ]


INVESTOR_NAME = re.compile(r"\b(ventures?|capital|partners|funds?|angels?|vc|holdings?|equity|lp|llp)\b|vest(or|ment)", re.I)


def competitor_entities(bundle: EvidenceBundle, profile: StartupProfile) -> list[GraphEntity]:
    """Companies Cala tagged in the competitor answer, minus investors and the founder's own startup.

    Structured company rows count too, but only entities named as a row's company (not its investors).
    """
    own = norm(profile.name)
    row_names = {norm(e.title.split(" · ")[0]) for e in bundle.evidence if e.kind == "market"}
    seen: set[str] = set()
    out: list[GraphEntity] = []
    for kind in ("competitor", "market"):
        if kind == "market" and len(out) >= 3:
            break  # the competitor answer is the precise source; company rows only top it up
        for e in bundle.entities.get(kind, []):
            name = e.get("name", "")
            if (e.get("entity_type") != "Company" or e["id"] in seen or INVESTOR_NAME.search(name)
                    or (own and norm(name) == own)):
                continue
            if kind == "market" and not any(n and (n in norm(name) or norm(name) in n) for n in row_names):
                continue
            seen.add(e["id"])
            out.append(GraphEntity(e["id"], name, "Company"))
    return out[:MAX_COMPETITORS]


async def map_competitors(settings: Settings, bundle: EvidenceBundle, profile: StartupProfile) -> CompetitorMap:
    result = CompetitorMap(competitors=competitor_entities(bundle, profile))
    if not result.competitors or not settings.cala_api_key:
        return result
    async with httpx.AsyncClient() as http:
        try:
            result.backers, investors = await asyncio.wait_for(
                competitor_backers(GraphClient(settings, http), result.competitors), COMPETITOR_BUDGET)
            result.competitors = [c for c in result.competitors if c.id not in investors][:SHOWN_COMPETITORS]
        except asyncio.TimeoutError:
            pass
    return result


def add_competitor_facts(bundle: EvidenceBundle, cmap: CompetitorMap) -> None:
    for company in cmap.competitors:
        backers = cmap.backers.get(company.id)
        if backers:
            names = ", ".join(b.name for b in backers[:12])
            bundle.add("graph", f"Cala graph: {company.name} has INVESTED_IN edges from {names}.", GRAPH_SOURCE,
                       title=f"Backers of {company.name}")


def _conflicts(target: str, graph: InvestorGraph | None, cmap: CompetitorMap, bundle: EvidenceBundle) -> list[Conflict]:
    conflicts: dict[str, Conflict] = {}
    competitor_ids = {c.id: c.name for c in cmap.competitors}
    competitor_names = {norm(c.name): c.name for c in cmap.competitors}
    target_norm = norm(target)
    if graph:
        for company in graph.portfolio:
            name = competitor_ids.get(company.id) or competitor_names.get(norm(company.name))
            if name:
                conflicts[norm(name)] = Conflict(company=name, basis="graph")
    for company in cmap.competitors:
        if any(norm(b.name) == target_norm or (graph and b.id == graph.entity.id) for b in cmap.backers.get(company.id, [])):
            conflicts[norm(company.name)] = Conflict(company=company.name, basis="graph")
    # Sourced text: competitor evidence that names this investor next to a competitor.
    for fact in bundle.evidence:
        if fact.kind != "competitor" or target_norm not in norm(fact.text):
            continue
        for key, name in competitor_names.items():
            if key and key in norm(fact.text) and key not in conflicts:
                conflicts[key] = Conflict(company=name, basis="evidence", evidence=fact.id)
    return list(conflicts.values())


async def verify_targets(
    settings: Settings, targets: list[InvestorTarget], cmap: CompetitorMap, bundle: EvidenceBundle
) -> list[InvestorTarget]:
    graphs: dict[str, InvestorGraph | None] = {t.name: None for t in targets}
    if settings.cala_api_key and targets:
        async with httpx.AsyncClient() as http:
            client = GraphClient(settings, http)

            async def one(target: InvestorTarget) -> None:
                entity = await resolve(client, target.name, investor=True)
                if entity:
                    graphs[target.name] = InvestorGraph(entity=entity)
                    graphs[target.name] = await investor_graph(client, entity)

            try:
                await asyncio.wait_for(asyncio.gather(*(one(t) for t in targets)), INVESTOR_BUDGET)
            except asyncio.TimeoutError:
                pass  # keep whatever finished; the rest stays unverified

    year = recent_year()
    enriched: list[InvestorTarget] = []
    for target in targets:
        graph = graphs.get(target.name)
        verification = InvestorVerification(
            verified=graph is not None,
            entityId=graph.entity.id if graph else None,
            entityName=graph.entity.name if graph else None,
            description=(graph.entity.description[:240] if graph else ""),
            portfolio=[c.name for c in graph.portfolio[:8]] if graph else [],
            portfolioCount=len(graph.portfolio) if graph else 0,
            portfolioCapped=bool(graph and len(graph.portfolio) >= PORTFOLIO_LIMIT),
            recentDeals=deals_since(graph.deals, year) if graph else 0,
            latestDeal=latest_deal(graph.deals) if graph else "",
            conflicts=_conflicts(target.name, graph, cmap, bundle),
        )
        if graph and graph.portfolio:
            portfolio = ", ".join(c.name for c in graph.portfolio[:10])
            deal_note = f" Latest recorded deal {verification.latestDeal}." if verification.latestDeal else ""
            bundle.add("graph", f"Cala graph: {graph.entity.name} INVESTED_IN {portfolio}"
                       f"{' and more' if len(graph.portfolio) > 10 else ''}.{deal_note}", GRAPH_SOURCE,
                       title=f"{graph.entity.name} portfolio ({len(graph.portfolio)} companies)")
            graph_fact = bundle.evidence[-1].id
            if graph_fact not in target.evidence:
                target = target.model_copy(update={"evidence": [*target.evidence, graph_fact]})
        enriched.append(target.model_copy(update={"verification": verification}))
    # Graph-confirmed conflicts go last; then verified before unverified; then by fit.
    # Text co-mentions are shown as "possible links" but do not demote an investor on their own.
    enriched.sort(key=lambda t: (any(c.basis == "graph" for c in t.verification.conflicts),
                                 not t.verification.verified, -t.fitScore))
    return enriched
