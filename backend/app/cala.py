"""Cala data layer client and evidence gathering.

Every fact the analysis may cite becomes an `Evidence` item with a stable id (E1, E2, ...)
and the sources Cala returned for it. Later steps may only cite these ids.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

import httpx

from app.config import Settings
from app.models import Evidence, Source, StartupProfile

MAX_FACTS_PER_SEARCH = 8
MAX_ROWS = 10
MAX_TEXT = 1200
MAX_SUMMARY = 2500


class CalaClient:
    def __init__(self, settings: Settings, client: httpx.AsyncClient):
        self._base = settings.cala_base_url
        self._client = client
        self._headers = {"X-API-KEY": settings.cala_api_key or "", "Content-Type": "application/json"}

    async def search(self, text: str) -> dict[str, Any]:
        """Natural-language answer with sourced context facts (POST /v1/knowledge/search)."""
        response = await self._client.post(
            f"{self._base}/v1/knowledge/search",
            headers=self._headers,
            json={"input": text, "explainability": False, "return_entities": True},
        )
        response.raise_for_status()
        return response.json()

    async def query(self, text: str) -> dict[str, Any]:
        """Structured rows (POST /v1/knowledge/query)."""
        response = await self._client.post(
            f"{self._base}/v1/knowledge/query",
            headers=self._headers,
            json={"input": text, "return_entities": True},
        )
        response.raise_for_status()
        return response.json()


@dataclass
class EvidenceBundle:
    evidence: list[Evidence] = field(default_factory=list)
    summaries: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    mode: str = "cala"

    def add(self, kind: str, text: str, sources: list[Source], limit: int = MAX_TEXT, title: str = "") -> None:
        text = " ".join(str(text).split())[:limit]
        if not text or any(item.text == text for item in self.evidence):
            return
        title = title or _title_from(text, sources)
        self.evidence.append(
            Evidence(id=f"E{len(self.evidence) + 1}", kind=kind, title=title, text=text, sources=sources)
        )


def _clip(text: str, limit: int = 110) -> str:
    text = " ".join(str(text).replace("#", " ").replace("*", " ").split())
    return text if len(text) <= limit else text[: limit - 1].rsplit(" ", 1)[0] + "…"


def _title_from(text: str, sources: list[Source]) -> str:
    """Short human title: the source document name when it is informative, else the first sentence."""
    for source in sources:
        name = source.name.strip()
        if len(name) >= 20 and name.lower() not in {"cala", "cala knowledge query"}:
            return _clip(name)
    return _clip(text.split(". ")[0])


def _region(profile: StartupProfile) -> str:
    return profile.country if profile.country.lower() != "europe" else "Europe"


def evidence_queries(profile: StartupProfile) -> list[tuple[str, str, str]]:
    """(kind, endpoint, input) triples sent to Cala."""
    region = _region(profile)
    stage = profile.stage.replace("-", " ")
    return [
        (
            "competitor",
            "search",
            f"Which startups and companies build {profile.description[:300]} in the {profile.sector} sector "
            f"in {region}? Give names, total funding raised and their latest funding round.",
        ),
        (
            "funding",
            "search",
            f"Which funding rounds did {profile.sector} startups in {region} raise in the last 24 months? "
            f"Include amount, round type, date and lead investors.",
        ),
        (
            "investor",
            "search",
            f"Which investors led {stage} rounds in {profile.sector} companies in {region} since 2024, "
            f"and which companies did they back?",
        ),
        (
            "market",
            "query",
            f"companies.industry={profile.sector}.location={region}.founded_year>=2015"
            f".order_by=total_funding DESC.limit={MAX_ROWS}"
            f".return(name, total_funding, last_funding_round, investors)",
        ),
    ]


def _sources_from_origins(origins: list[dict[str, Any]] | None) -> list[Source]:
    sources: list[Source] = []
    for origin in origins or []:
        src = origin.get("source") or {}
        doc = origin.get("document") or {}
        name = doc.get("name") or src.get("name") or "Cala"
        url = doc.get("url") or src.get("url")
        if not any(s.name == name and s.url == url for s in sources):
            sources.append(Source(name=str(name), url=url))
    return sources[:3]


def _ingest_search(bundle: EvidenceBundle, kind: str, payload: dict[str, Any]) -> None:
    context = payload.get("context") or []
    if payload.get("content"):
        # Cala's synthesised answer, cited with the documents it was built from.
        summary = str(payload["content"])[:MAX_SUMMARY]
        bundle.summaries[kind] = summary
        answer_sources = _sources_from_origins([o for fact in context for o in fact.get("origins") or []])
        bundle.add(kind, f"Cala answer: {summary}", answer_sources or [Source(name="Cala")], limit=MAX_SUMMARY,
                   title=f"Cala summary: {QUERY_LABELS.get(kind, kind).lower()}")
    seen_docs: set[str] = set()
    for fact in context:
        sources = _sources_from_origins(fact.get("origins")) or [Source(name="Cala")]
        doc_key = sources[0].url or sources[0].name
        if doc_key in seen_docs:
            continue
        seen_docs.add(doc_key)
        bundle.add(kind, fact.get("content", ""), sources)
        if len(seen_docs) >= MAX_FACTS_PER_SEARCH:
            break


def _ingest_query(bundle: EvidenceBundle, kind: str, payload: dict[str, Any]) -> None:
    for row in (payload.get("results") or [])[:MAX_ROWS]:
        if not isinstance(row, dict):
            continue
        text = "; ".join(f"{key}: {value}" for key, value in row.items() if value not in (None, "", []))
        title = " · ".join(str(row[k]) for k in ("name", "total_funding", "last_funding_round") if row.get(k))
        bundle.add(kind, text, [Source(name="Cala knowledge query")], title=_clip(title) if title else "")


QUERY_LABELS = {
    "competitor": "Competitors building something similar",
    "funding": "Recent funding rounds in your sector",
    "investor": "Investors leading rounds at your stage",
    "market": "Structured list of top-funded companies",
}


async def stream_evidence(settings: Settings, profile: StartupProfile) -> AsyncIterator[dict[str, Any] | EvidenceBundle]:
    """Yields one progress dict per Cala query as it finishes, then the final EvidenceBundle."""
    queries = evidence_queries(profile)
    if not settings.cala_api_key:
        from app.demo import demo_evidence

        bundle = demo_evidence(profile)
        for kind, _, _ in queries:
            facts = sum(1 for e in bundle.evidence if e.kind == kind)
            yield {"kind": kind, "state": "done", "facts": facts, "seconds": 0.0, "evidence": bundle.evidence}
        yield bundle
        return

    bundle = EvidenceBundle(mode="cala")
    started = time.monotonic()

    async def run(index: int, cala: CalaClient) -> tuple[int, Any]:
        _, endpoint, text = queries[index]
        try:
            return index, await (cala.search(text) if endpoint == "search" else cala.query(text))
        except Exception as exc:  # reported per query, the others still count
            return index, exc

    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as http:
        cala = CalaClient(settings, http)
        for next_done in asyncio.as_completed([run(i, cala) for i in range(len(queries))]):
            index, result = await next_done
            kind, endpoint, _ = queries[index]
            before = len(bundle.evidence)
            if isinstance(result, Exception):
                status = getattr(getattr(result, "response", None), "status_code", None)
                bundle.errors.append(f"Cala {endpoint} for {kind} failed" + (f" (HTTP {status})" if status else ""))
                state = "failed"
            else:
                (_ingest_search if endpoint == "search" else _ingest_query)(bundle, kind, result)
                state = "done"
            yield {
                "kind": kind,
                "state": state,
                "facts": len(bundle.evidence) - before,
                "seconds": round(time.monotonic() - started, 1),
                "evidence": bundle.evidence,
            }
    yield bundle


async def gather_evidence(settings: Settings, profile: StartupProfile) -> EvidenceBundle:
    bundle = EvidenceBundle()
    async for item in stream_evidence(settings, profile):
        if isinstance(item, EvidenceBundle):
            bundle = item
    return bundle
