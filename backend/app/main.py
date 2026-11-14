from __future__ import annotations

import hmac
import json
import logging
from contextlib import asynccontextmanager
from typing import Annotated, AsyncIterator

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from app.config import Settings, get_settings
from app.examples import find_example, list_examples, replay
from app.models import StartupProfile
from app.pipeline import run_analysis
from app import store
from app.runs import investor_history, load_run, save_run

log = logging.getLogger("unicorn_oracle")
settings_at_start = get_settings()



@asynccontextmanager
async def lifespan(_app: FastAPI):
    logging.getLogger("uvicorn.error").info("Storage: reports in %(reports)s, API cache in %(cache)s", store.describe())
    yield
    await store.close()


app = FastAPI(title="Unicorn Oracle API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings_at_start.cors_origins),
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Access-Code"],
)

def _client_ip(request: Request) -> str:
    return request.headers.get("x-real-ip") or (request.client.host if request.client else "unknown")


async def _rate_limit(request: Request, settings: Settings) -> None:
    if not await store.allow_hit(_client_ip(request), settings.rate_limit_per_hour):
        raise HTTPException(status_code=429, detail="Hourly analysis limit reached. Try again later.")


@app.get("/api/health")
async def health(settings: Annotated[Settings, Depends(get_settings)]):
    return {"status": "ok", "dataMode": settings.data_mode, "analysisMode": settings.analysis_mode,
            "accessCodeRequired": bool(settings.access_code), "storage": store.describe()}


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str):
    run = await load_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Report not found")
    return run


@app.get("/api/investors/history")
async def investors_history(names: Annotated[list[str], Query()], exclude: str = ""):
    """Shortlist history across all stored reports: counts and audit verdicts only, no founder data."""
    return await investor_history([n[:120] for n in names], exclude)


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
                await save_run(event.get("runId", ""), profile.model_dump(), recorded)
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
        await _rate_limit(request, settings)
    return StreamingResponse(
        _stream(settings, profile, example),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
