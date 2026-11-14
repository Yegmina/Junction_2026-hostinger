"""Evidence -> drivers -> 2x2 scenarios -> round probability -> investor committee."""
from __future__ import annotations

import asyncio
import math
import time
import uuid
from typing import Any, AsyncIterator

from app.cala import QUERY_LABELS, EvidenceBundle, stream_evidence
from app.config import Settings
from app.demo import demo_committee, demo_plan
from app.llm import PESTEL_ENUM, COMMITTEE_PROMPT, COMMITTEE_SCHEMA, PLAN_PROMPT, PLAN_SCHEMA, structured_call
from app.verification import CompetitorMap, add_competitor_facts, map_competitors, verify_targets
from app.models import (
    Axis,
    Committee,
    CommitteeMember,
    Driver,
    EventBreakdown,
    EventEstimate,
    InvestorTarget,
    Scenario,
    ScenarioPlan,
    StartupProfile,
)

QUADRANTS = [("low", "low"), ("low", "high"), ("high", "low"), ("high", "high")]


def clamp(value: Any, low: float = 0.0, high: float = 1.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return low
    if math.isnan(number):
        return low
    return max(low, min(high, number))


def _refs(ids: list[str], valid: set[str]) -> list[str]:
    seen: list[str] = []
    for ref in ids or []:
        ref = str(ref).strip()
        if ref in valid and ref not in seen:
            seen.append(ref)
    return seen


def estimate_event(question: str, scenarios: list[Scenario], explanation: str) -> EventEstimate:
    """P(event) = sum_s P(s) * P(event | s); the band is the spread across scenarios."""
    probability = sum(s.probability * s.eventProbabilityIfScenario for s in scenarios)
    variance = sum(s.probability * (s.eventProbabilityIfScenario - probability) ** 2 for s in scenarios)
    spread = math.sqrt(variance)
    return EventEstimate(
        question=question,
        probability=clamp(probability),
        low=clamp(probability - spread),
        high=clamp(probability + spread),
        breakdown=[
            EventBreakdown(
                scenarioId=s.id,
                weight=s.probability,
                conditional=s.eventProbabilityIfScenario,
                contribution=s.probability * s.eventProbabilityIfScenario,
            )
            for s in scenarios
        ],
        explanation=explanation,
    )


def normalize_plan(raw: dict[str, Any], valid: set[str], question: str) -> ScenarioPlan:
    drivers = [
        Driver(
            id=str(d.get("id") or f"D{i + 1}"),
            name=str(d.get("name", ""))[:120],
            pestel=d.get("pestel") if d.get("pestel") in PESTEL_ENUM else "economic",
            description=str(d.get("description", ""))[:400],
            impact=clamp(d.get("impact")),
            uncertainty=clamp(d.get("uncertainty")),
            direction=d.get("direction") if d.get("direction") in ("tailwind", "headwind", "mixed") else "mixed",
            evidence=_refs(d.get("evidence", []), valid),
        )
        for i, d in enumerate(raw.get("drivers", [])[:8])
    ]
    if not drivers:
        raise ValueError("Analysis returned no drivers")

    axes = [Axis(**{k: str(a.get(k, "")) for k in ("driverId", "name", "lowLabel", "highLabel")}) for a in raw.get("axes", [])[:2]]
    if len(axes) < 2:
        ranked = sorted(drivers, key=lambda d: d.impact * d.uncertainty, reverse=True)[:2]
        axes = [Axis(driverId=d.id, name=d.name, lowLabel="Low", highLabel="High") for d in ranked]
        if len(axes) < 2:
            raise ValueError("Analysis returned fewer than two scenario axes")

    by_quadrant: dict[tuple[str, str], dict[str, Any]] = {}
    for item in raw.get("scenarios", []):
        position = tuple(item.get("position") or [])
        if position in QUADRANTS and position not in by_quadrant:
            by_quadrant[position] = item
    if len(by_quadrant) != 4:
        raise ValueError("Analysis must return one scenario per quadrant")

    total = sum(clamp(by_quadrant[q].get("probability")) for q in QUADRANTS) or 1.0
    scenarios = []
    for index, quadrant in enumerate(QUADRANTS):
        item = by_quadrant[quadrant]
        scenarios.append(
            Scenario(
                id=f"S{index + 1}",
                name=str(item.get("name", f"Scenario {index + 1}"))[:80],
                position=quadrant,
                oneLiner=str(item.get("oneLiner", ""))[:160],
                narrative=str(item.get("narrative", ""))[:600],
                probability=clamp(item.get("probability")) / total if total else 0.25,
                eventProbabilityIfScenario=clamp(item.get("eventProbabilityIfScenario")),
                signposts=[str(s)[:160] for s in item.get("signposts", [])[:4]],
                evidence=_refs(item.get("evidence", []), valid),
            )
        )
    event = estimate_event(question, scenarios, str(raw.get("eventExplanation", ""))[:800])
    return ScenarioPlan(verdict=str(raw.get("verdict", ""))[:300], drivers=drivers, axes=axes,
                        scenarios=scenarios, event=event)


def normalize_committee(raw: dict[str, Any], bundle: EvidenceBundle) -> Committee:
    valid = {e.id for e in bundle.evidence}
    corpus = " ".join(e.text.lower() for e in bundle.evidence)
    members = [
        CommitteeMember(
            persona=str(m.get("persona", ""))[:60],
            stance=m.get("stance") if m.get("stance") in ("back", "conditional", "pass") else "conditional",
            headline=str(m.get("headline", ""))[:140],
            argument=str(m.get("argument", ""))[:600],
            evidence=_refs(m.get("evidence", []), valid),
        )
        for m in raw.get("members", [])[:3]
    ]
    # Only keep investors that actually appear in Cala evidence: no invented names.
    targets = [
        InvestorTarget(
            name=str(t.get("name", ""))[:120],
            why=str(t.get("why", ""))[:400],
            fitScore=clamp(t.get("fitScore")),
            evidence=_refs(t.get("evidence", []), valid),
        )
        for t in raw.get("investorTargets", [])[:6]
        if str(t.get("name", "")).strip() and str(t.get("name")).strip().lower() in corpus
    ]
    targets.sort(key=lambda t: t.fitScore, reverse=True)
    return Committee(
        members=members,
        consensus=str(raw.get("consensus", ""))[:800],
        investorTargets=targets,
        nextActions=[str(a)[:200] for a in raw.get("nextActions", [])[:5]],
    )


def _llm_payload(profile: StartupProfile, bundle: EvidenceBundle) -> dict[str, Any]:
    return {
        "startup": profile.model_dump(),
        "question": profile.question,
        "evidence": [e.model_dump(include={"id", "kind", "text"}) for e in bundle.evidence],
        "calaSummaries": bundle.summaries,
    }


async def run_analysis(settings: Settings, profile: StartupProfile) -> AsyncIterator[dict[str, Any]]:
    run_id = f"run-{uuid.uuid4().hex[:10]}"
    analyst = {"openai": "OpenAI", "gemini": "Gemini"}.get(settings.analysis_mode, "Demo")
    live_graph = settings.data_mode == "cala"
    yield {"type": "start", "runId": run_id, "question": profile.question,
           "dataMode": settings.data_mode, "analysisMode": settings.analysis_mode}
    steps = [{"id": f"cala:{kind}", "group": "Cala data", "label": label} for kind, label in QUERY_LABELS.items()]
    if live_graph:
        steps.append({"id": "graph:competitors", "group": "Cala graph", "label": "Who backs your competitors"})
    steps += [
        {"id": "scenarios", "group": analyst, "label": "Drivers, scenario matrix and round probability"},
        {"id": "committee", "group": analyst, "label": "Investment committee and investor shortlist"},
    ]
    if live_graph:
        steps.append({"id": "graph:investors", "group": "Cala graph",
                      "label": "Verify shortlist: portfolio, recent deals, conflicts"})
    yield {"type": "steps", "steps": steps}
    for kind in QUERY_LABELS:
        yield {"type": "step", "id": f"cala:{kind}", "state": "running"}

    bundle = EvidenceBundle()
    async for item in stream_evidence(settings, profile):
        if isinstance(item, EvidenceBundle):
            bundle = item
            continue
        detail = f"{item['facts']} facts" if item["state"] == "done" else "failed, continuing without it"
        yield {"type": "step", "id": f"cala:{item['kind']}", "state": item["state"],
               "detail": detail, "seconds": item["seconds"]}
        yield {"type": "evidence", "mode": "demo" if settings.data_mode == "demo" else "cala",
               "errors": [], "evidence": [e.model_dump() for e in item["evidence"]]}
    yield _evidence_event(bundle)
    if not bundle.evidence:
        yield {"type": "error", "message": "Cala returned no usable evidence for this startup. Try a broader sector or region."}
        return

    if settings.analysis_mode == "demo" and bundle.mode != "demo":
        # Never mix the fictional demo analysis with real Cala evidence.
        yield {"type": "error", "message": "Real Cala evidence loaded. Set GEMINI_API_KEY or OPENAI_API_KEY to generate drivers, scenarios and the committee."}
        yield {"type": "done", "runId": run_id}
        return

    valid = {e.id for e in bundle.evidence}
    payload = _llm_payload(profile, bundle)

    # The competitor graph lookup runs while the analyst builds scenarios.
    cmap = CompetitorMap()
    graph_task = None
    if live_graph:
        yield {"type": "step", "id": "graph:competitors", "state": "running", "detail": "following INVESTED_IN edges"}
        graph_started = time.monotonic()
        graph_task = asyncio.create_task(map_competitors(settings, bundle, profile))

    yield {"type": "step", "id": "scenarios", "state": "running", "detail": f"reading {len(bundle.evidence)} facts"}
    started = time.monotonic()
    try:
        raw_plan = (
            await structured_call(settings, PLAN_PROMPT, payload, "scenario_plan", PLAN_SCHEMA)
            if settings.analysis_mode != "demo"
            else demo_plan(profile)
        )
    except BaseException:
        if graph_task:
            graph_task.cancel()
        raise
    plan = normalize_plan(raw_plan, valid, profile.question)
    yield {"type": "step", "id": "scenarios", "state": "done", "seconds": round(time.monotonic() - started, 1),
           "detail": f"{len(plan.drivers)} drivers, 4 scenarios"}
    yield {"type": "plan", "plan": plan.model_dump()}

    if graph_task:
        cmap = await graph_task
        add_competitor_facts(bundle, cmap)
        linked = sum(1 for c in cmap.competitors if cmap.backers.get(c.id))
        yield {"type": "step", "id": "graph:competitors", "state": "done",
               "seconds": round(time.monotonic() - graph_started, 1),
               "detail": f"{linked} of {len(cmap.competitors)} competitors with known backers"}
        yield {"type": "graph", "competitors": cmap.as_payload()}
        yield _evidence_event(bundle)

    yield {"type": "step", "id": "committee", "state": "running", "detail": "three partners debating"}
    started = time.monotonic()
    committee_payload = {**_llm_payload(profile, bundle), "scenarios": [s.model_dump() for s in plan.scenarios],
                         "roundProbability": plan.event.probability,
                         "competitorBackersFromCalaGraph": cmap.as_payload()}
    raw_committee = (
        await structured_call(settings, COMMITTEE_PROMPT, committee_payload, "committee", COMMITTEE_SCHEMA)
        if settings.analysis_mode != "demo"
        else demo_committee(profile)
    )
    committee = normalize_committee(raw_committee, bundle)
    yield {"type": "step", "id": "committee", "state": "done", "seconds": round(time.monotonic() - started, 1),
           "detail": f"{len(committee.investorTargets)} investors shortlisted"}
    yield {"type": "committee", "committee": committee.model_dump()}

    if live_graph:
        yield {"type": "step", "id": "graph:investors", "state": "running",
               "detail": f"checking {len(committee.investorTargets)} investors"}
        started = time.monotonic()
        targets = await verify_targets(settings, committee.investorTargets, cmap, bundle)
        committee = committee.model_copy(update={"investorTargets": targets})
        verified = sum(1 for t in targets if t.verification and t.verification.verified)
        conflicted = sum(1 for t in targets if t.verification and t.verification.conflicts)
        yield {"type": "step", "id": "graph:investors", "state": "done",
               "seconds": round(time.monotonic() - started, 1),
               "detail": f"{verified} verified, {conflicted} with conflicts"}
        yield _evidence_event(bundle)
        yield {"type": "committee", "committee": committee.model_dump()}
    yield {"type": "done", "runId": run_id}


def _evidence_event(bundle: EvidenceBundle) -> dict[str, Any]:
    return {"type": "evidence", "mode": bundle.mode, "errors": bundle.errors,
            "evidence": [e.model_dump() for e in bundle.evidence]}
