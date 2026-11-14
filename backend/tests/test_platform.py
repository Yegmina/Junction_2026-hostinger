"""Cache and usage counting, saved reports, access code, intro paths and ticket matching."""
import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app import calahttp, store
from app.graph import GraphEntity, company_people, pick_intro_companies, ticket_match
from app.main import app
from app.runs import load_run, save_run
from tests.test_pipeline import PROFILE, _events


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    for key in ("CALA_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "ACCESS_CODE", "DATABASE_URL", "VALKEY_URL"):
        monkeypatch.delenv(key, raising=False)
    store.reset()


def test_cala_request_caches_and_counts():
    calls = []

    def handler(request):
        calls.append(request.url)
        if request.url.path.endswith("search"):
            return httpx.Response(200, json={"content": "answer"})
        return httpx.Response(200, json={"relationships": {"incoming": {"FOUNDED": [{"id": "p"}, {"id": "q"}]}}})

    async def go():
        usage = calahttp.start_usage()
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            for _ in range(2):
                await calahttp.cala_request(http, "POST", "https://x/v1/entities/1", kind="entity",
                                            headers={}, body={"a": 1})
            await calahttp.cala_request(http, "POST", "https://x/v1/knowledge/search", kind="search",
                                        headers={}, body={"input": "q"})
        return usage

    usage = asyncio.run(go())
    assert len(calls) == 2  # second identical entity call came from the disk cache
    assert usage.as_dict() == {"searches": 1, "queries": 0, "entityLookups": 2, "relationships": 4, "cached": 1,
                               "webSearches": 0, "webScrapes": 0, "contextDev": 0, "nemotron": 0}


def test_demo_run_reports_usage_and_is_saved_for_sharing():
    client = TestClient(app)
    events = _events(client.post("/api/analyze", json=PROFILE))
    types = [e["type"] for e in events]
    assert types[-2:] == ["usage", "done"]
    run_id = events[-1]["runId"]
    saved = client.get(f"/api/runs/{run_id}").json()
    assert saved["profile"]["name"] == PROFILE["name"]
    assert [e["type"] for e in saved["events"]] == types


def test_run_ids_are_validated():
    assert TestClient(app).get("/api/runs/..%2Fetc").status_code == 404
    assert asyncio.run(load_run("../../etc/passwd")) is None
    assert asyncio.run(save_run("not-a-run", {}, [])) == ""
    assert asyncio.run(load_run("not-a-run")) is None


def test_access_code_guards_live_runs(monkeypatch):
    monkeypatch.setenv("ACCESS_CODE", "s3cret")
    client = TestClient(app)
    assert client.get("/api/health").json()["accessCodeRequired"] is True
    denied = client.post("/api/analyze", json=PROFILE)
    assert denied.status_code == 401 and denied.json()["detail"] == "access_code_required"
    assert client.post("/api/analyze", json=PROFILE, headers={"X-Access-Code": "wrong"}).status_code == 401
    assert client.post("/api/analyze", json=PROFILE, headers={"X-Access-Code": "s3cret"}).status_code == 200


SEED_DEALS = [
    {"date": "2024-04-02", "label": "SEED", "value": 5_000_000.0, "units": "EUR"},
    {"date": "2023-06-15", "label": "SEED", "value": 1_000_000.0, "units": "EUR"},
    {"date": "2026-04-24", "label": "SERIES_A", "value": None, "units": None},
]


def test_ticket_match_yes_partial_no_unknown():
    yes = ticket_match(SEED_DEALS, "seed", 2_500_000)
    assert yes["match"] == "yes" and yes["stages"] == ["seed", "series-a"]
    assert ticket_match(list(reversed(SEED_DEALS)), "seed", 2e6)["stages"] == ["seed", "series-a"]
    assert yes["minEur"] == 1_000_000 and yes["maxEur"] == 5_000_000
    assert "€1M–€5M" in yes["text"]
    assert ticket_match(SEED_DEALS, "growth", 3_000_000)["match"] == "partial"
    assert ticket_match(SEED_DEALS, "growth", 200_000_000)["match"] == "no"
    assert ticket_match([], "seed", 1_000_000)["match"] == "unknown"
    usd = ticket_match([{"date": "", "label": "SERIES_B", "value": 100_000_000.0, "units": "USD"}], "series-b", 90_000_000)
    assert usd["maxEur"] == pytest.approx(92_000_000) and usd["match"] == "yes"


def test_intro_companies_prefer_evidence_mentions():
    portfolio = [GraphEntity(str(i), n, "Company") for i, n in enumerate(["Verda", "Kova Labs", "Solu Oy", "Metroc"])]
    picked = pick_intro_companies(portfolio, "metroc raised a seed round with solu", limit=3)
    assert [c.name for c in picked] == ["Solu Oy", "Metroc", "Verda"]


class FakeClient:
    async def relationships(self, entity_id):
        return {"incoming": ["FOUNDED", "IS_CEO_OF", "WORKS_AT"]}

    async def retrieve(self, entity_id, body):
        assert set(body["relationships"]["incoming"]) == {"FOUNDED", "IS_CEO_OF"}
        return {"relationships": {"incoming": {
            "IS_CEO_OF": [{"id": "p1", "name": "Ruben Bryon", "entity_type": "Person"}],
            "FOUNDED": [{"id": "p1", "name": "Ruben Bryon", "entity_type": "Person"},
                        {"id": "o1", "name": "Some Holding", "entity_type": "Company"}],
        }}}


def test_company_people_dedupes_and_prefers_founder_role():
    people = asyncio.run(company_people(FakeClient(), GraphEntity("c", "Verda", "Company")))
    assert people == [("Ruben Bryon", "founder", "Verda")]
