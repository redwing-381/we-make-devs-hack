"""Agent interfaces shared by Triage, Cause, Memory, Comms and Brain.

The base defines the shapes only. F-B1 (feat/agent-runtime) implements:
  * the Claude tool loop (catalog queries exposed as tools, step budget <= 8, per-call timeout),
  * `record_finding` grounding: re-run `query_id` with `params`; reject unless every evidence id
    is in the result,
  * the graph-only fallback (deterministic path, no LLM) when GRAPH_ONLY=true or the LLM fails,
  * emitting AgentEvents (SSE + JSONL) and writing AgentStep / Finding nodes.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Protocol

from whygraph.models.events import AgentEvent, AgentName, Finding

Emit = Callable[[AgentEvent], Awaitable[None]]


@dataclass
class AgentContext:
    incident_id: str
    investigation_id: str
    graph: str  # tenant graph name
    emit: Emit
    graph_only: bool = False
    # findings so far, read back from the graph blackboard (not passed between agents in memory)
    findings: list[Finding] = field(default_factory=list)


class Agent(Protocol):
    name: AgentName

    async def run(self, ctx: AgentContext) -> list[Finding]:
        """Investigate using catalog queries only; every returned Finding must be grounded."""
        ...


class GroundingError(ValueError):
    """Raised when a finding cites evidence that its query does not return."""
