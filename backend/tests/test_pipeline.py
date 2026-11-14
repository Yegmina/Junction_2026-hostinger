import json

import pytest
from fastapi.testclient import TestClient

from app.cala import EvidenceBundle, _ingest_query, _ingest_search
from app.config import get_settings
from app.demo import demo_committee, demo_evidence, demo_plan
from app.main import app
from app.models import Source, StartupProfile
from app.pipeline import normalize_committee, normalize_plan

PROFILE = {
    "name": "Testco",
    "description": "AI tooling that automates EU compliance reporting for SMEs",
    "sector": "RegTech",
    "country": "Finland",
    "stage": "seed",
    "targetAmountEur": 2000000,
    "horizonMonths": 12,
}


@pytest.fixture(autouse=True)
def no_keys(monkeypatch):
    monkeypatch.delenv("CALA_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)


def _events(response):
    return [json.loads(line[5:]) for line in response.text.split("\n") if line.startswith("data:")]


def test_health_reports_demo_modes():
    body = TestClient(app).get("/api/health").json()
    assert body == {"status": "ok", "dataMode": "demo", "analysisMode": "demo", "accessCodeRequired": False}


def test_analyze_streams_full_demo_run():
    response = TestClient(app).post("/api/analyze", json=PROFILE)
    assert response.status_code == 200
    events = _events(response)
    types = [e["type"] for e in events]
    assert types[0] == "start" and types[-1] == "done"
    finished = {e["id"] for e in events if e["type"] == "step" and e["state"] == "done"}
    assert finished == {s["id"] for s in next(e for e in events if e["type"] == "steps")["steps"]}
    for needed in ("steps", "step", "evidence", "plan", "committee"):
        assert needed in types

    plan = next(e for e in events if e["type"] == "plan")["plan"]
    assert len(plan["scenarios"]) == 4
    assert abs(sum(s["probability"] for s in plan["scenarios"]) - 1) < 1e-9
    event = plan["event"]
    expected = sum(s["probability"] * s["eventProbabilityIfScenario"] for s in plan["scenarios"])
    assert event["probability"] == pytest.approx(expected)
    assert event["low"] <= event["probability"] <= event["high"]


def test_invalid_profile_rejected():
    assert TestClient(app).post("/api/analyze", json={**PROFILE, "description": "short"}).status_code == 422


def test_plan_drops_unknown_citations_and_normalizes():
    profile = StartupProfile(**PROFILE)
    raw = demo_plan(profile)
    raw["scenarios"][0]["evidence"] = ["E1", "E999", "E1"]
    for s in raw["scenarios"]:
        s["probability"] = 2.0
    plan = normalize_plan(raw, {"E1", "E2"}, profile.question)
    assert plan.scenarios[0].evidence == ["E1"]
    assert all(s.probability == pytest.approx(0.25) for s in plan.scenarios)


def test_plan_requires_four_quadrants():
    raw = demo_plan(StartupProfile(**PROFILE))
    raw["scenarios"] = raw["scenarios"][:3]
    with pytest.raises(ValueError):
        normalize_plan(raw, set(), "q")


def test_committee_drops_investors_not_in_evidence():
    profile = StartupProfile(**PROFILE)
    bundle = demo_evidence(profile)
    raw = demo_committee(profile)
    raw["investorTargets"].append({"name": "Invented Capital", "why": "x", "fitScore": 1, "evidence": []})
    names = [t.name for t in normalize_committee(raw, bundle).investorTargets]
    assert "Invented Capital" not in names
    assert names[0] == "Aurora Ventures (fictional)"


def test_cala_payload_ingestion():
    bundle = EvidenceBundle()
    _ingest_search(bundle, "funding", {
        "content": "summary",
        "context": [{"id": "x", "content": "Acme raised 5M seed", "origins": [
            {"source": {"name": "Src", "url": "https://s"}, "document": {"name": "Doc", "url": "https://d"}}]}],
    })
    _ingest_query(bundle, "market", {"results": [{"name": "Acme", "total_funding": "5M", "investors": None}]})
    assert [e.id for e in bundle.evidence] == ["E1", "E2", "E3"]
    assert bundle.evidence[0].text == "Cala answer: summary"
    assert bundle.evidence[1].sources == [Source(name="Doc", url="https://d")]
    assert bundle.evidence[2].text == "name: Acme; total_funding: 5M"
    assert bundle.summaries["funding"] == "summary"


def test_settings_modes(monkeypatch):
    monkeypatch.setenv("CALA_API_KEY", "k")
    assert get_settings().data_mode == "cala"


def test_live_data_without_openai_skips_demo_analysis(monkeypatch):
    async def fake_stream(settings, profile):
        bundle = EvidenceBundle(mode="cala")
        bundle.add("funding", "Real fact", [Source(name="S")])
        yield {"kind": "funding", "state": "done", "facts": 1, "seconds": 1.0, "evidence": bundle.evidence}
        yield bundle

    monkeypatch.setattr("app.pipeline.stream_evidence", fake_stream)
    types = [e["type"] for e in _events(TestClient(app).post("/api/analyze", json=PROFILE))]
    assert "plan" not in types and "committee" not in types
    assert types[-2:] == ["error", "done"]


def test_evidence_titles_are_short_and_human():
    bundle = EvidenceBundle()
    bundle.add("funding", "Acme raised 5M. More text here.", [Source(name="Acme raises €5M seed to scale grid software", url="https://x")])
    bundle.add("funding", "Short fact without good source. Second sentence.", [Source(name="Cala")])
    assert bundle.evidence[0].title == "Acme raises €5M seed to scale grid software"
    assert bundle.evidence[1].title == "Short fact without good source"
