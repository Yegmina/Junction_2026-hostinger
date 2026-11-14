"""Shared transport for every Cala call: a 24 h cache (Valkey or disk) and per-run usage counting.

Usage is tracked in a ContextVar, so concurrent analyses each count their own calls, and
tasks spawned inside one analysis share its counter.
"""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import asdict, dataclass
from typing import Any

import httpx

from app.store import cache_get, cache_key, cache_put

CACHE_TTL_SECONDS = 24 * 3600


@dataclass
class CalaUsage:
    searches: int = 0
    queries: int = 0
    entityLookups: int = 0
    relationships: int = 0
    cached: int = 0
    webSearches: int = 0  # Oxylabs /v1/search
    webScrapes: int = 0  # Oxylabs /v1/scrape
    contextDev: int = 0  # Context.dev calls
    nemotron: int = 0  # NVIDIA Nemotron calls

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


_usage: ContextVar[CalaUsage | None] = ContextVar("cala_usage", default=None)


def start_usage() -> CalaUsage:
    usage = CalaUsage()
    _usage.set(usage)
    return usage


def count_web(field_name: str) -> None:
    """Count a non-Cala call (Oxylabs, Context.dev, Nemotron) for this run."""
    usage = _usage.get()
    if usage is not None:
        setattr(usage, field_name, getattr(usage, field_name) + 1)


def _count(kind: str, payload: Any) -> None:
    usage = _usage.get()
    if usage is None:
        return
    if kind == "search":
        usage.searches += 1
    elif kind == "query":
        usage.queries += 1
    else:
        usage.entityLookups += 1
    rels = payload.get("relationships") if isinstance(payload, dict) else None
    if isinstance(rels, dict):
        for direction in rels.values():
            if isinstance(direction, dict):
                usage.relationships += sum(len(v) for v in direction.values() if isinstance(v, list))


async def cala_request(
    http: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    kind: str,
    headers: dict[str, str],
    params: dict[str, Any] | None = None,
    body: Any = None,
    timeout: float | None = None,
) -> Any:
    """GET/POST to Cala with caching. `kind` is search, query or entity (for usage counts)."""
    key = cache_key(method, url, params, body)
    cached = await cache_get(key, CACHE_TTL_SECONDS)
    if cached is not None:
        _count(kind, cached)
        usage = _usage.get()
        if usage:
            usage.cached += 1
        return cached
    response = await http.request(method, url, headers=headers, params=params, json=body, timeout=timeout)
    response.raise_for_status()
    data = response.json()
    await cache_put(key, data, CACHE_TTL_SECONDS)
    _count(kind, data)
    return data
