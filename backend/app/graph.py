"""Cala knowledge-graph checks: who backs the competitors, and is each shortlisted investor real,
still active and free of portfolio conflicts.

Graph calls are bounded by timeouts so a slow lookup degrades to "not verified" instead of
stalling the run.
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import httpx

from app.calahttp import cala_request
from app.config import Settings

ENTITY_TIMEOUT = 25.0
PORTFOLIO_LIMIT = 40
INVESTOR_FIELDS = ("venture", "capital", "invest", "fund", "angel", "vc", "accelerator", "equity")
SUFFIXES = r"\b(oy|oyj|ab|aps|a/s|as|gmbh|ltd|limited|llc|inc|plc|oü|ou|sa|bv|nv|ky|kb|srl|sas|corp|co)\b\.?"


def norm(name: str) -> str:
    text = re.sub(SUFFIXES, " ", (name or "").lower())
    return " ".join(re.sub(r"[^a-z0-9äöåü ]+", " ", text).split())


@dataclass
class GraphEntity:
    id: str
    name: str
    entity_type: str
    description: str = ""


@dataclass
class InvestorGraph:
    entity: GraphEntity
    portfolio: list[GraphEntity] = field(default_factory=list)
    deals: list[dict[str, Any]] = field(default_factory=list)


class GraphClient:
    def __init__(self, settings: Settings, http: httpx.AsyncClient):
        self._base = f"{settings.cala_base_url}/v1/entities"
        self._http = http
        self._headers = {"X-API-KEY": settings.cala_api_key or "", "Content-Type": "application/json"}

    async def search(self, name: str, limit: int = 8) -> list[GraphEntity]:
        data = await cala_request(self._http, "GET", self._base, kind="entity", headers=self._headers,
                                  params={"name": name[:100], "limit": limit}, timeout=ENTITY_TIMEOUT)
        return [
            GraphEntity(e["id"], e.get("name", ""), e.get("entity_type", ""), e.get("description") or "")
            for e in data.get("entities", [])
        ]

    async def relationships(self, entity_id: str) -> dict[str, list[str]]:
        data = await cala_request(self._http, "GET", f"{self._base}/{entity_id}/introspection", kind="entity",
                                  headers=self._headers, timeout=ENTITY_TIMEOUT)
        return data.get("relationships") or {}

    async def retrieve(self, entity_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return await cala_request(self._http, "POST", f"{self._base}/{entity_id}", kind="entity",
                                  headers=self._headers, body=body, timeout=ENTITY_TIMEOUT)


def _related(payload: dict[str, Any], direction: str, rel: str) -> list[GraphEntity]:
    items = ((payload.get("relationships") or {}).get(direction) or {}).get(rel) or []
    return [GraphEntity(e["id"], e.get("name", ""), e.get("entity_type", "")) for e in items if e.get("id")]


def _value(payload: dict[str, Any], prop: str) -> Any:
    item = (payload.get("properties") or {}).get(prop)
    return item.get("value") if isinstance(item, dict) else item


def pick_entity(name: str, candidates: list[GraphEntity], investor: bool) -> GraphEntity | None:
    """Best candidate for a name: exact normalized match first, investors prefer VC-like descriptions."""
    target = norm(name)
    best, best_score = None, 0.0
    for c in candidates:
        if c.entity_type not in ("Organization", "Company"):
            continue
        n = norm(c.name)
        score = 3.0 if n == target else 1.5 if n.startswith(target) or target.startswith(n) else 0.0
        if not score:
            continue
        if investor and any(w in c.description.lower() for w in INVESTOR_FIELDS):
            score += 1.5
        if investor and c.entity_type == "Organization":
            score += 0.5
        if re.search(r"\bfund\s+[ivx\d]+\b", c.name.lower()):
            score -= 1.0  # prefer the firm over one of its fund vehicles
        if score > best_score:
            best, best_score = c, score
    return best if best_score >= 2.5 else None


async def resolve(client: GraphClient, name: str, investor: bool) -> GraphEntity | None:
    try:
        return pick_entity(name, await client.search(name), investor)
    except httpx.HTTPError:
        return None


INVESTOR_EDGES = {"INVESTED_IN"}  # raising rounds also creates PARTICIPATES_IN_FUNDING_ROUND, so it is not a signal


async def competitor_backers(
    client: GraphClient, competitors: list[GraphEntity]
) -> tuple[dict[str, list[GraphEntity]], set[str]]:
    """Map competitor id -> investors with an INVESTED_IN edge into it.

    Also returns ids that turned out to be investors themselves (they have outgoing investment
    edges), since Cala's answers sometimes tag funds and asset managers next to competitors.
    """

    async def one(company: GraphEntity) -> tuple[str, list[GraphEntity], bool]:
        try:
            rels = await client.relationships(company.id)
            if INVESTOR_EDGES & set(rels.get("outgoing") or []):
                return company.id, [], True
            if "INVESTED_IN" not in (rels.get("incoming") or []):
                return company.id, [], False
            payload = await client.retrieve(company.id, {"relationships": {"incoming": {"INVESTED_IN": {"limit": 25}}}})
            return company.id, _related(payload, "incoming", "INVESTED_IN"), False
        except httpx.HTTPError:
            return company.id, [], False

    results = await asyncio.gather(*(one(c) for c in competitors))
    return {cid: backers for cid, backers, _ in results if backers}, {cid for cid, _, investor in results if investor}


async def investor_graph(client: GraphClient, entity: GraphEntity) -> InvestorGraph:
    graph = InvestorGraph(entity=entity)
    try:
        rels = (await client.relationships(entity.id)).get("outgoing") or []
        wanted = {r: {"limit": PORTFOLIO_LIMIT} for r in ("INVESTED_IN", "PARTICIPATES_IN_FUNDING_ROUND") if r in rels}
        if not wanted:
            return graph
        payload = await client.retrieve(entity.id, {"properties": ["description"], "relationships": {"outgoing": wanted}})
        graph.entity.description = graph.entity.description or str(_value(payload, "description") or "")
        graph.portfolio = _related(payload, "outgoing", "INVESTED_IN")
        rounds = _related(payload, "outgoing", "PARTICIPATES_IN_FUNDING_ROUND")[:10]
    except httpx.HTTPError:
        return graph

    async def deal(round_entity: GraphEntity) -> dict[str, Any] | None:
        try:
            p = await client.retrieve(round_entity.id, {"properties": [
                "announcement_date", "round_label", "transaction_value", "transaction_value_units"]})
        except httpx.HTTPError:
            return None
        when = str(_value(p, "announcement_date") or "")[:10]
        return {"date": when, "label": str(_value(p, "round_label") or round_entity.name),
                "value": _value(p, "transaction_value"), "units": _value(p, "transaction_value_units")}

    deals = [d for d in await asyncio.gather(*(deal(r) for r in rounds)) if d]
    graph.deals = sorted(deals, key=lambda d: d["date"], reverse=True)
    return graph


def deals_since(deals: list[dict[str, Any]], year: int) -> int:
    return sum(1 for d in deals if d["date"][:4].isdigit() and int(d["date"][:4]) >= year)


def latest_deal(deals: list[dict[str, Any]]) -> str:
    return next((d["date"] for d in deals if d["date"]), "")


def recent_year() -> int:
    return date.today().year - 2


# --- Warm intro paths: people who founded or run an investor's portfolio companies ---------------

PEOPLE_EDGES = {"FOUNDED": "founder", "IS_CEO_OF": "CEO", "IS_CTO_OF": "CTO"}


async def company_people(client: GraphClient, company: GraphEntity) -> list[tuple[str, str, str]]:
    """(person, role, company) for founders and executives of one company; one row per person."""
    try:
        incoming = set((await client.relationships(company.id)).get("incoming") or [])
        wanted = {r: {"limit": 3} for r in PEOPLE_EDGES if r in incoming}
        if not wanted:
            return []
        payload = await client.retrieve(company.id, {"relationships": {"incoming": wanted}})
    except httpx.HTTPError:
        return []
    people: dict[str, tuple[str, str, str]] = {}
    for rel, role in PEOPLE_EDGES.items():  # founder first, so a founder-CEO reads as founder
        for person in _related(payload, "incoming", rel):
            if person.entity_type == "Person" and person.name and person.name not in people:
                people[person.name] = (person.name, role, company.name)
    return list(people.values())


def pick_intro_companies(portfolio: list[GraphEntity], corpus: str, limit: int = 4) -> list[GraphEntity]:
    """Portfolio companies named in the evidence first (most relevant), then the rest in graph order."""
    mentioned = [c for c in portfolio if norm(c.name) and norm(c.name) in corpus]
    rest = [c for c in portfolio if c not in mentioned]
    return (mentioned + rest)[:limit]


# --- Ticket-size match: what kind of rounds an investor actually joins --------------------------

USD_TO_EUR = 0.92
ROUND_STAGE = {"PRE_SEED": "pre-seed", "SEED": "seed", "SERIES_A": "series-a", "SERIES_B": "series-b"}
STAGE_NAMES = {"pre-seed": "pre-seed", "seed": "seed", "series-a": "Series A", "series-b": "Series B", "growth": "growth"}


def round_stage(label: str) -> str | None:
    label = (label or "").upper().replace("-", "_").replace(" ", "_")
    if label in ROUND_STAGE:
        return ROUND_STAGE[label]
    if label.startswith("SERIES_") or label in ("GROWTH", "LATE_STAGE", "PRIVATE_EQUITY"):
        return "growth"
    return None


def deal_eur(deal: dict[str, Any]) -> float | None:
    try:
        value = float(deal.get("value"))
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    units = str(deal.get("units") or "EUR").upper()
    return value * USD_TO_EUR if units == "USD" else value if units == "EUR" else None


def _money(value: float) -> str:
    return f"€{value / 1e6:.1f}M".replace(".0M", "M") if value >= 1e6 else f"€{value / 1e3:.0f}k"


def ticket_match(deals: list[dict[str, Any]], stage: str, target_eur: float) -> dict[str, Any]:
    """Compare the rounds an investor joined (stage and round size) with the founder's raise."""
    stages: list[str] = []
    for d in deals:
        s = round_stage(d.get("label", ""))
        if s and s not in stages:
            stages.append(s)
    stages.sort(key=list(STAGE_NAMES).index)
    amounts = sorted(a for a in (deal_eur(d) for d in deals) if a)
    if not stages and not amounts:
        return {"stages": [], "minEur": None, "maxEur": None, "rounds": len(deals), "match": "unknown",
                "text": "No round details in the Cala graph yet."}
    low, high = (amounts[0], amounts[-1]) if amounts else (None, None)
    stage_ok = stage in stages if stages else None
    # Round sizes are totals, so allow a generous band around what this investor has joined.
    size_ok = (low / 2 <= target_eur <= high * 2) if amounts else None
    checks = [c for c in (stage_ok, size_ok) if c is not None]
    match = "yes" if all(checks) else "no" if not any(checks) else "partial"
    stage_text = "/".join(STAGE_NAMES[s] for s in stages) or "undisclosed-stage"
    size_text = (f" of {_money(low)}" if low == high else f" of {_money(low)}–{_money(high)}") if amounts else ""
    verdict = {"yes": "fits your", "partial": "partly fits your", "no": "does not fit your"}[match]
    text = f"Joined {stage_text} rounds{size_text}; {verdict} {_money(target_eur)} {STAGE_NAMES.get(stage, stage)}."
    return {"stages": stages, "minEur": low, "maxEur": high, "rounds": len(deals), "match": match, "text": text}
