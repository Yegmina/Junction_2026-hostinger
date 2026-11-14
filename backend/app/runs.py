"""Finished runs saved to disk so a report has a shareable link (/r/<runId>)."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from app.calahttp import data_dir

RUN_ID = re.compile(r"^run-[0-9a-f]{10}$")


def _path(run_id: str):
    folder = data_dir() / "runs"
    folder.mkdir(exist_ok=True)
    return folder / f"{run_id}.json"


def save_run(run_id: str, profile: dict[str, Any], events: list[dict[str, Any]]) -> None:
    if not RUN_ID.match(run_id):
        return
    path = _path(run_id)
    if path.exists():
        return
    payload = {"runId": run_id, "savedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "profile": profile, "events": events}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def load_run(run_id: str) -> dict[str, Any] | None:
    if not RUN_ID.match(run_id):
        return None
    path = _path(run_id)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
