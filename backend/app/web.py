"""Live web evidence: Context.dev company profiles and site scraping, Oxylabs search-to-scrape.

Every fact keeps its source URL. Failures are recorded and shown, never hidden: a step that
cannot reach the web says so and the report continues with Cala data alone.
"""
from __future__ import annotations

import asyncio
import re
from datetime import date
from typing import Any
from urllib.parse import urlparse

import httpx

from app.cala import EvidenceBundle
from app.calahttp import _cache_path, _cache_put, count_web
from app.config import Settings
from app.models import InvestorTarget, InvestorWeb, Source, StartupProfile, WebItem

CONTEXT_DEV = "https://api.context.dev/v1"
OXYLABS = "https://webapi.oxylabs.io/v1"
WEB_CACHE_SECONDS = 3600  # live web data: at most one hour old
CALL_TIMEOUT = 25.0
COMPETITOR_BUDGET = 25.0
INVESTOR_BUDGET = 45.0
MAX_WEB_COMPETITORS = 5


def _cached(method: str, url: str, body: Any) -> Any | None:
    import json
    import time

    path = _cache_path(method, url, None, body)
    try:
        if time.time() - path.stat().st_mtime < WEB_CACHE_SECONDS:
            return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    return None


async def _post(http: httpx.AsyncClient, url: str, key: str, body: dict[str, Any], counter: str) -> Any:
    cached = _cached("POST", url, body)
    if cached is not None:
        return cached
    count_web(counter)
    response = await http.post(url, json=body, timeout=CALL_TIMEOUT,
                               headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    response.raise_for_status()
    data = response.json()
    _cache_put(_cache_path("POST", url, None, body), data)
    return data


# ---------- text helpers ----------

MD_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
MD_NOISE = re.compile(r"[#*_>`|]+")


def clean_markdown(text: str) -> str:
    text = MD_LINK.sub(r"\1", text or "")
    text = MD_NOISE.sub(" ", text)
    return " ".join(text.split())


def sentences(text: str) -> list[str]:
    """Sentences of at most 400 chars; markdown lines (headings, list items) never merge."""
    out = []
    for line in (text or "").splitlines():
        for sentence in re.split(r"(?<=[.!?])\s+", clean_markdown(line)):
            if 40 <= len(sentence.strip()) <= 400:
                out.append(sentence.strip())
    return out


def pick_sentences(text: str, must: list[str], prefer: list[str], limit: int = 2) -> str:
    """Sentences naming any of `must`, ranked by how many `prefer` words they contain."""
    must_l = [m.lower() for m in must if m]
    prefer_l = [p.lower() for p in prefer if p and len(p) > 2]
    scored = []
    for index, sentence in enumerate(sentences(text)):
        low = sentence.lower()
        if must_l and not any(m in low for m in must_l):
            continue
        scored.append((sum(p in low for p in prefer_l), -index, sentence))
    scored.sort(reverse=True)
    return " ".join(s for _, _, s in scored[:limit])[:500]


def domain_of(url: str | None) -> str:
    if not url:
        return ""
    host = urlparse(url if "//" in url else f"https://{url}").netloc
    return host.removeprefix("www.")


def _short_name(name: str) -> str:
    """'Lifeline Ventures Oy' -> 'Lifeline Ventures' for matching in web text."""
    return re.sub(r"\b(oy|ab|gmbh|ltd|llc|inc|as|a/s|bv|sa|plc)\b\.?$", "", name.strip(), flags=re.I).strip(" ,")


def _profile_words(profile: StartupProfile) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z-]{3,}", f"{profile.sector} {profile.description}")
    return list(dict.fromkeys(w.lower() for w in words))[:12] + [profile.stage.replace("-", " "), profile.country]


# ---------- Context.dev ----------

async def brand_by_name(http: httpx.AsyncClient, key: str, name: str) -> dict[str, Any] | None:
    data = await _post(http, f"{CONTEXT_DEV}/brand/retrieve", key, {"type": "by_name", "name": name}, "contextDev")
    brand = data.get("brand") if isinstance(data, dict) else None
    return brand if isinstance(brand, dict) and brand.get("domain") else None


async def scrape_markdown(http: httpx.AsyncClient, key: str, url: str) -> str:
    data = await _post(http, f"{CONTEXT_DEV}/web/scrape", key,
                       {"url": url, "formats": {"markdown": True}, "sharedParams": {"mainContentOnly": True}},
                       "contextDev")
    markdown = data.get("markdown") if isinstance(data, dict) else None
    if isinstance(markdown, dict):
        if markdown.get("success") is False:
            return ""
        return str(markdown.get("data") or "")
    return str(markdown or "")


def _logo(brand: dict[str, Any]) -> str | None:
    for logo in brand.get("logos") or []:
        url = logo.get("url") if isinstance(logo, dict) else logo
        if isinstance(url, str) and url.startswith("https://"):
            return url
    return None


def _employees(brand: dict[str, Any]) -> str:
    value = brand.get("employees")
    if isinstance(value, dict):
        value = value.get("count") or value.get("range") or value.get("value")
    return str(value) if value not in (None, "", 0) else ""


def _brand_fact(name: str, brand: dict[str, Any]) -> str:
    parts = [f"{name} ({brand['domain']})"]
    description = clean_markdown(str(brand.get("description") or ""))[:300]
    if description:
        parts.append(description.rstrip(".") + ".")
    if _employees(brand):
        parts.append(f"Employees: {_employees(brand)}.")
    address = brand.get("address")
    if isinstance(address, dict) and (address.get("country") or address.get("city")):
        parts.append(f"Based in {', '.join(str(address[k]) for k in ('city', 'country') if address.get(k))}.")
    return " ".join(parts)


async def competitor_profiles(settings: Settings, names: list[str], bundle: EvidenceBundle) -> dict[str, Any]:
    """Context.dev profile per competitor, added as 'web' evidence. Returns a step summary."""
    if not settings.context_dev_api_key or not names:
        return {"found": 0, "tried": 0, "errors": []}
    key = settings.context_dev_api_key
    errors: list[str] = []
    found = 0

    async def one(http: httpx.AsyncClient, name: str) -> None:
        nonlocal found
        try:
            brand = await brand_by_name(http, key, name)
        except (httpx.HTTPError, ValueError) as exc:
            errors.append(f"{name}: {_reason(exc)}")
            return
        if not brand:
            return
        found += 1
        bundle.add("web", f"Context.dev profile: {_brand_fact(name, brand)}",
                   [Source(name=f"{brand['domain']} (via Context.dev)", url=f"https://{brand['domain']}")],
                   title=f"{name}: company profile from its website")

    async with httpx.AsyncClient() as http:
        try:
            await asyncio.wait_for(asyncio.gather(*(one(http, n) for n in names[:MAX_WEB_COMPETITORS])),
                                   COMPETITOR_BUDGET)
        except asyncio.TimeoutError:
            errors.append("timed out")
    return {"found": found, "tried": min(len(names), MAX_WEB_COMPETITORS), "errors": errors}


# ---------- Oxylabs ----------

async def oxy_search(http: httpx.AsyncClient, key: str, query: str, max_results: int = 5) -> list[dict[str, Any]]:
    data = await _post(http, f"{OXYLABS}/search", key, {"query": query, "max_results": max_results}, "webSearches")
    results = data.get("results") if isinstance(data, dict) else None
    return [r for r in results or [] if isinstance(r, dict) and r.get("url")]


async def oxy_scrape(http: httpx.AsyncClient, key: str, url: str) -> str:
    data = await _post(http, f"{OXYLABS}/scrape", key, {"url": url, "output": ["markdown"]}, "webScrapes")
    results = data.get("results") if isinstance(data, dict) else None
    if isinstance(results, list) and results and isinstance(results[0], dict):
        return str(results[0].get("markdown") or results[0].get("content") or "")
    return str((data or {}).get("markdown") or "")


SKIP_DOMAINS = ("linkedin.com", "facebook.com", "x.com", "twitter.com", "instagram.com", "youtube.com")


async def investor_news(http: httpx.AsyncClient, key: str, investor: str, profile: StartupProfile,
                        bundle: EvidenceBundle, web: InvestorWeb) -> None:
    """Search the live web for the investor's latest deals, then scrape and quote the best article."""
    short = _short_name(investor)
    year = date.today().year
    query = f"\"{short}\" invests {profile.sector} {year}"
    results = await oxy_search(http, key, query)
    candidates = [r for r in results
                  if short.lower() in f"{r.get('title', '')} {r.get('outline', '')}".lower()
                  and not any(d in domain_of(r["url"]) for d in SKIP_DOMAINS)]
    for result in candidates[:2]:
        try:
            page = await oxy_scrape(http, key, result["url"])
        except (httpx.HTTPError, ValueError) as exc:
            web.errors.append(f"Oxylabs scrape of {domain_of(result['url'])}: {_reason(exc)}")
            continue
        quote = pick_sentences(page, [short], _profile_words(profile) + ["led", "round", "invest", "seed", "funding"])
        if not quote:
            quote = clean_markdown(str(result.get("outline") or ""))[:300]
        if not quote:
            continue
        title = clean_markdown(str(result.get("title") or domain_of(result["url"])))[:140]
        eid = bundle.add("web", f"Live web ({domain_of(result['url'])}): {quote}",
                         [Source(name=f"{title} (via Oxylabs)", url=result["url"])],
                         title=f"{short} on the web: {title}")
        web.news.append(WebItem(title=title, url=result["url"], snippet=quote[:300], evidenceId=eid))
        if len(web.news) >= 1:
            return
    if not candidates:
        web.errors.append(f"Oxylabs search found no recent article naming {short}")


async def investor_site(http: httpx.AsyncClient, key: str, investor: str, profile: StartupProfile,
                        bundle: EvidenceBundle, web: InvestorWeb) -> None:
    """Context.dev: find the investor's website, then scrape it for the stated investment focus."""
    short = _short_name(investor)
    brand = await brand_by_name(http, key, short)
    if not brand:
        web.errors.append(f"Context.dev found no website for {short}")
        return
    web.website = f"https://{brand['domain']}"
    web.description = clean_markdown(str(brand.get("description") or ""))[:300]
    web.logo = _logo(brand)
    page = ""
    try:
        page = await scrape_markdown(http, key, web.website)
    except (httpx.HTTPError, ValueError) as exc:
        web.errors.append(f"Context.dev scrape of {brand['domain']}: {_reason(exc)}")
    focus = pick_sentences(page, [], _profile_words(profile) + ["invest", "seed", "early", "stage", "founders", "ticket"])
    focus = focus or web.description
    if focus:
        web.focus = focus[:400]
        web.focusEvidenceId = bundle.add(
            "web", f"{short} website ({brand['domain']}): {focus}",
            [Source(name=f"{brand['domain']} (via Context.dev)", url=web.website)],
            title=f"{short}: investment focus from its website")


async def check_investors(settings: Settings, targets: list[InvestorTarget], profile: StartupProfile,
                          bundle: EvidenceBundle) -> list[InvestorTarget]:
    """Attach live web data to each shortlisted investor (both providers run in parallel)."""
    webs = {t.name: InvestorWeb() for t in targets}

    async def guarded(coro, web: InvestorWeb, label: str) -> None:
        try:
            await coro
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            web.errors.append(f"{label}: {_reason(exc)}")

    jobs = []
    async with httpx.AsyncClient() as http:
        for target in targets:
            web = webs[target.name]
            if settings.context_dev_api_key:
                jobs.append(guarded(investor_site(http, settings.context_dev_api_key, target.name, profile, bundle, web),
                                    web, "Context.dev"))
            if settings.oxylabs_api_key:
                jobs.append(guarded(investor_news(http, settings.oxylabs_api_key, target.name, profile, bundle, web),
                                    web, "Oxylabs"))
        try:
            await asyncio.wait_for(asyncio.gather(*jobs), INVESTOR_BUDGET)
        except asyncio.TimeoutError:
            for web in webs.values():
                if not web.news and not web.website:
                    web.errors.append("live web check timed out")
    out = []
    for target in targets:
        web = webs[target.name]
        evidence = list(target.evidence)
        for eid in [web.focusEvidenceId] + [n.evidenceId for n in web.news]:
            if eid and eid not in evidence:
                evidence.append(eid)
        out.append(target.model_copy(update={"web": web, "evidence": evidence}))
    return out


def _reason(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    if isinstance(exc, httpx.TimeoutException):
        return "timed out"
    return type(exc).__name__
