"""Fictional demo data used when API keys are missing.

All company and investor names here are invented and every source is labelled as fictional,
so the demo can never be mistaken for real market data.
"""
from __future__ import annotations

from app.cala import EvidenceBundle
from app.models import Source, StartupProfile

DEMO_SOURCE = [Source(name="Demo dataset (fictional)")]


def demo_evidence(profile: StartupProfile) -> EvidenceBundle:
    sector = profile.sector
    region = profile.country
    bundle = EvidenceBundle(mode="demo")
    facts = [
        ("competitor", f"Northwind Labs (fictional) builds {sector} software in {region}; total funding EUR 14M; latest round Series A in 2025 led by Aurora Ventures (fictional)."),
        ("competitor", f"Kestrel Systems (fictional) is an early {sector} startup in {region} with EUR 1.8M pre-seed funding from Fjord Angels (fictional)."),
        ("competitor", f"Lumen Grid (fictional), a US {sector} company, raised USD 60M Series B in 2025 and announced European expansion."),
        ("funding", f"{sector} startups in {region} raised 23 disclosed rounds in the last 24 months (demo figure), with median seed size of EUR 2.1M."),
        ("funding", f"Seed-to-Series-A conversion in {sector} slowed in 2025: time between rounds grew from 18 to 24 months (demo figure)."),
        ("funding", f"Two {sector} rounds above EUR 20M closed in {region} in 2025, both with a public-sector co-investor (demo figure)."),
        ("investor", f"Aurora Ventures (fictional) led 4 {sector} seed and Series A rounds in {region} since 2024, typical ticket EUR 1-5M."),
        ("investor", f"Fjord Angels (fictional) is an angel syndicate that co-invested in 9 {region} pre-seed and seed rounds since 2024."),
        ("investor", f"Baltic Bridge Capital (fictional) closed a new EUR 120M fund in 2025 focused on {sector} and B2B software."),
        ("market", f"EU regulation affecting {sector} enters into force in 2026, raising compliance costs for smaller vendors (demo fact)."),
    ]
    for kind, text in facts:
        bundle.add(kind, text, DEMO_SOURCE)
    bundle.summaries["note"] = "Demo mode: no CALA_API_KEY configured. All names and figures are fictional."
    return bundle


def demo_plan(profile: StartupProfile) -> dict:
    return {
        "verdict": "Roughly a coin flip: the round closes if seed capital rebounds, so lead with the 2026 compliance deadline.",
        "drivers": [
            {"id": "D1", "name": "Seed capital availability", "pestel": "economic", "description": "How much early-stage capital is flowing into the sector.", "impact": 0.85, "uncertainty": 0.75, "direction": "mixed", "evidence": ["E4", "E5", "E9"]},
            {"id": "D2", "name": "Regulatory pressure", "pestel": "legal", "description": "New EU rules raise compliance costs but also create demand for compliant tools.", "impact": 0.7, "uncertainty": 0.65, "direction": "mixed", "evidence": ["E10"]},
            {"id": "D3", "name": "Competitive crowding", "pestel": "technological", "description": "Well-funded competitors entering the region.", "impact": 0.65, "uncertainty": 0.4, "direction": "headwind", "evidence": ["E1", "E3"]},
            {"id": "D4", "name": "Active local lead investors", "pestel": "economic", "description": "Presence of investors who still lead rounds at this stage.", "impact": 0.6, "uncertainty": 0.3, "direction": "tailwind", "evidence": ["E7", "E8", "E9"]},
            {"id": "D5", "name": "Public co-investment", "pestel": "political", "description": "Public funds co-investing in larger rounds.", "impact": 0.45, "uncertainty": 0.5, "direction": "tailwind", "evidence": ["E6"]},
        ],
        "axes": [
            {"driverId": "D1", "name": "Seed capital availability", "lowLabel": "Capital drought", "highLabel": "Capital rebound"},
            {"driverId": "D2", "name": "Regulatory pressure", "lowLabel": "Light-touch rules", "highLabel": "Compliance wave"},
        ],
        "scenarios": [
            {"id": "S1", "name": "Frozen market", "position": ["low", "low"], "oneLiner": "Investors wait; bridge rounds instead of seed.", "narrative": "Little capital and little regulatory urgency: investors wait for traction.", "probability": 0.2, "eventProbabilityIfScenario": 0.2, "signposts": ["Fewer seed rounds per quarter", "Bridge rounds become common"], "evidence": ["E5"]},
            {"id": "S2", "name": "Compliance squeeze", "position": ["low", "high"], "oneLiner": "Only compliance sellers raise while money is scarce.", "narrative": "Rules bite while capital is scarce; only startups that sell compliance raise.", "probability": 0.3, "eventProbabilityIfScenario": 0.35, "signposts": ["Enforcement dates confirmed", "Incumbents acquire small vendors"], "evidence": ["E10", "E5"]},
            {"id": "S3", "name": "Open runway", "position": ["high", "low"], "oneLiner": "Capital returns; strong teams raise quickly.", "narrative": "Capital returns and competition stays generalist; strong teams raise quickly.", "probability": 0.2, "eventProbabilityIfScenario": 0.6, "signposts": ["New sector funds close", "Round sizes rise"], "evidence": ["E9", "E4"]},
            {"id": "S4", "name": "Regulated boom", "position": ["high", "high"], "oneLiner": "Rules create demand and capital follows.", "narrative": "New rules create demand and capital follows; compliant products win leads.", "probability": 0.3, "eventProbabilityIfScenario": 0.7, "signposts": ["Public co-investment grows", "Corporate pilots announced"], "evidence": ["E6", "E9", "E10"]},
        ],
        "eventExplanation": "Demo estimate: the round is likely when capital rebounds, and hard in a capital drought regardless of regulation.",
    }


def demo_committee(profile: StartupProfile) -> dict:
    return {
        "members": [
            {"persona": "Lead partner (bull case)", "stance": "back", "headline": "Active local leads make seed credible", "argument": "Active local leads and a fresh sector fund mean a credible seed path.", "evidence": ["E7", "E9"]},
            {"persona": "Risk partner (bear case)", "stance": "conditional", "headline": "Needs traction before a crowded market", "argument": "Longer time between rounds and a well-funded US entrant raise the bar for traction.", "evidence": ["E5", "E3"]},
            {"persona": "Sector specialist", "stance": "back", "headline": "Regulation is the wedge", "argument": "Upcoming regulation is a wedge if the product sells compliance.", "evidence": ["E10"]},
        ],
        "consensus": "Raise with a compliance-led story and target investors who led sector seed rounds recently.",
        "investorTargets": [
            {"name": "Aurora Ventures (fictional)", "why": "Led several sector seed and Series A rounds with matching ticket size.", "fitScore": 0.8, "evidence": ["E7", "E1"]},
            {"name": "Baltic Bridge Capital (fictional)", "why": "New fund with a sector focus needs to deploy.", "fitScore": 0.7, "evidence": ["E9"]},
            {"name": "Fjord Angels (fictional)", "why": "Frequent co-investor to fill the round.", "fitScore": 0.55, "evidence": ["E8"]},
        ],
        "nextActions": [
            "Prepare a one-page note on how the product helps with the 2026 regulation",
            "Ask a portfolio founder of the top target for an intro",
            "Track new sector rounds weekly as signposts",
        ],
    }
