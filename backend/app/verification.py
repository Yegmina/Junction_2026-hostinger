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
    company_people,
    competitor_backers,
    deals_since,
    investor_graph,
    latest_deal,
    norm,
    pick_intro_companies,
    recent_year,
    resolve,
    ticket_match,
)
from app.models import Conflict, IntroPath, InvestorTarget, InvestorVerification, Source, StartupProfile, TicketMatch

GRAPH_SOURCE = [Source(name="Cala knowledge graph")]
MAX_COMPETITORS = 8
SHOWN_COMPETITORS = 6
COMPETITOR_BUDGET = 45.0
INVESTOR_BUDGET = 60.0
INTRO_BUDGET = 20.0
INTROS_PER_INVESTOR = 3


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


async def _intro_paths(client: GraphClient, graph: InvestorGraph, corpus: str) -> list[IntroPath]:
    companies = pick_intro_companies(graph.portfolio, corpus)
    try:
        found = await asyncio.wait_for(asyncio.gather(*(company_people(client, c) for c in companies)), INTRO_BUDGET)
    except asyncio.TimeoutError:
        return []
    # One person per company keeps the list varied: several companies beat several people at one.
    paths = [IntroPath(person=p[0][0], role=p[0][1], company=p[0][2]) for p in found if p]
    return paths[:INTROS_PER_INVESTOR]


async def verify_targets(
    settings: Settings, targets: list[InvestorTarget], cmap: CompetitorMap, bundle: EvidenceBundle,
    profile: StartupProfile | None = None,
) -> list[InvestorTarget]:
    graphs: dict[str, InvestorGraph | None] = {t.name: None for t in targets}
    intros: dict[str, list[IntroPath]] = {}
    corpus = " ".join(norm(e.text) for e in bundle.evidence)
    competitor_ids = {c.id for c in cmap.competitors}
    if settings.cala_api_key and targets:
        async with httpx.AsyncClient() as http:
            client = GraphClient(settings, http)

            async def one(target: InvestorTarget) -> None:
                entity = await resolve(client, target.name, investor=True)
                if entity:
                    graphs[target.name] = InvestorGraph(entity=entity)
                    graph = await investor_graph(client, entity)
                    graphs[target.name] = graph
                    # Founders of a competitor are not a warm intro.
                    safe = InvestorGraph(entity=graph.entity,
                                         portfolio=[c for c in graph.portfolio if c.id not in competitor_ids])
                    intros[target.name] = await _intro_paths(client, safe, corpus)

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
            introPaths=intros.get(target.name, []),
            ticket=(TicketMatch(**ticket_match(graph.deals, profile.stage, profile.targetAmountEur))
                    if graph and profile else None),
        )
        if graph and graph.portfolio:
            portfolio = ", ".join(c.name for c in graph.portfolio[:10])
            deal_note = f" Latest recorded deal {verification.latestDeal}." if verification.latestDeal else ""
            facts = [bundle.add("graph", f"Cala graph: {graph.entity.name} INVESTED_IN {portfolio}"
                                f"{' and more' if len(graph.portfolio) > 10 else ''}.{deal_note}", GRAPH_SOURCE,
                                title=f"{graph.entity.name} portfolio ({len(graph.portfolio)} companies)")]
        else:
            facts = []
        if verification.introPaths:
            people = "; ".join(f"{p.person} ({p.role} of {p.company})" for p in verification.introPaths)
            facts.append(bundle.add("graph", f"Cala graph: people behind {verification.entityName} portfolio "
                                    f"companies: {people}.", GRAPH_SOURCE, title=f"Warm intros to {verification.entityName}"))
        if verification.ticket and verification.ticket.match != "unknown":
            facts.append(bundle.add("graph", f"Cala graph: {verification.entityName}: {verification.ticket.text}",
                                    GRAPH_SOURCE, title=f"{verification.entityName} round sizes"))
        new = [f for f in facts if f and f not in target.evidence]
        if new:
            target = target.model_copy(update={"evidence": [*target.evidence, *new]})
        enriched.append(target.model_copy(update={"verification": verification}))
    # Graph-confirmed conflicts go last; then verified before unverified; then by fit.
    # Text co-mentions are shown as "possible links" but do not demote an investor on their own.
    enriched.sort(key=lambda t: (any(c.basis == "graph" for c in t.verification.conflicts),
                                 not t.verification.verified,
                                 bool(t.verification.ticket and t.verification.ticket.match == "no"),
                                 -t.fitScore))
    return enriched
