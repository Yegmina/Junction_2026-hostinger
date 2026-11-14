"""Evidence -> (scenarios || competitor graph -> committee -> verified shortlist)."""
from __future__ import annotations

import asyncio
import math
import time
import uuid
from typing import Any, AsyncIterator

from app.cala import QUERY_LABELS, EvidenceBundle, stream_evidence
from app.calahttp import start_usage
from app.config import Settings
from app.demo import demo_committee, demo_plan
from app.llm import PESTEL_ENUM, COMMITTEE_PROMPT, COMMITTEE_SCHEMA, PLAN_PROMPT, PLAN_SCHEMA, structured_call
from app.nemotron import audit_shortlist
from app.verification import CompetitorMap, add_competitor_facts, competitor_entities, map_competitors, verify_targets
from app.web import check_investors, competitor_profiles
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
    usage = start_usage()  # every Cala call below, including in spawned tasks, counts here
    run_started = time.monotonic()
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
                      "label": "Verify shortlist: portfolio, round sizes, warm intros, conflicts"})
    web_competitors = bool(settings.context_dev_api_key) and settings.analysis_mode != "demo"
    web_investors = bool(settings.context_dev_api_key or settings.oxylabs_api_key) and settings.analysis_mode != "demo"
    auditing = bool(settings.nvidia_api_key) and settings.analysis_mode != "demo"
    if web_competitors:
        steps.insert(len(QUERY_LABELS), {"id": "web:competitors", "group": "Live web",
                                         "label": "Competitor profiles from their websites (Context.dev)"})
    if web_investors:
        providers = " + ".join(p for p, k in (("Context.dev", settings.context_dev_api_key),
                                               ("Oxylabs", settings.oxylabs_api_key)) if k)
        steps.append({"id": "web:investors", "group": "Live web",
                      "label": f"Investor websites and latest deals ({providers})"})
    if auditing:
        steps.append({"id": "audit", "group": "NVIDIA Nemotron", "label": "Independent audit of the shortlist"})
    yield {"type": "steps", "steps": steps}
    for kind in QUERY_LABELS:
        yield {"type": "step", "id": f"cala:{kind}", "state": "running"}

    bundle = EvidenceBundle()
    async for item in stream_evidence(settings, profile):
        if isinstance(item, EvidenceBundle):
            bundle = item
            continue
        detail = (f"{item['facts']} facts" if item["state"] == "done"
                  else f"failed ({item.get('reason') or 'error'}), continuing without it")
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

    # Two lanes run at once and stream into one queue: scenarios (slow LLM call) and the
    # shortlist (competitor graph -> committee -> investor verification). The founder sees
    # who to pitch without waiting for the scenario matrix.
    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    async def scenario_lane() -> None:
        await queue.put({"type": "step", "id": "scenarios", "state": "running",
                         "detail": f"reading {len(bundle.evidence)} facts"})
        started = time.monotonic()
        raw_plan = (
            await structured_call(settings, PLAN_PROMPT, payload, "scenario_plan", PLAN_SCHEMA)
            if settings.analysis_mode != "demo"
            else demo_plan(profile)
        )
        plan = normalize_plan(raw_plan, valid, profile.question)
        await queue.put({"type": "step", "id": "scenarios", "state": "done",
                         "seconds": round(time.monotonic() - started, 1),
                         "detail": f"{len(plan.drivers)} drivers, 4 scenarios"})
        await queue.put({"type": "plan", "plan": plan.model_dump()})

    async def shortlist_lane() -> None:
        cmap = CompetitorMap()
        web_task = None
        if web_competitors:
            names = [c.name for c in competitor_entities(bundle, profile)]
            await queue.put({"type": "step", "id": "web:competitors", "state": "running",
                             "detail": f"looking up {min(len(names), 5)} competitors"})
            web_task = asyncio.create_task(_timed(competitor_profiles(settings, names, bundle)))
        if live_graph:
            await queue.put({"type": "step", "id": "graph:competitors", "state": "running",
                             "detail": "following INVESTED_IN edges"})
            started = time.monotonic()
            cmap = await map_competitors(settings, bundle, profile)
            add_competitor_facts(bundle, cmap)
            linked = sum(1 for c in cmap.competitors if cmap.backers.get(c.id))
            await queue.put({"type": "step", "id": "graph:competitors", "state": "done",
                             "seconds": round(time.monotonic() - started, 1),
                             "detail": f"{linked} of {len(cmap.competitors)} competitors with known backers"})
            await queue.put({"type": "graph", "competitors": cmap.as_payload()})
            await queue.put(_evidence_event(bundle))
        if web_task:
            summary, seconds = await web_task
            detail = f"{summary['found']} of {summary['tried']} profiled, {summary.get('news', 0)} headlines"
            if summary["errors"] and not summary["found"]:
                detail += f" ({summary['errors'][0]})"
            await queue.put({"type": "step", "id": "web:competitors", "state": "done", "seconds": seconds,
                             "detail": detail})
            await queue.put(_evidence_event(bundle))

        await queue.put({"type": "step", "id": "committee", "state": "running", "detail": "three partners debating"})
        started = time.monotonic()
        committee_payload = {**_llm_payload(profile, bundle), "competitorBackersFromCalaGraph": cmap.as_payload()}
        raw_committee = (
            await structured_call(settings, COMMITTEE_PROMPT, committee_payload, "committee", COMMITTEE_SCHEMA)
            if settings.analysis_mode != "demo"
            else demo_committee(profile)
        )
        committee = normalize_committee(raw_committee, bundle)
        await queue.put({"type": "step", "id": "committee", "state": "done",
                         "seconds": round(time.monotonic() - started, 1),
                         "detail": f"{len(committee.investorTargets)} investors shortlisted"})
        await queue.put({"type": "committee", "committee": committee.model_dump()})

        web_check = None
        if web_investors and committee.investorTargets:
            await queue.put({"type": "step", "id": "web:investors", "state": "running",
                             "detail": f"searching and scraping for {len(committee.investorTargets)} investors"})
            web_check = asyncio.create_task(_timed(check_investors(settings, committee.investorTargets, profile, bundle)))
        if live_graph:
            await queue.put({"type": "step", "id": "graph:investors", "state": "running",
                             "detail": f"checking {len(committee.investorTargets)} investors"})
            started = time.monotonic()
            targets = await verify_targets(settings, committee.investorTargets, cmap, bundle, profile)
            if web_check:
                webbed, _ = await web_check
                by_name = {t.name: t for t in webbed}
                targets = [t.model_copy(update={"web": by_name[t.name].web, "evidence": by_name[t.name].evidence})
                           if t.name in by_name else t for t in targets]
            committee = committee.model_copy(update={"investorTargets": targets})
            verified = sum(1 for t in targets if t.verification and t.verification.verified)
            intros = sum(len(t.verification.introPaths) for t in targets if t.verification)
            conflicted = sum(1 for t in targets if t.verification and t.verification.conflicts)
            await queue.put({"type": "step", "id": "graph:investors", "state": "done",
                             "seconds": round(time.monotonic() - started, 1),
                             "detail": f"{verified} verified, {intros} intro paths, {conflicted} with conflicts"})
            await queue.put(_evidence_event(bundle))
            await queue.put({"type": "committee", "committee": committee.model_dump()})
        elif web_check:
            webbed, _ = await web_check
            committee = committee.model_copy(update={"investorTargets": webbed})
        if web_check:
            _, seconds = await web_check
            targets = committee.investorTargets
            sites = sum(1 for t in targets if t.web and t.web.website)
            news = sum(len(t.web.news) for t in targets if t.web)
            await queue.put({"type": "step", "id": "web:investors", "state": "done", "seconds": seconds,
                             "detail": f"{sites} websites, {news} recent articles"})
            await queue.put(_evidence_event(bundle))
            await queue.put({"type": "committee", "committee": committee.model_dump()})

        if auditing and committee.investorTargets:
            await queue.put({"type": "step", "id": "audit", "state": "running",
                             "detail": f"{settings.nemotron_model.split('/')[-1]} reviewing {len(committee.investorTargets)} leads"})
            started = time.monotonic()
            try:
                committee = await audit_shortlist(settings, profile, committee, bundle)
                verdicts = [t.audit.verdict for t in committee.investorTargets if t.audit]
                detail = ", ".join(f"{verdicts.count(v)} {v}" for v in ("supported", "weak", "contradicted") if verdicts.count(v))
                await queue.put({"type": "step", "id": "audit", "state": "done",
                                 "seconds": round(time.monotonic() - started, 1), "detail": detail or "no verdicts"})
                await queue.put({"type": "committee", "committee": committee.model_dump()})
            except Exception as exc:  # the audit is a second opinion: never lose the report over it
                await queue.put({"type": "step", "id": "audit", "state": "failed",
                                 "seconds": round(time.monotonic() - started, 1),
                                 "detail": f"audit unavailable ({type(exc).__name__}), shortlist unchanged"})

    async def lane(coro) -> None:
        try:
            await coro
            await queue.put(None)
        except Exception as exc:  # surfaced in the consumer, which owns error reporting
            await queue.put({"type": "__failed__", "error": exc})

    tasks = [asyncio.create_task(lane(scenario_lane())), asyncio.create_task(lane(shortlist_lane()))]
    try:
        finished = 0
        while finished < len(tasks):
            event = await queue.get()
            if event is None:
                finished += 1
            elif event["type"] == "__failed__":
                raise event["error"]
            else:
                yield event
    finally:
        for task in tasks:
            task.cancel()

    yield {"type": "usage", "usage": usage.as_dict()}
    yield {"type": "done", "runId": run_id, "seconds": round(time.monotonic() - run_started, 1)}


async def _timed(coro):
    started = time.monotonic()
    result = await coro
    return result, round(time.monotonic() - started, 1)


def _evidence_event(bundle: EvidenceBundle) -> dict[str, Any]:
    return {"type": "evidence", "mode": bundle.mode, "errors": bundle.errors,
            "evidence": [e.model_dump() for e in bundle.evidence]}
