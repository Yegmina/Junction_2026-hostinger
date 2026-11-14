from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Stage = Literal["pre-seed", "seed", "series-a", "series-b", "growth"]
Pestel = Literal["political", "economic", "social", "technological", "environmental", "legal"]


class StartupProfile(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=10, max_length=1500)
    sector: str = Field(min_length=2, max_length=80)
    country: str = Field(default="Europe", min_length=2, max_length=60)
    stage: Stage = "seed"
    targetAmountEur: int = Field(default=2_000_000, ge=10_000, le=500_000_000)
    horizonMonths: int = Field(default=12, ge=3, le=36)

    @property
    def question(self) -> str:
        return (
            f"Will {self.name} close a {self.stage} round of about EUR {self.targetAmountEur:,} "
            f"within {self.horizonMonths} months?"
        )


class Source(BaseModel):
    name: str
    url: str | None = None


class Evidence(BaseModel):
    id: str
    kind: Literal["competitor", "funding", "investor", "market", "graph"]
    title: str = ""
    text: str
    sources: list[Source] = Field(default_factory=list)


class Driver(BaseModel):
    id: str
    name: str
    pestel: Pestel
    description: str
    impact: float = Field(ge=0, le=1)
    uncertainty: float = Field(ge=0, le=1)
    direction: Literal["tailwind", "headwind", "mixed"]
    evidence: list[str] = Field(default_factory=list)


class Axis(BaseModel):
    driverId: str
    name: str
    lowLabel: str
    highLabel: str


class Scenario(BaseModel):
    id: str
    name: str
    position: tuple[Literal["low", "high"], Literal["low", "high"]]
    oneLiner: str = ""
    narrative: str
    probability: float = Field(ge=0, le=1)
    eventProbabilityIfScenario: float = Field(ge=0, le=1)
    signposts: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)


class EventBreakdown(BaseModel):
    scenarioId: str
    weight: float
    conditional: float
    contribution: float


class EventEstimate(BaseModel):
    question: str
    probability: float = Field(ge=0, le=1)
    low: float = Field(ge=0, le=1)
    high: float = Field(ge=0, le=1)
    breakdown: list[EventBreakdown]
    explanation: str


class ScenarioPlan(BaseModel):
    verdict: str = ""
    drivers: list[Driver]
    axes: list[Axis]
    scenarios: list[Scenario]
    event: EventEstimate


class CommitteeMember(BaseModel):
    persona: str
    stance: Literal["back", "conditional", "pass"]
    headline: str = ""
    argument: str
    evidence: list[str] = Field(default_factory=list)


class Conflict(BaseModel):
    company: str
    basis: Literal["graph", "evidence"]
    evidence: str | None = None


class IntroPath(BaseModel):
    person: str
    role: Literal["founder", "CEO", "CTO", "board member"]
    company: str


class TicketMatch(BaseModel):
    stages: list[str] = Field(default_factory=list)
    minEur: float | None = None
    maxEur: float | None = None
    rounds: int = 0
    match: Literal["yes", "partial", "no", "unknown"] = "unknown"
    text: str = ""


class InvestorVerification(BaseModel):
    verified: bool
    entityId: str | None = None
    entityName: str | None = None
    description: str = ""
    portfolio: list[str] = Field(default_factory=list)
    portfolioCount: int = 0
    portfolioCapped: bool = False
    recentDeals: int = 0
    latestDeal: str = ""
    conflicts: list[Conflict] = Field(default_factory=list)
    introPaths: list[IntroPath] = Field(default_factory=list)
    ticket: TicketMatch | None = None


class InvestorTarget(BaseModel):
    name: str
    why: str
    fitScore: float = Field(ge=0, le=1)
    evidence: list[str] = Field(default_factory=list)
    verification: InvestorVerification | None = None


class Committee(BaseModel):
    members: list[CommitteeMember]
    consensus: str
    investorTargets: list[InvestorTarget]
    nextActions: list[str]
