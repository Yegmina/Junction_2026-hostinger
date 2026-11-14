"""LLM calls with strict JSON schemas: Gemini (generateContent) or OpenAI (Responses API)."""
from __future__ import annotations

import json
from typing import Any

import httpx

from app.config import Settings

PESTEL_ENUM = ["political", "economic", "social", "technological", "environmental", "legal"]
STR_LIST = {"type": "array", "items": {"type": "string"}}


def _obj(properties: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False, "properties": properties, "required": list(properties)}


PLAN_SCHEMA = _obj(
    {
        "verdict": {"type": "string"},
        "drivers": {
            "type": "array",
            "items": _obj(
                {
                    "id": {"type": "string"},
                    "name": {"type": "string"},
                    "pestel": {"type": "string", "enum": PESTEL_ENUM},
                    "description": {"type": "string"},
                    "impact": {"type": "number"},
                    "uncertainty": {"type": "number"},
                    "direction": {"type": "string", "enum": ["tailwind", "headwind", "mixed"]},
                    "evidence": STR_LIST,
                }
            ),
        },
        "axes": {
            "type": "array",
            "items": _obj(
                {
                    "driverId": {"type": "string"},
                    "name": {"type": "string"},
                    "lowLabel": {"type": "string"},
                    "highLabel": {"type": "string"},
                }
            ),
        },
        "scenarios": {
            "type": "array",
            "items": _obj(
                {
                    "id": {"type": "string"},
                    "name": {"type": "string"},
                    "position": {"type": "array", "items": {"type": "string", "enum": ["low", "high"]}},
                    "oneLiner": {"type": "string"},
                    "narrative": {"type": "string"},
                    "probability": {"type": "number"},
                    "eventProbabilityIfScenario": {"type": "number"},
                    "signposts": STR_LIST,
                    "evidence": STR_LIST,
                }
            ),
        },
        "eventExplanation": {"type": "string"},
    }
)

COMMITTEE_SCHEMA = _obj(
    {
        "members": {
            "type": "array",
            "items": _obj(
                {
                    "persona": {"type": "string"},
                    "stance": {"type": "string", "enum": ["back", "conditional", "pass"]},
                    "headline": {"type": "string"},
                    "argument": {"type": "string"},
                    "evidence": STR_LIST,
                }
            ),
        },
        "consensus": {"type": "string"},
        "investorTargets": {
            "type": "array",
            "items": _obj(
                {
                    "name": {"type": "string"},
                    "why": {"type": "string"},
                    "fitScore": {"type": "number"},
                    "evidence": STR_LIST,
                }
            ),
        },
        "nextActions": STR_LIST,
    }
)

PLAN_PROMPT = (
    "You are a venture foresight analyst. Use ONLY the evidence items provided (ids E1, E2, ...). "
    "Step 1: extract 5-7 drivers that will shape whether this startup can raise its round. Tag each with one "
    "PESTEL category, impact and uncertainty in 0..1, direction, and the evidence ids that support it. "
    "Step 2: pick the two drivers with the highest impact x uncertainty as scenario axes (low/high labels). "
    "Step 3: write exactly four scenarios, one per axis quadrant; position is [first axis, second axis] as "
    "'low'/'high'. Give each a probability (all four sum to 1), the conditional probability that the startup "
    "closes the stated round in that scenario, 2-3 observable signposts, and supporting evidence ids. "
    "Use base rates: most startups do not close their target round on time. Do not invent facts, companies "
    "or numbers that are not in the evidence. Write for a busy founder: 'verdict' is ONE plain sentence of at "
    "most 25 words with the bottom line and the single biggest lever; each scenario 'oneLiner' is at most 14 words; "
    "narratives at most 50 words; driver descriptions at most 25 words. No markdown."
)

COMMITTEE_PROMPT = (
    "You simulate an investment committee with exactly three members: 'Lead partner (bull case)', "
    "'Risk partner (bear case)' and 'Sector specialist'. Each gives a stance (back/conditional/pass) on the "
    "startup's round and a short argument citing evidence ids. Then write a consensus. Then list 3-5 investor "
    "targets: ONLY investors whose names appear in the evidence text, with why they fit, fitScore 0..1 and "
    "evidence ids. Finish with 3-5 concrete next actions for the founder. Use only the provided evidence. "
    "Each member 'headline' is at most 12 words; arguments at most 60 words; consensus at most 35 words; "
    "investor 'why' at most 25 words; next actions at most 16 words each, starting with a verb. No markdown."
)


def _output_text(raw: dict[str, Any]) -> str:
    if isinstance(raw.get("output_text"), str):
        return raw["output_text"]
    for output in raw.get("output", []):
        for content in output.get("content", []) or []:
            if isinstance(content.get("text"), str):
                return content["text"]
    raise ValueError("OpenAI response contained no text output")


async def structured_call(
    settings: Settings, system: str, payload: dict[str, Any], name: str, schema: dict[str, Any]
) -> dict[str, Any]:
    if settings.analysis_mode == "gemini":
        return await _gemini_call(settings, system, payload, schema)
    return await _openai_call(settings, system, payload, name, schema)


async def _gemini_call(settings: Settings, system: str, payload: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": json.dumps(payload, ensure_ascii=False)}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseJsonSchema": schema,
            "maxOutputTokens": 16000,
            "temperature": 0.4,
        },
    }
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{settings.gemini_model}:generateContent"
    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
        response = await client.post(url, headers={"x-goog-api-key": settings.gemini_api_key or ""}, json=body)
        response.raise_for_status()
        raw = response.json()
    candidates = raw.get("candidates") or []
    if not candidates:
        raise ValueError("Gemini returned no candidates")
    parts = (candidates[0].get("content") or {}).get("parts") or []
    text = "".join(part.get("text", "") for part in parts if not part.get("thought"))
    if not text:
        raise ValueError(f"Gemini returned no text (finishReason={candidates[0].get('finishReason')})")
    return json.loads(text)


async def _openai_call(
    settings: Settings, system: str, payload: dict[str, Any], name: str, schema: dict[str, Any]
) -> dict[str, Any]:
    body = {
        "model": settings.openai_model,
        "input": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        "text": {"format": {"type": "json_schema", "name": name, "strict": True, "schema": schema}},
        "reasoning": {"effort": "low"},
        "max_output_tokens": 8000,
    }
    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
        response = await client.post(
            "https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            json=body,
        )
        response.raise_for_status()
        return json.loads(_output_text(response.json()))
