from app.cala import EvidenceBundle
from app.graph import GraphEntity, InvestorGraph, norm, pick_entity
from app.models import Source
from app.verification import CompetitorMap, _conflicts


def test_norm_strips_legal_suffixes():
    assert norm("Capalo AI Oy") == norm("capalo ai") == "capalo ai"


def test_pick_entity_prefers_exact_vc_firm_over_fund_vehicle_and_lookalikes():
    candidates = [
        GraphEntity("1", "Lifeline Ventures Fund V Ky", "Company", "Investment fund"),
        GraphEntity("2", "Lifeline Ventures", "Organization", "Finnish venture capital firm"),
        GraphEntity("3", "Lifeline Ventures AB", "Company", "Swedish holding company"),
        GraphEntity("4", "Lifeline Ventures", "Person", ""),
    ]
    assert pick_entity("Lifeline Ventures", candidates, investor=True).id == "2"


def test_pick_entity_rejects_weak_matches():
    assert pick_entity("Synergi", [GraphEntity("1", "SYNERGI DIGITAL LIMITED", "Company", "UK IT firm")], investor=False) is None


def test_conflicts_from_graph_and_evidence():
    rival = GraphEntity("c1", "Capalo AI Oy", "Company")
    other = GraphEntity("c2", "Sustashift", "Company")
    cmap = CompetitorMap(competitors=[rival, other], backers={})
    graph = InvestorGraph(entity=GraphEntity("i1", "Innovestor", "Organization"),
                          portfolio=[GraphEntity("c1", "Capalo AI Oy", "Company")])
    bundle = EvidenceBundle()
    bundle.add("competitor", "Sustashift raised a seed round led by Innovestor.", [Source(name="Press release")])
    conflicts = {c.company: c for c in _conflicts("Innovestor", graph, cmap, bundle)}
    assert conflicts["Capalo AI Oy"].basis == "graph"
    assert conflicts["Sustashift"].basis == "evidence" and conflicts["Sustashift"].evidence == "E1"


def test_no_conflict_for_unrelated_investor():
    cmap = CompetitorMap(competitors=[GraphEntity("c1", "Capalo AI Oy", "Company")],
                         backers={"c1": [GraphEntity("i9", "Other VC", "Organization")]})
    assert _conflicts("Lifeline Ventures", None, cmap, EvidenceBundle()) == []


def test_competitor_entities_skip_investors_and_own_startup():
    from app.models import StartupProfile
    from app.verification import competitor_entities

    bundle = EvidenceBundle()
    bundle.entities["competitor"] = [
        {"id": "1", "name": "Capalo AI Oy", "entity_type": "Company"},
        {"id": "2", "name": "Innovestor Oy", "entity_type": "Company"},
        {"id": "3", "name": "Heartcore Capital A/S", "entity_type": "Company"},
        {"id": "4", "name": "Ledgerly", "entity_type": "Company"},
        {"id": "5", "name": "Greencode Ventures", "entity_type": "Organization"},
    ]
    profile = StartupProfile(name="Ledgerly", description="CSRD reporting tool", sector="climate", country="Finland")
    assert [c.name for c in competitor_entities(bundle, profile)] == ["Capalo AI Oy"]
