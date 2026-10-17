"""Deterministic orchestration: who runs when is code, not an LLM decision.

    Triage ∥ Memory(pass 1)  →  Cause  →  extract features  →  Memory(pass 2)  →  Comms

Triage and Memory write to the same graph blackboard concurrently; Cause reads Triage's findings back from the
graph. A failing agent is reported in the stream and the investigation carries on without it.
"""

import asyncio
import importlib
import logging
from collections.abc import Callable
from dataclasses import dataclass

from whygraph.agents.base import AgentContext, BaseAgent, QueryRunner, run_catalog
from whygraph.agents.blackboard import Board
from whygraph.agents.events import EventBus, get_bus
from whygraph.config import get_settings

log = logging.getLogger(__name__)

FeatureExtractor = Callable[[str, str | None], list[str]]


@dataclass
class Team:
    triage: BaseAgent | None = None
    cause: BaseAgent | None = None
    memory: BaseAgent | None = None
    comms: BaseAgent | None = None
    extract_features: FeatureExtractor | None = None


def _load(module: str, attr: str):
    try:
        return getattr(importlib.import_module(module), attr)
    except (ImportError, AttributeError):
        return None  # that feature hasn't landed yet; the investigation runs without it


def default_team() -> Team:
    agents = {}
    for role, cls in [
        ("triage", "TriageAgent"),
        ("cause", "CauseAgent"),
        ("memory", "MemoryAgent"),
        ("comms", "CommsAgent"),
    ]:
        agent_cls = _load(f"whygraph.agents.{role}", cls)
        agents[role] = agent_cls() if agent_cls else None
    return Team(**agents, extract_features=_load("whygraph.graph.features", "extract_features"))


class Orchestrator:
    def __init__(
        self,
        team: Team | None = None,
        bus: EventBus | None = None,
        board_factory: Callable[[str | None], Board] = Board,
        llm_factory: Callable[[], object] | None = None,
        run_query: QueryRunner = run_catalog,
    ) -> None:
        self.team = team or default_team()
        self.bus = bus or get_bus()
        self.board_factory = board_factory
        if llm_factory is None:
            from whygraph.agents.llm import get_llm

            llm_factory = get_llm
        self.llm_factory = llm_factory
        self.run_query = run_query

    async def _run(self, agent: BaseAgent | None, ctx: AgentContext) -> None:
        if agent is None:
            return
        try:
            await agent.run(ctx)
        except Exception as e:
            log.exception("%s failed", agent.name)
            await self.bus.publish(
                ctx.incident_id, "agent.done", agent.name, summary=f"failed: {e}", error=True
            )

    async def investigate(
        self, incident_id: str, graph: str | None = None, graph_only: bool | None = None
    ) -> str:
        graph_only = get_settings().graph_only if graph_only is None else graph_only
        board = self.board_factory(graph)
        inv_id = await asyncio.to_thread(board.open_investigation, incident_id, graph_only)
        ctx = AgentContext(
            incident_id=incident_id,
            investigation_id=inv_id,
            graph=graph,
            bus=self.bus,
            board=board,
            graph_only=graph_only,
            run_query=self.run_query,
            llm=None if graph_only else self.llm_factory(),
        )
        incident = await asyncio.to_thread(board.incident, incident_id) or {"id": incident_id, "alerts": []}
        alerts = incident.pop("alerts", [])
        await self.bus.publish(
            incident_id,
            "incident.opened",
            "orchestrator",
            incident=incident,
            alerts=alerts,
            investigation_id=inv_id,
            graph_only=graph_only or ctx.llm is None,
        )
        team = self.team
        try:
            await asyncio.gather(self._run(team.triage, ctx), self._run(team.memory, ctx.with_phase(1)))
            await self._run(team.cause, ctx)
            if team.extract_features:
                try:
                    await asyncio.to_thread(team.extract_features, incident_id, graph)
                except Exception:
                    log.exception("feature extraction failed")
            await self._run(team.memory, ctx.with_phase(2))
            await self._run(team.comms, ctx)
        finally:
            await asyncio.to_thread(board.close_investigation, inv_id)
            self.bus.close(incident_id)
        return inv_id


_tasks: dict[str, asyncio.Task] = {}


def start_investigation(incident_id: str, graph: str | None = None, delay_s: float = 0.0) -> bool:
    """Start an investigation in the background, at most one at a time per incident."""
    running = _tasks.get(incident_id)
    if running and not running.done():
        return False

    async def go() -> None:
        if delay_s:
            await asyncio.sleep(delay_s)  # let sibling alerts land so Triage sees all of them
        await Orchestrator().investigate(incident_id, graph=graph)

    _tasks[incident_id] = asyncio.get_running_loop().create_task(go())
    return True
