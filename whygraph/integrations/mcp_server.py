"""MCP server for our SDE agents (and any other agent): Why-Graph's memory as tools.

Served at /mcp (streamable HTTP) behind the WHYGRAPH_API_TOKEN bearer token. Read tools only run catalog
queries; `check_change_risk` runs the stored detectors and records that the PR was warned.
"""

import re
from typing import Any

from fastmcp import FastMCP
from fastmcp.server.auth.providers.jwt import StaticTokenVerifier

from whygraph.config import get_settings
from whygraph.graph import client, queries
from whygraph.graph.ids import cfg
from whygraph.integrations.guard import check_change_risk as run_guard
from whygraph.models.events import ChangeRiskRequest, ConfigChange

GRAPH_NAME = re.compile(r"^[A-Za-z0-9_]{1,64}$")
MAX_ROWS = 25

INSTRUCTIONS = """Why-Graph remembers how this company's production broke before and what fixed it.
Before you open a PR that changes config (timeouts, retries, pool sizes, flags) or call paths, call
check_change_risk with the exact changes. If it returns warnings, follow the advice (e.g. the safe_min value)
and cite the lesson id in your PR body. Use who_knows to find the owner or on-call engineer for a service,
why_is to learn why a config value is what it is, and get_service_context before touching an unfamiliar
service. Every answer includes the graph node ids it came from."""


def _graph(graph: str | None) -> str | None:
    if graph and not GRAPH_NAME.match(graph):
        raise ValueError("invalid graph name")
    return graph


def _catalog(query_id: str, params: dict[str, Any], graph: str | None) -> dict[str, Any]:
    graph = _graph(graph)  # validate first, even if the query isn't available
    if query_id not in queries.CATALOG:
        return {"available": False, "detail": f"query {query_id!r} is not in the catalog yet"}
    out = client.run(queries.get(query_id).cypher, params, graph=graph, read_only=True)
    return {
        "available": True,
        "query_id": query_id,
        "rows": out.rows[:MAX_ROWS],
        "row_count": len(out.rows),
        "node_ids": [n.id for n in out.subgraph.nodes],
        "rel_ids": [r.id for r in out.subgraph.rels],
    }


def build_server(auth: bool = True) -> FastMCP:
    token = get_settings().whygraph_api_token
    verifier = StaticTokenVerifier({token: {"client_id": "whygraph-client", "scopes": []}}) if auth else None
    mcp = FastMCP("why-graph", instructions=INSTRUCTIONS, auth=verifier)

    @mcp.tool(annotations={"readOnlyHint": False, "idempotentHint": True})
    def check_change_risk(
        changes: list[ConfigChange],
        title: str | None = None,
        diff: str | None = None,
        author: str | None = None,
        pr_number: int | None = None,
        graph: str | None = None,
    ) -> dict:
        """Check proposed config changes against every lesson and detector learned from past incidents.

        `changes` are services.yaml edits, e.g. {"service": "shipping", "key": "timeouts_ms.quote",
        "old": 600, "new": 100}. Returns a risk level, one warning per matching detector (with the lesson,
        the incident it came from, a safe value and the evidence path) and plain advice.
        """
        req = ChangeRiskRequest(changes=changes, title=title, diff=diff, author=author, pr_number=pr_number)
        return run_guard(req, graph=_graph(graph)).model_dump()

    @mcp.tool(annotations={"readOnlyHint": True})
    def who_knows(service: str, graph: str | None = None) -> dict:
        """Who owns, is on call for, and has hands-on history with a service (commits, resolved incidents)."""
        return _catalog("who_knows", {"svc": service}, graph)

    @mcp.tool(annotations={"readOnlyHint": True})
    def why_is(service: str, key: str, graph: str | None = None) -> dict:
        """Why a config value is what it is: the change, PR, decision, lesson and incident behind it.

        `key` is the dotted services.yaml path under the service, e.g. "timeouts_ms.quote".
        """
        return _catalog("why_is", {"cfg": cfg(service, key)}, graph)

    @mcp.tool(annotations={"readOnlyHint": True})
    def get_service_context(service: str, graph: str | None = None) -> dict:
        """Everything worth knowing before touching a service: dependencies with latencies, and owners."""
        return {
            "service": service,
            "neighbors": _catalog("service_neighbors", {"svc": service}, graph),
            "owners": _catalog("who_knows", {"svc": service}, graph),
        }

    return mcp


mcp = build_server()
