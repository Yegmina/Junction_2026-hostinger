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
    count_web(counter)  # counted like Cala: every call the report used, cached or not
    cached = _cached("POST", url, body)
    if cached is not None:
        return cached
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


DATE = re.compile(r"\b(20(2[3-9])|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b", re.I)
AMOUNT = re.compile(r"(€|\$|£|\bEUR\b|\bUSD\b)\s?\d|\d+(\.\d+)?\s?(m|million|k|bn)\b", re.I)
DEAL = ("led", "leads", "co-led", "participated", "backed", "invested", "raised", "round", "seed", "series")
BOILERPLATE = ("every venture round", "cookie", "subscribe", "sign up", "our funding reports cover")


def deal_sentences(text: str, name: str, topic: list[str], about_page: bool = False, limit: int = 2) -> str:
    """Sentences about the investor's deals, ranked: dated or sized first, then deal words, then topic.

    Only sentences with a date or an amount qualify. On a page whose title names the investor
    (a deal dashboard), sentences need not repeat the name."""
    scored = []
    for index, sentence in enumerate(sentences(text)):
        low = sentence.lower()
        if any(b in low for b in BOILERPLATE) or not (DATE.search(sentence) or AMOUNT.search(sentence)):
            continue
        names_it = name.lower() in low
        deal_words = sum(w in low for w in DEAL)
        if not names_it and not (about_page and deal_words):
            continue
        score = (3 * bool(DATE.search(sentence)) + 3 * bool(AMOUNT.search(sentence)) + 2 * names_it
                 + deal_words + sum(t in low for t in topic if len(t) > 3))
        scored.append((score, -index, sentence))
    scored.sort(reverse=True)
    return " ".join(s for _, _, s in scored[:limit])[:500]


def domain_of(url: str | None) -> str:
    if not url:
        return ""
    host = urlparse(url if "//" in url else f"https://{url}").netloc
    return host.removeprefix("www.")


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def _short_name(name: str) -> str:
    """'Lifeline Ventures Oy' -> 'Lifeline Ventures' for matching in web text."""
    return re.sub(r"\b(oy|ab|gmbh|ltd|llc|inc|as|a/s|bv|sa|plc)\b\.?$", "", name.strip(), flags=re.I).strip(" ,")


def _profile_words(profile: StartupProfile) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z-]{3,}", f"{profile.sector} {profile.description}")
    return list(dict.fromkeys(w.lower() for w in words))[:12] + [profile.stage.replace("-", " "), profile.country]


# ---------- Context.dev ----------
# Four endpoints combined: company search (funding, headcount, domain), brand (logo),
# web scrape (the investor's own words on its focus) and news (competitor headlines).

async def company_search(http: httpx.AsyncClient, key: str, name: str) -> dict[str, Any] | None:
    """Best company match for a name; None unless the returned name really matches."""
    data = await _post(http, f"{CONTEXT_DEV}/company/search", key, {"query": name}, "contextDev")
    want = _norm(_short_name(name))
    for result in (data.get("results") if isinstance(data, dict) else None) or []:
        got = _norm(_short_name(str(result.get("name") or "")))
        if result.get("domain") and want and got and (got == want or got.startswith(want) or want.startswith(got)):
            return result
    return None


async def brand_logo(http: httpx.AsyncClient, key: str, domain: str) -> str | None:
    data = await _post(http, f"{CONTEXT_DEV}/brand/retrieve", key, {"type": "by_domain", "domain": domain}, "contextDev")
    logos = ((data or {}).get("brand") or {}).get("logos") or []
    ranked = sorted((l for l in logos if isinstance(l, dict) and str(l.get("url", "")).startswith("https://")),
                    key=lambda l: (l.get("type") != "icon", l.get("mode") not in ("light", "has_opaque_background")))
    return ranked[0]["url"] if ranked else None


async def scrape_markdown(http: httpx.AsyncClient, key: str, url: str) -> str:
    data = await _post(http, f"{CONTEXT_DEV}/web/scrape", key,
                       {"url": url, "formats": {"markdown": True}, "sharedParams": {"mainContentOnly": True}},
                       "contextDev")
    markdown = data.get("markdown") if isinstance(data, dict) else None
    if isinstance(markdown, dict):
        return str(markdown.get("data") or "") if markdown.get("success") is not False else ""
    return str(markdown or "")


async def company_news(http: httpx.AsyncClient, key: str, domain: str, limit: int = 2) -> list[dict[str, Any]]:
    data = await _post(http, f"{CONTEXT_DEV}/news/search", key,
                       {"searchBy": {"type": "entity", "entity": {"type": "domain", "domain": domain}}, "limit": limit},
                       "contextDev")
    return [a for a in (data.get("data") if isinstance(data, dict) else None) or []
            if isinstance(a, dict) and a.get("url") and a.get("title")
            and (a.get("match") or {}).get("level", "primary") == "primary"]


def _usd(amount: Any) -> str:
    try:
        value = float(amount)
    except (TypeError, ValueError):
        return ""
    return f"${value / 1e6:.1f}M" if value >= 1e6 else f"${value / 1e3:.0f}k"


def company_fact(name: str, company: dict[str, Any]) -> str:
    """'Kausal (kausal.tech): raised $1.9M in 2 rounds; latest seed of $931k on 2023-10-31; 42 employees; ...'"""
    parts = []
    funding = company.get("funding") or {}
    if funding.get("total_usd"):
        rounds = funding.get("round_count")
        parts.append(f"raised {_usd(funding['total_usd'])} in total" + (f" over {rounds} rounds" if rounds else ""))
    latest = funding.get("latest_round") or {}
    if latest.get("type"):
        amount = f" of {_usd(latest['amount_usd'])}" if latest.get("amount_usd") else ""
        parts.append(f"latest round: {str(latest['type']).replace('_', ' ')}{amount}"
                     + (f" on {latest['date']}" if latest.get("date") else ""))
    employees = (company.get("employees") or {}).get("count")
    if employees:
        parts.append(f"{employees} employees")
    if company.get("founded_year"):
        parts.append(f"founded {company['founded_year']}")
    hq = company.get("headquarters") or {}
    if hq.get("city") or hq.get("country_code"):
        parts.append("HQ " + ", ".join(str(hq[k]) for k in ("city", "country_code") if hq.get(k)))
    if not parts:
        description = clean_markdown(str(company.get("description") or ""))
        parts.append(description[:240])
    return f"{name} ({company['domain']}): " + "; ".join(p for p in parts if p) + "."


async def competitor_profiles(settings: Settings, names: list[str], bundle: EvidenceBundle) -> dict[str, Any]:
    """Context.dev funding profile and latest headline per competitor, added as 'web' evidence."""
    if not settings.context_dev_api_key or not names:
        return {"found": 0, "tried": 0, "news": 0, "errors": []}
    key = settings.context_dev_api_key
    errors: list[str] = []
    found = news_count = 0

    async def one(http: httpx.AsyncClient, name: str) -> None:
        nonlocal found, news_count
        try:
            company = await company_search(http, key, name)
        except (httpx.HTTPError, ValueError) as exc:
            errors.append(f"{name}: {_reason(exc)}")
            return
        if not company:
            return
        found += 1
        url = f"https://{company['domain']}"
        bundle.add("web", f"Context.dev company data: {company_fact(name, company)}",
                   [Source(name=f"{company['domain']} company profile (via Context.dev)", url=url)],
                   title=f"{name}: funding and size (Context.dev)")
        try:
            articles = await company_news(http, key, company["domain"], limit=1)
        except (httpx.HTTPError, ValueError):
            articles = []
        for article in articles[:1]:
            news_count += 1
            when = str(article.get("published_at") or "")[:10]
            text = clean_markdown(f"{article['title']}. {article.get('description') or ''}")[:400]
            source = (article.get("source") or {}).get("name") or domain_of(article["url"])
            bundle.add("web", f"News about {name} ({source}{', ' + when if when else ''}): {text}",
                       [Source(name=f"{article['title']} ({source}, via Context.dev)", url=article["url"])],
                       title=f"{name} in the news: {clean_markdown(article['title'])[:90]}")

    async with httpx.AsyncClient() as http:
        try:
            await asyncio.wait_for(asyncio.gather(*(one(http, n) for n in names[:MAX_WEB_COMPETITORS])),
                                   COMPETITOR_BUDGET)
        except asyncio.TimeoutError:
            errors.append("timed out")
    return {"found": found, "tried": min(len(names), MAX_WEB_COMPETITORS), "news": news_count, "errors": errors}


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


def _own_site(name: str, domain: str) -> bool:
    """'Greencode Ventures' owns greencode.vc and greencodeventures.com, not funding.tech.eu."""
    host = _norm(domain.split(".")[0] if domain.count(".") <= 1 else domain.rsplit(".", 2)[-2])
    first = _norm(name.split()[0]) if name.split() else ""
    return bool(host) and (host in _norm(name) or (len(first) >= 5 and host.startswith(first)))


def _outline(result: dict[str, Any]) -> str:
    outline = result.get("outline")
    if isinstance(outline, list):
        outline = " ".join(str(o) for o in outline)
    return clean_markdown(str(outline or ""))


async def investor_news(http: httpx.AsyncClient, key: str, investor: str, profile: StartupProfile,
                        bundle: EvidenceBundle, web: InvestorWeb) -> None:
    """Oxylabs search-to-scrape: find third-party coverage of the investor's recent deals, read the page,
    quote the sentences that name it. The investor's own site is skipped (Context.dev covers it)."""
    short = _short_name(investor)
    query = f"\"{short}\" led {profile.stage.replace('-', ' ')} round {date.today().year}"
    results = await oxy_search(http, key, query, max_results=8)
    candidates = [r for r in results
                  if short.lower() in f"{r.get('title', '')} {_outline(r)}".lower()
                  and not _own_site(short, domain_of(r["url"]))
                  and not any(d in domain_of(r["url"]) for d in SKIP_DOMAINS)]
    for result in candidates[:2]:
        page = ""
        try:
            page = await oxy_scrape(http, key, result["url"])
        except (httpx.HTTPError, ValueError) as exc:
            web.errors.append(f"Oxylabs scrape of {domain_of(result['url'])}: {_reason(exc)}")
        about_page = short.lower() in str(result.get("title") or "").lower()
        quote = deal_sentences(page, short, _profile_words(profile), about_page=about_page)
        if not quote:  # the search snippet, if it reports a dated or sized deal
            quote = deal_sentences(_outline(result), short, _profile_words(profile), about_page=about_page)
        if not quote:
            continue
        title = clean_markdown(str(result.get("title") or domain_of(result["url"])))[:140]
        eid = bundle.add("web", f"Live web ({domain_of(result['url'])}): {quote}",
                         [Source(name=f"{title} (via Oxylabs)", url=result["url"])],
                         title=f"{short} on the web: {title}")
        web.news.append(WebItem(title=title, url=result["url"], snippet=quote[:300], evidenceId=eid))
        return
    web.errors.append(f"Oxylabs search found no third-party article naming {short}")


async def investor_site(http: httpx.AsyncClient, key: str, investor: str, profile: StartupProfile,
                        bundle: EvidenceBundle, web: InvestorWeb) -> None:
    """Context.dev: company search finds the website, brand gives the logo, scraping the site
    gives the investor's own words on what it backs."""
    short = _short_name(investor)
    company = await company_search(http, key, short)
    if not company:
        web.errors.append(f"Context.dev found no company profile for {short}")
        return
    domain = company["domain"]
    web.website = f"https://{domain}"
    web.description = clean_markdown(str(company.get("description") or ""))[:300]
    logo_job = asyncio.create_task(brand_logo(http, key, domain))
    page = ""
    try:
        page = await scrape_markdown(http, key, web.website)
    except (httpx.HTTPError, ValueError) as exc:
        web.errors.append(f"Context.dev scrape of {domain}: {_reason(exc)}")
    focus = pick_sentences(page, [], _profile_words(profile) + ["invest", "seed", "early", "stage", "founders", "ticket"])
    focus = focus or web.description
    if focus:
        web.focus = focus[:400]
        web.focusEvidenceId = bundle.add(
            "web", f"{short} website ({domain}): {focus}",
            [Source(name=f"{domain} (via Context.dev)", url=web.website)],
            title=f"{short}: investment focus in its own words")
    try:
        web.logo = await logo_job
    except (httpx.HTTPError, ValueError):
        pass


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
