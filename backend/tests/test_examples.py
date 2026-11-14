import json

from fastapi.testclient import TestClient

import app.examples as examples
from app.main import app

STEP_EVENTS = [
    {"t": 0.0, "event": {"type": "start", "runId": "r1", "question": "q", "dataMode": "cala", "analysisMode": "gemini"}},
    {"t": 30.0, "event": {"type": "step", "id": "cala:funding", "state": "done", "seconds": 30.0}},
    {"t": 60.0, "event": {"type": "done", "runId": "r1"}},
]


def _events(response):
    return [json.loads(line[5:]) for line in response.text.split("\n") if line.startswith("data:")]


def test_unedited_example_replays_recorded_run(tmp_path, monkeypatch):
    monkeypatch.setattr(examples, "REPLAY_DIR", tmp_path)
    monkeypatch.setattr(examples, "REPLAY_SECONDS", 0.06)
    example = examples.EXAMPLES[0]
    (tmp_path / f"{example['slug']}.json").write_text(json.dumps({"recordedAt": "2026-11-14T10:00:00+00:00", "events": STEP_EVENTS}))

    events = _events(TestClient(app).post("/api/analyze", json=example["profile"]))
    assert [e["type"] for e in events] == ["start", "step", "done"]
    assert events[0]["replay"] == {"recordedAt": "2026-11-14T10:00:00+00:00", "originalSeconds": 60.0}
    assert events[1]["seconds"] == 0.0  # 30s scaled to the short replay
    assert TestClient(app).get("/api/examples").json()["examples"][0]["cached"] is True


def test_edited_example_runs_live_pipeline(tmp_path, monkeypatch):
    monkeypatch.delenv("CALA_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(examples, "REPLAY_DIR", tmp_path)
    example = examples.EXAMPLES[0]
    (tmp_path / f"{example['slug']}.json").write_text(json.dumps({"recordedAt": "x", "events": STEP_EVENTS}))

    events = _events(TestClient(app).post("/api/analyze", json={**example["profile"], "targetAmountEur": 3000000}))
    assert "replay" not in events[0]
    assert any(e["type"] == "plan" for e in events)
