"""Aiven storage: reports in PostgreSQL, cache and rate limits in Valkey, and the file fallback.

The service tests run when TEST_DATABASE_URL / TEST_VALKEY_URL are set (CI starts PostgreSQL 18 and
Valkey 9 containers; Aiven runs the same engines). The fallback tests always run.
"""
import asyncio
import os
import secrets
import time

import pytest
from fastapi.testclient import TestClient

from app import runs, store
from app.main import app

PG = os.getenv("TEST_DATABASE_URL")
VK = os.getenv("TEST_VALKEY_URL")
needs_pg = pytest.mark.skipif(not PG, reason="set TEST_DATABASE_URL to test PostgreSQL")
needs_vk = pytest.mark.skipif(not VK, reason="set TEST_VALKEY_URL to test Valkey")


def _run_id() -> str:
    return f"run-{secrets.token_hex(5)}"


def _events(run_id: str, targets: list[tuple[str, str]]) -> list[dict]:
    committee = {"investorTargets": [
        {"name": name, "fitScore": 0.8, "why": "", "evidence": [], "audit": {"verdict": verdict},
         "verification": {"verified": True}} for name, verdict in targets]}
    return [{"type": "start", "runId": run_id}, {"type": "committee", "committee": {"investorTargets": []}},
            {"type": "committee", "committee": committee}, {"type": "done", "runId": run_id}]


def test_shortlist_rows_use_the_final_committee_and_skip_duplicates():
    rows = runs.shortlist_rows("run-0000000001", {"sector": "fintech", "stage": "seed"},
                               _events("run-0000000001", [("Inventure", "supported"), (" inventure ", "weak"),
                                                          ("Maki.vc", "contradicted")]))
    assert [(r[1], r[2], r[4]) for r in rows] == [("inventure", "Inventure", "supported"),
                                                  ("maki.vc", "Maki.vc", "contradicted")]
    assert rows[0][6:] == ("fintech", "seed")


def test_unreachable_database_falls_back_to_files(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@127.0.0.1:9/none")
    run_id = _run_id()

    async def go():
        where = await runs.save_run(run_id, {"name": "A"}, _events(run_id, [("Inventure", "supported")]))
        return where, await runs.load_run(run_id), await runs.investor_history(["Inventure"])

    where, loaded, history = asyncio.run(go())
    assert where == "files" and loaded["profile"] == {"name": "A"}
    assert history == {"available": False, "investors": {}}


def test_unreachable_valkey_falls_back_to_files_and_memory(monkeypatch):
    monkeypatch.setenv("VALKEY_URL", "redis://127.0.0.1:9")

    async def go():
        await store.cache_put("k", {"v": 1}, 60)
        allowed = [await store.allow_hit("1.2.3.4", 2) for _ in range(3)]
        return await store.cache_get("k", 60), allowed

    assert asyncio.run(go()) == ({"v": 1}, [True, True, False])


def test_health_names_the_storage(monkeypatch):
    assert TestClient(app).get("/api/health").json()["storage"] == {"reports": "files", "cache": "files"}
    monkeypatch.setenv("DATABASE_URL", "postgres://avnadmin:x@pg-oracle-junction.k.aivencloud.com:12345/defaultdb")
    monkeypatch.setenv("VALKEY_URL", "rediss://default:x@valkey-oracle-junction.k.aivencloud.com:12346")
    assert store.describe() == {"reports": "Aiven for PostgreSQL", "cache": "Aiven for Valkey"}


@needs_pg
def test_postgres_stores_reports_and_answers_investor_history(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", PG)
    first, second, third = _run_id(), _run_id(), _run_id()
    unique = f"Fund {secrets.token_hex(3)}"
    nul_event = {"type": "evidence", "evidence": [{"text": "scraped\x00page"}]}

    async def go():
        assert await runs.save_run(first, {"sector": "fintech", "stage": "seed"},
                                   [nul_event, *_events(first, [(unique, "supported")])]) == "postgres"
        await runs.save_run(first, {"sector": "changed"}, [])  # a run id is stored once
        await runs.save_run(second, {"sector": "climate tech", "stage": "seed"},
                            _events(second, [(unique.upper(), "weak")]))
        await runs.save_run(third, {"sector": "fintech", "stage": "seed"},
                            _events(third, [(unique, "contradicted")]))
        loaded = await runs.load_run(first)
        history = await runs.investor_history([unique, "Nobody Capital"], exclude_run=third)
        await store.close()
        return loaded, history

    loaded, history = asyncio.run(go())
    assert loaded["profile"]["sector"] == "fintech" and loaded["events"][-1]["type"] == "done"
    assert loaded["events"][0]["evidence"][0]["text"] == "scrapedpage"  # NUL removed, report still in PostgreSQL
    stats = history["investors"][runs.investor_key(unique)]
    assert history["available"] and "nobody capital" not in history["investors"]
    assert (stats["reports"], stats["supported"], stats["weak"], stats["contradicted"]) == (2, 1, 1, 0)
    assert sorted(stats["sectors"]) == ["climate tech", "fintech"]


@needs_pg
def test_file_reports_import_into_postgres(monkeypatch):
    run_id = _run_id()
    assert asyncio.run(runs.save_run(run_id, {"name": "Old"}, _events(run_id, []))) == "files"
    monkeypatch.setenv("DATABASE_URL", PG)
    store.reset()
    assert asyncio.run(runs.import_files()) == (1, 0)
    (store.data_dir() / "runs" / f"{run_id}.json").unlink()
    store.reset()
    assert asyncio.run(runs.load_run(run_id))["profile"] == {"name": "Old"}


@needs_vk
def test_valkey_cache_expires_and_limits_are_shared(monkeypatch):
    monkeypatch.setenv("VALKEY_URL", VK)
    key, client_id = secrets.token_hex(8), f"ip-{secrets.token_hex(4)}"

    async def go():
        await store.cache_put(key, {"answer": 42}, 1)
        hit = await store.cache_get(key, 1)
        ttl = await store.valkey_client().ttl(f"uo:cache:{key}")
        allowed = [await store.allow_hit(client_id, 3, window=60) for _ in range(4)]
        await store.close()
        return hit, ttl, allowed

    hit, ttl, allowed = asyncio.run(go())
    assert hit == {"answer": 42} and 0 < ttl <= 1
    assert allowed == [True, True, True, False]
    assert not list(store.data_dir().glob("cache/*.json"))  # nothing went to the file cache
    time.sleep(1.2)
    store.reset()

    async def expired():
        value = await store.cache_get(key, 1)
        await store.close()
        return value

    assert asyncio.run(expired()) is None  # Valkey dropped it after its TTL
