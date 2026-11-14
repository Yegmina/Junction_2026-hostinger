"""Shared transport for every Cala call: a 24 h disk cache and per-run usage counting.

Usage is tracked in a ContextVar, so concurrent analyses each count their own calls, and
tasks spawned inside one analysis share its counter.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx

CACHE_TTL_SECONDS = 24 * 3600


def data_dir() -> Path:
    path = Path(os.getenv("DATA_DIR") or Path(__file__).resolve().parents[1] / "data")
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass
class CalaUsage:
    searches: int = 0
    queries: int = 0
    entityLookups: int = 0
    relationships: int = 0
    cached: int = 0

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


_usage: ContextVar[CalaUsage | None] = ContextVar("cala_usage", default=None)


def start_usage() -> CalaUsage:
    usage = CalaUsage()
    _usage.set(usage)
    return usage


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


def _cache_path(method: str, url: str, params: Any, body: Any) -> Path:
    key = json.dumps([method, url, params, body], sort_keys=True, ensure_ascii=False)
    folder = data_dir() / "cache"
    folder.mkdir(exist_ok=True)
    return folder / f"{hashlib.sha256(key.encode()).hexdigest()}.json"


def _cache_get(path: Path) -> Any | None:
    try:
        if time.time() - path.stat().st_mtime < CACHE_TTL_SECONDS:
            return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    return None


def _cache_put(path: Path, data: Any) -> None:
    try:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass  # caching is best effort


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
    path = _cache_path(method, url, params, body)
    cached = _cache_get(path)
    if cached is not None:
        _count(kind, cached)
        usage = _usage.get()
        if usage:
            usage.cached += 1
        return cached
    response = await http.request(method, url, headers=headers, params=params, json=body, timeout=timeout)
    response.raise_for_status()
    data = response.json()
    _cache_put(path, data)
    _count(kind, data)
    return data
