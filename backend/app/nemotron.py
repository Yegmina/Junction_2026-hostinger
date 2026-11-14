"""NVIDIA Nemotron as an independent auditor of the Gemini shortlist.

A second model family reads all evidence (Cala + live web) and the shortlist, and judges each
investor: supported, weak or contradicted. Contradicted leads drop to the bottom (a feedback
loop on the first model's output). Before the call, a deterministic citation check tells the
auditor which cited facts actually name each investor, so it reasons from facts, not wording.
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any

import httpx

from app.cala import EvidenceBundle
from app.calahttp import count_web
from app.config import Settings
from app.models import Audit, Committee, StartupProfile

NVIDIA_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
AUDIT_TIMEOUT = 90.0
VERDICTS = ("supported", "weak", "contradicted")
AUDIT_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["audits", "summary"],
    "properties": {
        "audits": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["name", "verdict", "reason", "evidence"],
            "properties": {"name": {"type": "string"}, "verdict": {"type": "string", "enum": list(VERDICTS)},
                           "reason": {"type": "string"}, "evidence": {"type": "array", "items": {"type": "string"}}}}},
        "summary": {"type": "string"},
    },
}

AUDIT_PROMPT = (
    "You are an independent due-diligence auditor checking another AI's investor shortlist for a startup "
    "fundraise. You get the startup, numbered evidence (E1, E2, ...) from the Cala knowledge graph and the live "
    "web, and the shortlist with graph verification, live web data and a citation check. For EACH shortlisted "
    "investor decide: 'supported' (evidence shows it invests at this stage and sector, recently, with no "
    "conflict), 'weak' (plausible but thin, old or indirect evidence), or 'contradicted' (evidence shows a "
    "conflict with a competitor, the wrong stage or sector, or the cited facts do not concern this investor). "
    "The founder raises an equity round: a grant agency, public funding body or lender that does not take equity "
    "cannot lead it, so rate such a body 'weak' at best and say it is non-dilutive. "
    "Give a reason of at most 25 words naming the decisive fact, and the evidence ids you relied on. Then a "
    "'summary' of at most 30 words: which investor to pitch first and why. Use only the provided evidence. "
    "Return ONLY a JSON object of this shape, no markdown: "
    '{"audits":[{"name":"<investor name exactly as given>","verdict":"supported|weak|contradicted",'
    '"reason":"...","evidence":["E1"]}],"summary":"..."}'
)


def citation_check(committee: Committee, bundle: EvidenceBundle) -> dict[str, dict[str, list[str]]]:
    """For each target: cited facts that name it vs cited facts that do not."""
    by_id = {e.id: e.text.lower() for e in bundle.evidence}
    out = {}
    for target in committee.investorTargets:
        first = re.split(r"\s+", target.name.strip().lower())[0]
        naming = [eid for eid in target.evidence if first and first in by_id.get(eid, "")]
        out[target.name] = {"citedFactsNamingIt": naming,
                            "citedFactsNotNamingIt": [eid for eid in target.evidence if eid not in naming]}
    return out


def _shortlist(committee: Committee, checks: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for t in committee.investorTargets:
        v, w = t.verification, t.web
        rows.append({
            "name": t.name, "why": t.why, "fitScore": t.fitScore, "citedEvidence": t.evidence,
            "citationCheck": checks.get(t.name),
            "calaGraph": None if not v else {
                "verified": v.verified, "recentDeals": v.recentDeals, "latestDeal": v.latestDeal,
                "conflictsWithCompetitors": [c.company for c in v.conflicts],
                "ticket": v.ticket.text if v.ticket else "", "warmIntros": len(v.introPaths)},
            "liveWeb": None if not w else {
                "website": w.website, "focus": w.focus, "news": [n.snippet for n in w.news], "errors": w.errors},
        })
    return rows


def parse_json(text: str) -> dict[str, Any]:
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("Nemotron returned no JSON object")
    return json.loads(text[start:end + 1])


async def _chat(settings: Settings, payload: dict[str, Any]) -> str:
    body = {
        "model": settings.nemotron_model,
        "messages": [
            {"role": "system", "content": AUDIT_PROMPT},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        "temperature": 0.1,
        "max_tokens": 16384 if settings.nemotron_reasoning else 4096,
        # Measured on a 60-fact report: reasoning off answers in ~3 s, on in ~55 s with a similar audit.
        "chat_template_kwargs": {"enable_thinking": settings.nemotron_reasoning},
        # The server enforces the schema while generating: free-form JSON was malformed in ~1 of 3 runs.
        "response_format": {"type": "json_schema", "json_schema": {"name": "shortlist_audit", "schema": AUDIT_SCHEMA,
                                                                   "strict": True}},
    }
    headers = {"Authorization": f"Bearer {settings.nvidia_api_key}", "Accept": "application/json"}
    last: Exception | None = None
    async with httpx.AsyncClient(timeout=AUDIT_TIMEOUT) as http:
        for attempt in range(3):
            count_web("nemotron")
            try:
                response = await http.post(NVIDIA_URL, headers=headers, json=body)
                if response.status_code in (429, 500, 502, 503, 504):
                    raise httpx.HTTPStatusError("retryable", request=response.request, response=response)
                response.raise_for_status()
                choice = response.json()["choices"][0]
                if choice.get("finish_reason") == "length":
                    raise ValueError("Nemotron ran out of tokens before answering")
                return choice["message"].get("content") or ""
            except (httpx.HTTPStatusError, httpx.TransportError) as exc:
                if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code not in (429, 500, 502, 503, 504):
                    raise
                last = exc
                await asyncio.sleep(2 * (attempt + 1))
    raise last or ValueError("Nemotron call failed")


async def audit_shortlist(settings: Settings, profile: StartupProfile, committee: Committee,
                          bundle: EvidenceBundle) -> Committee:
    """Return the committee with an audit on each target, contradicted ones moved last."""
    checks = citation_check(committee, bundle)
    payload = {
        "startup": profile.model_dump(),
        "question": profile.question,
        "evidence": [{"id": e.id, "kind": e.kind, "text": e.text} for e in bundle.evidence],
        "shortlist": _shortlist(committee, checks),
    }
    try:
        raw = parse_json(await _chat(settings, payload))
    except ValueError:  # json.JSONDecodeError included: one more try before giving up
        raw = parse_json(await _chat(settings, payload))
    valid = {e.id for e in bundle.evidence}
    audits: dict[str, Audit] = {}
    for item in raw.get("audits") or []:
        name = str(item.get("name", "")).strip().lower()
        verdict = str(item.get("verdict", "")).strip().lower()
        if verdict not in VERDICTS:
            continue
        audits[name] = Audit(verdict=verdict, reason=str(item.get("reason", ""))[:300],
                             evidence=[e for e in item.get("evidence") or [] if e in valid][:6],
                             model=settings.nemotron_model)
    targets = [t.model_copy(update={"audit": audits.get(t.name.strip().lower())}) for t in committee.investorTargets]
    # Feedback loop: keep Gemini's order, but contradicted leads go last and weak ones after supported.
    rank = {"supported": 0, "weak": 1, "contradicted": 2}
    targets.sort(key=lambda t: rank.get(t.audit.verdict, 1) if t.audit else 1)
    return committee.model_copy(update={"investorTargets": targets,
                                        "auditSummary": str(raw.get("summary", ""))[:300],
                                        "auditModel": settings.nemotron_model})
