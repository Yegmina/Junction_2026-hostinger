import asyncio

from app.cala import EvidenceBundle
from app.config import get_settings
from app.models import Committee, InvestorTarget, Source, StartupProfile
from app import nemotron
from app.nemotron import citation_check, parse_json
from app.web import _short_name, clean_markdown, domain_of, pick_sentences

PROFILE = StartupProfile(name="Ledgerly", description="AI assistant for CSRD sustainability reporting",
                         sector="climate tech software", country="Finland")


def test_markdown_and_sentence_picking():
    md = "# News\n[Lifeline Ventures](https://x.fi) led a €2M seed round in a climate software startup. Unrelated cookie banner text here, nothing to see."
    assert "https" not in clean_markdown(md)
    quote = pick_sentences(md, ["Lifeline Ventures"], ["seed", "climate"])
    assert quote.startswith("Lifeline Ventures led a €2M seed round")
    assert pick_sentences(md, ["Nobody Capital"], ["seed"]) == ""


def test_names_and_domains():
    assert _short_name("Lifeline Ventures Oy") == "Lifeline Ventures"
    assert domain_of("https://www.lifelineventures.com/team") == "lifelineventures.com"


def test_parse_json_strips_reasoning_and_fences():
    text = '<think>long reasoning {not json}</think>\n```json\n{"audits": [], "summary": "ok"}\n```'
    assert parse_json(text) == {"audits": [], "summary": "ok"}


def _committee(bundle):
    bundle.add("investor", "Lifeline Ventures led a seed round in climate software.", [Source(name="a")])
    bundle.add("investor", "Voima Ventures backs energy startups.", [Source(name="b")])
    return Committee(members=[], consensus="", nextActions=[], investorTargets=[
        InvestorTarget(name="Voima Ventures", why="", fitScore=0.9, evidence=["E1"]),
        InvestorTarget(name="Lifeline Ventures", why="", fitScore=0.8, evidence=["E1"]),
    ])


def test_citation_check_flags_facts_that_do_not_name_the_investor():
    bundle = EvidenceBundle()
    checks = citation_check(_committee(bundle), bundle)
    assert checks["Voima Ventures"] == {"citedFactsNamingIt": [], "citedFactsNotNamingIt": ["E1"]}
    assert checks["Lifeline Ventures"]["citedFactsNamingIt"] == ["E1"]


def test_audit_moves_contradicted_leads_last(monkeypatch):
    async def fake_chat(settings, payload):
        assert payload["shortlist"][0]["citationCheck"]["citedFactsNotNamingIt"] == ["E1"]
        return ('{"audits":[{"name":"Voima Ventures","verdict":"contradicted","reason":"cited fact is about Lifeline",'
                '"evidence":["E1","E99"]},{"name":"Lifeline Ventures","verdict":"supported","reason":"led climate seed",'
                '"evidence":["E1"]}],"summary":"Pitch Lifeline first."}')

    monkeypatch.setattr(nemotron, "_chat", fake_chat)
    bundle = EvidenceBundle()
    out = asyncio.run(nemotron.audit_shortlist(get_settings(), PROFILE, _committee(bundle), bundle))
    assert [t.name for t in out.investorTargets] == ["Lifeline Ventures", "Voima Ventures"]
    assert out.investorTargets[1].audit.verdict == "contradicted"
    assert out.investorTargets[1].audit.evidence == ["E1"]  # unknown ids dropped
    assert out.auditSummary == "Pitch Lifeline first."


def test_deal_sentences_prefer_dated_sized_deals():
    from app.web import deal_sentences
    page = ("Every venture round since January 2024 in which public sources name Acme Capital as an investor.\n"
            "Acme Capital is an investor based in Helsinki with a broad mandate.\n"
            "In March 2026 Acme Capital led a €3M seed round in Verdi, a climate software startup.")
    assert deal_sentences(page, "Acme Capital", ["climate"]).startswith("In March 2026 Acme Capital led")


def test_deal_dashboard_sentences_count_only_on_pages_about_the_investor():
    from app.web import deal_sentences
    page = "# 2C Ventures\n4 venture rounds in the first 9 months of 2026, at 4 companies in 2 countries.\nRounds in 2025"
    assert deal_sentences(page, "2C Ventures", [], about_page=True).startswith("4 venture rounds")
    assert deal_sentences(page, "2C Ventures", [], about_page=False) == ""


def test_own_site_detection():
    from app.web import _own_site
    assert _own_site("Greencode Ventures", "greencode.vc")
    assert _own_site("Lifeline Ventures", "lifelineventures.com")
    assert not _own_site("Lifeline Ventures", "badideas.fund")
    assert not _own_site("2C Ventures", "funding.tech.eu")
