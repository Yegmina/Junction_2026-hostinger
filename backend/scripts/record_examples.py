"""Record real pipeline runs for the landing-page examples into app/replays/<slug>.json.

Usage (needs CALA_API_KEY and GEMINI_API_KEY or OPENAI_API_KEY in the environment):
    python -m scripts.record_examples            # all examples
    python -m scripts.record_examples csrd-saas  # one example
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from datetime import datetime, timezone

from app.config import get_settings
from app.examples import EXAMPLES, REPLAY_DIR
from app.models import StartupProfile
from app.pipeline import run_analysis


async def record(example: dict) -> None:
    settings = get_settings()
    if settings.data_mode != "cala" or settings.analysis_mode == "demo":
        raise SystemExit("Recording needs live Cala and LLM keys; refusing to record demo data.")
    started = time.monotonic()
    events = []
    async for event in run_analysis(settings, StartupProfile(**example["profile"])):
        events.append({"t": round(time.monotonic() - started, 2), "event": event})
        print(f"  {events[-1]['t']:6.1f}s {event['type']} {event.get('id', '')}", flush=True)
    if events[-1]["event"]["type"] != "done" or any(e["event"]["type"] == "error" for e in events):
        raise SystemExit(f"Run for {example['slug']} did not finish cleanly; not saving.")
    REPLAY_DIR.mkdir(exist_ok=True)
    payload = {"recordedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"), "events": events}
    (REPLAY_DIR / f"{example['slug']}.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    print(f"saved {example['slug']} ({events[-1]['t']:.0f}s)")


async def main(slugs: list[str]) -> None:
    for example in EXAMPLES:
        if not slugs or example["slug"] in slugs:
            print(f"recording {example['slug']}")
            await record(example)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
