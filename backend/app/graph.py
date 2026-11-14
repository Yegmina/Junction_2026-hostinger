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
        r = await self._http.get(self._base, params={"name": name[:100], "limit": limit}, headers=self._headers,
                                 timeout=ENTITY_TIMEOUT)
        r.raise_for_status()
        return [
            GraphEntity(e["id"], e.get("name", ""), e.get("entity_type", ""), e.get("description") or "")
            for e in r.json().get("entities", [])
        ]

    async def relationships(self, entity_id: str) -> dict[str, list[str]]:
        r = await self._http.get(f"{self._base}/{entity_id}/introspection", headers=self._headers, timeout=ENTITY_TIMEOUT)
        r.raise_for_status()
        return r.json().get("relationships") or {}

    async def retrieve(self, entity_id: str, body: dict[str, Any]) -> dict[str, Any]:
        r = await self._http.post(f"{self._base}/{entity_id}", json=body, headers=self._headers, timeout=ENTITY_TIMEOUT)
        r.raise_for_status()
        return r.json()


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
