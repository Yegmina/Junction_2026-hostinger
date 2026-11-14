"""Example startups shown on the landing page, and replays of real recorded runs for them.

A replay re-streams the events of a real Cala + LLM run recorded earlier, with the original
timing compressed, so the demo is reliable and fast. Any edited input runs the live pipeline.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, AsyncIterator

from app.models import StartupProfile

REPLAY_DIR = Path(__file__).resolve().parent / "replays"
REPLAY_SECONDS = 9.0  # target length of a replay, whatever the original run took

EXAMPLES: list[dict[str, Any]] = [
    {
        "slug": "csrd-saas",
        "label": "CSRD reporting SaaS",
        "profile": {
            "name": "Ledgerly",
            "description": "AI assistant that automates EU sustainability (CSRD) reporting for small and mid-sized companies",
            "sector": "climate tech software",
            "country": "Finland",
            "stage": "seed",
            "targetAmountEur": 2500000,
            "horizonMonths": 12,
        },
    },
    {
        "slug": "defence-drones",
        "label": "Defence drones",
        "profile": {
            "name": "AeroRozum",
            "description": "Autonomous drones for border surveillance and defence logistics",
            "sector": "defence tech",
            "country": "Finland",
            "stage": "seed",
            "targetAmountEur": 3000000,
            "horizonMonths": 12,
        },
    },
    {
        "slug": "sme-lending",
        "label": "SME lending fintech",
        "profile": {
            "name": "Kassavirta",
            "description": "Embedded working-capital loans for Nordic SMEs, underwritten from accounting data",
            "sector": "fintech",
            "country": "Sweden",
            "stage": "series-a",
            "targetAmountEur": 8000000,
            "horizonMonths": 12,
        },
    },
]


def _replay_path(slug: str) -> Path:
    return REPLAY_DIR / f"{slug}.json"


def find_example(profile: StartupProfile) -> dict[str, Any] | None:
    """The example whose profile matches exactly and has a recorded replay."""
    data = profile.model_dump()
    for example in EXAMPLES:
        if StartupProfile(**example["profile"]).model_dump() == data and _replay_path(example["slug"]).exists():
            return example
    return None


def list_examples() -> list[dict[str, Any]]:
    return [{**e, "cached": _replay_path(e["slug"]).exists()} for e in EXAMPLES]


async def replay(example: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
    record = json.loads(_replay_path(example["slug"]).read_text(encoding="utf-8"))
    events: list[dict[str, Any]] = record["events"]
    total = max(events[-1]["t"], 0.001) if events else 1.0
    scale = min(1.0, REPLAY_SECONDS / total)
    previous = 0.0
    for item in events:
        await asyncio.sleep(max(0.0, (item["t"] - previous) * scale))
        previous = item["t"]
        event = dict(item["event"])
        if event.get("type") == "start":
            event["replay"] = {"recordedAt": record["recordedAt"], "originalSeconds": round(total, 1)}
        if event.get("type") == "step" and event.get("seconds") is not None:
            event["seconds"] = round(event["seconds"] * scale, 1)
        yield event
