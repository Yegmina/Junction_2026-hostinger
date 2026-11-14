from __future__ import annotations

import hmac
import json
import logging
import time
from collections import defaultdict, deque
from typing import Annotated, AsyncIterator

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from app.config import Settings, get_settings
from app.examples import find_example, list_examples, replay
from app.models import StartupProfile
from app.pipeline import run_analysis
from app.runs import load_run, save_run

log = logging.getLogger("unicorn_oracle")
settings_at_start = get_settings()

app = FastAPI(title="Unicorn Oracle API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings_at_start.cors_origins),
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Access-Code"],
)

_hits: dict[str, deque[float]] = defaultdict(deque)


def _client_ip(request: Request) -> str:
    return request.headers.get("x-real-ip") or (request.client.host if request.client else "unknown")


def _rate_limit(request: Request, settings: Settings) -> None:
    now = time.time()
    hits = _hits[_client_ip(request)]
    while hits and now - hits[0] > 3600:
        hits.popleft()
    if len(hits) >= settings.rate_limit_per_hour:
        raise HTTPException(status_code=429, detail="Hourly analysis limit reached. Try again later.")
    hits.append(now)


@app.get("/api/health")
async def health(settings: Annotated[Settings, Depends(get_settings)]):
    return {"status": "ok", "dataMode": settings.data_mode, "analysisMode": settings.analysis_mode,
            "accessCodeRequired": bool(settings.access_code)}


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str):
    run = load_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Report not found")
    return run


@app.get("/api/examples")
async def examples():
    return {"examples": list_examples()}


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


async def _stream(settings: Settings, profile: StartupProfile, example: dict | None = None) -> AsyncIterator[str]:
    try:
        events = replay(example) if example else run_analysis(settings, profile)
        recorded: list[dict] = []
        async for event in events:
            recorded.append(event)
            if event.get("type") == "done":
                # Save before announcing done, so the share link works as soon as the UI shows it.
                save_run(event.get("runId", ""), profile.model_dump(), recorded)
            yield _sse(event)
    except httpx.HTTPStatusError as exc:
        host = exc.request.url.host
        log.warning("Upstream %s returned %s: %s", host, exc.response.status_code, exc.response.text[:500])
        yield _sse({"type": "error", "message": f"Upstream service {host} returned HTTP {exc.response.status_code}."})
    except httpx.HTTPError as exc:
        log.warning("Upstream request failed: %r", exc)
        yield _sse({"type": "error", "message": "An upstream service did not respond. Please retry."})
    except (ValueError, KeyError) as exc:
        log.warning("Analysis output rejected: %s", exc)
        yield _sse({"type": "error", "message": f"The analysis output was invalid: {exc}"})


@app.post("/api/analyze")
async def analyze(
    profile: StartupProfile,
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    x_access_code: Annotated[str | None, Header()] = None,
):
    # Unedited example profiles replay a recorded real run; anything else runs live.
    example = find_example(profile)
    if not example:
        if settings.access_code and not hmac.compare_digest((x_access_code or "").encode(), settings.access_code.encode()):
            raise HTTPException(status_code=401, detail="access_code_required")
        _rate_limit(request, settings)
    return StreamingResponse(
        _stream(settings, profile, example),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
