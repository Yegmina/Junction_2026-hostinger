"""Durable state on Aiven: PostgreSQL keeps saved reports, Valkey keeps the API cache and rate limits.

DATABASE_URL is an Aiven for PostgreSQL service URI, VALKEY_URL an Aiven for Valkey URI. Each is
optional: without it the same data lives in files under DATA_DIR (the limiter in memory), so local
runs and tests need no services. If a configured service fails, calls fall back to files and the
service is skipped for a minute: a report is never lost because a database blinked.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import secrets
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

log = logging.getLogger("unicorn.store")

RETRY_AFTER_SECONDS = 60.0  # how long a failed service is skipped before the next attempt
CONNECT_TIMEOUT = 5.0

SCHEMA = """
CREATE TABLE IF NOT EXISTS reports (
    run_id   text PRIMARY KEY,
    saved_at timestamptz NOT NULL,
    profile  jsonb NOT NULL,
    events   jsonb NOT NULL
);
CREATE TABLE IF NOT EXISTS report_investors (
    run_id       text NOT NULL REFERENCES reports(run_id) ON DELETE CASCADE,
    investor     text NOT NULL,
    display_name text NOT NULL,
    fit_score    real,
    verdict      text,
    verified     boolean,
    sector       text,
    stage        text,
    PRIMARY KEY (run_id, investor)
);
CREATE INDEX IF NOT EXISTS report_investors_by_investor ON report_investors (investor);
"""

# Sliding-window limiter, atomic on the server: drop old hits, refuse when full, else record this one.
RATE_SCRIPT = """
local key, now, window, limit = KEYS[1], tonumber(ARGV[1]), tonumber(ARGV[2]), tonumber(ARGV[3])
redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
if redis.call('ZCARD', key) >= limit then return 0 end
redis.call('ZADD', key, now, ARGV[4])
redis.call('EXPIRE', key, math.ceil(window))
return 1
"""


def data_dir() -> Path:
    path = Path(os.getenv("DATA_DIR") or Path(__file__).resolve().parents[1] / "data")
    path.mkdir(parents=True, exist_ok=True)
    return path


def database_url() -> str | None:
    return os.getenv("DATABASE_URL") or None


def valkey_url() -> str | None:
    return os.getenv("VALKEY_URL") or None


def backend_name(url: str | None, product: str) -> str:
    """'Aiven for PostgreSQL' when the URI points at Aiven, the product name otherwise, 'files' if unset."""
    if not url:
        return "files"
    host = urlparse(url).hostname or ""
    return f"Aiven for {product}" if host.endswith(".aivencloud.com") else product


def describe() -> dict[str, str]:
    return {"reports": backend_name(database_url(), "PostgreSQL"), "cache": backend_name(valkey_url(), "Valkey")}


# ---------- service health: skip a failing service for a while instead of waiting on it every call ----------

_down_until: dict[str, float] = {}


def _available(service: str) -> bool:
    return time.monotonic() >= _down_until.get(service, 0.0)


def _query_error(exc: BaseException) -> bool:
    """The server answered but rejected this one command: the service itself is fine."""
    try:
        import asyncpg
        from valkey.exceptions import ResponseError
    except ImportError:
        return False
    return isinstance(exc, (asyncpg.PostgresError, ResponseError))


def mark_down(service: str, what: str, exc: BaseException) -> None:
    """Fall back to files for this call; on a connection failure, skip the service for a while."""
    if _query_error(exc):
        log.warning("%s rejected (%s: %s); using files for this call", what, type(exc).__name__, exc)
        return
    if _available(service):  # log once per outage, not once per call
        log.warning("%s failed (%s: %s); using files for %.0f s", what, type(exc).__name__, exc, RETRY_AFTER_SECONDS)
    _down_until[service] = time.monotonic() + RETRY_AFTER_SECONDS


def jsonb(value: Any) -> str:
    """JSON text PostgreSQL accepts as jsonb: it rejects NUL characters, which scraped pages can contain."""
    def clean(item: Any) -> Any:
        if isinstance(item, str):
            return item.replace("\x00", "")
        if isinstance(item, dict):
            return {clean(k): clean(v) for k, v in item.items()}
        if isinstance(item, list):
            return [clean(v) for v in item]
        return item
    return json.dumps(clean(value), ensure_ascii=False)


def reset() -> None:
    """Forget clients and outages (tests, and after the event loop changes)."""
    _down_until.clear()
    _pools.clear()
    _pool_locks.clear()
    _valkeys.clear()


# ---------- clients, one per event loop (the app has one; tests start several) ----------

_pools: dict[int, Any] = {}
_pool_locks: dict[int, asyncio.Lock] = {}
_valkeys: dict[int, Any] = {}


async def pg_pool() -> Any | None:
    """The asyncpg pool, creating the schema on first use; None without DATABASE_URL or while it is down."""
    url = database_url()
    if not url or not _available("postgres"):
        return None
    loop = id(asyncio.get_running_loop())
    if loop in _pools:
        return _pools[loop]
    lock = _pool_locks.setdefault(loop, asyncio.Lock())
    async with lock:
        if loop not in _pools:
            import asyncpg

            pool = await asyncpg.create_pool(url, min_size=1, max_size=5, timeout=CONNECT_TIMEOUT, command_timeout=10)
            async with pool.acquire() as conn:
                await conn.execute(SCHEMA)
            _pools[loop] = pool
    return _pools[loop]


def valkey_client() -> Any | None:
    url = valkey_url()
    if not url or not _available("valkey"):
        return None
    loop = id(asyncio.get_running_loop())
    if loop not in _valkeys:
        import valkey.asyncio as valkey

        _valkeys[loop] = valkey.from_url(url, socket_timeout=3, socket_connect_timeout=CONNECT_TIMEOUT,
                                         health_check_interval=30)
    return _valkeys[loop]


async def close() -> None:
    loop = id(asyncio.get_running_loop())
    pool, client = _pools.pop(loop, None), _valkeys.pop(loop, None)
    if pool:
        await pool.close()
    if client:
        await client.aclose()


# ---------- API response cache (Cala 24 h, live web 1 h) ----------

def cache_key(method: str, url: str, params: Any, body: Any) -> str:
    key = json.dumps([method, url, params, body], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(key.encode()).hexdigest()


def _cache_file(key: str) -> Path:
    folder = data_dir() / "cache"
    folder.mkdir(exist_ok=True)
    return folder / f"{key}.json"


async def cache_get(key: str, ttl: float) -> Any | None:
    client = valkey_client()
    if client is not None:
        try:
            raw = await client.get(f"uo:cache:{key}")
            return json.loads(raw) if raw else None
        except Exception as exc:  # any Valkey error: read the file cache instead
            mark_down("valkey", "Valkey cache read", exc)
    path = _cache_file(key)
    try:
        if time.time() - path.stat().st_mtime < ttl:
            return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    return None


async def cache_put(key: str, data: Any, ttl: float) -> None:
    text = json.dumps(data, ensure_ascii=False)
    client = valkey_client()
    if client is not None:
        try:
            await client.set(f"uo:cache:{key}", text, ex=int(ttl))  # Valkey expires it; no sweeping needed
            return
        except Exception as exc:
            mark_down("valkey", "Valkey cache write", exc)
    try:
        path = _cache_file(key)
        tmp = path.with_suffix(f".{secrets.token_hex(4)}.tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass  # caching is best effort


# ---------- rate limit for live runs, shared by every backend worker when Valkey is set ----------

_hits: dict[str, deque[float]] = defaultdict(deque)


async def allow_hit(client_id: str, limit: int, window: float = 3600.0) -> bool:
    """Record one live run for this client; False when it already used `limit` runs in the window."""
    now = time.time()
    client = valkey_client()
    if client is not None:
        try:
            ok = await client.eval(RATE_SCRIPT, 1, f"uo:rate:{client_id}", now, window, limit,
                                   f"{now}-{secrets.token_hex(4)}")
            return bool(int(ok))
        except Exception as exc:
            mark_down("valkey", "Valkey rate limit", exc)
    hits = _hits[client_id]
    while hits and now - hits[0] > window:
        hits.popleft()
    if len(hits) >= limit:
        return False
    hits.append(now)
    return True
