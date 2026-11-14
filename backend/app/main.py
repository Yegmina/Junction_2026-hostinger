from __future__ import annotations

import json
import logging
import time
from collections import defaultdict, deque
from typing import Annotated, AsyncIterator

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from app.config import Settings, get_settings
from app.models import StartupProfile
from app.pipeline import run_analysis

log = logging.getLogger("unicorn_oracle")
settings_at_start = get_settings()

app = FastAPI(title="Unicorn Oracle API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings_at_start.cors_origins),
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
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
    return {"status": "ok", "dataMode": settings.data_mode, "analysisMode": settings.analysis_mode}


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


async def _stream(settings: Settings, profile: StartupProfile) -> AsyncIterator[str]:
    try:
        async for event in run_analysis(settings, profile):
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
):
    _rate_limit(request, settings)
    return StreamingResponse(
        _stream(settings, profile),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
