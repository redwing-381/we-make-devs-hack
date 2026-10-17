"""Wire contracts. Source of truth for docs/events.md and ui/src/types/events.ts.

Changing anything here is a contract change: call it out in the PR and update the TS mirror.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field

AgentName = Literal["orchestrator", "triage", "cause", "memory", "comms", "brain", "guard"]
EventType = Literal[
    "incident.opened",
    "agent.started",
    "agent.step",
    "agent.finding",
    "agent.handoff",
    "agent.done",
    "incident.resolved",
    "memory.lesson_written",
    "guard.checked",
]
Severity = Literal["sev1", "sev2", "sev3"]


# --- graph shapes the UI draws -------------------------------------------------------------


class GraphNode(BaseModel):
    id: str  # stable string id, e.g. "svc:checkout" (see docs/schema.md)
    label: str
    name: str | None = None
    props: dict[str, Any] = Field(default_factory=dict)


class GraphRel(BaseModel):
    id: str  # "<src id>|<TYPE>|<dst id>"
    type: str
    src: str
    dst: str
    props: dict[str, Any] = Field(default_factory=dict)


class Subgraph(BaseModel):
    nodes: list[GraphNode] = Field(default_factory=list)
    rels: list[GraphRel] = Field(default_factory=list)


# --- ingest --------------------------------------------------------------------------------


class AlertIn(BaseModel):
    id: str | None = None
    service: str
    signal: Literal["error_rate", "latency_p99", "saturation", "custom"]
    value: float
    threshold: float
    severity: Severity = "sev2"
    ts: int  # epoch ms
    source: str = "watcher"


class DeployIn(BaseModel):
    sha: str
    repo: str
    services: list[str]
    ts: int
    pr_number: int | None = None
    author: str | None = None


class EdgeTelemetry(BaseModel):
    caller: str
    callee: str
    p99_ms: float  # measured on the callee side
    error_rate: float


class TelemetryIn(BaseModel):
    ts: int
    edges: list[EdgeTelemetry]


# --- agents --------------------------------------------------------------------------------


class Finding(BaseModel):
    id: str
    agent: AgentName
    claim: str
    confidence: float = Field(ge=0.0, le=1.0)  # computed from graph signals, never by the LLM
    query_id: str
    params: dict[str, Any] = Field(default_factory=dict)
    cypher: str | None = None
    builds_on: list[str] = Field(default_factory=list)
    evidence: Subgraph = Field(default_factory=Subgraph)


class AgentEvent(BaseModel):
    seq: int
    ts: int
    incident_id: str
    type: EventType
    agent: AgentName | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


# --- PR guard / MCP ------------------------------------------------------------------------


class ConfigChange(BaseModel):
    service: str
    key: str  # dotted path in services.yaml, e.g. "timeouts_ms.payment"
    old: float | str | None = None
    new: float | str


class ChangeRiskRequest(BaseModel):
    changes: list[ConfigChange]
    title: str | None = None
    diff: str | None = None
    author: str | None = None
    pr_number: int | None = None


class RiskWarning(BaseModel):
    detector_id: str
    lesson_id: str | None = None
    lesson_text: str | None = None
    incident_id: str | None = None
    service: str
    key: str
    proposed: float | str
    safe_min: float | None = None
    evidence: Subgraph = Field(default_factory=Subgraph)


class ChangeRiskResponse(BaseModel):
    risk: Literal["none", "low", "medium", "high"]
    warnings: list[RiskWarning] = Field(default_factory=list)
    advice: str = ""
