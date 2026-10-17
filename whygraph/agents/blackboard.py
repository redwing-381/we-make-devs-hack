"""The shared blackboard: episodic memory every agent reads and writes in the graph.

Investigation -[:STEP]-> AgentStep, Investigation -[:HAS_FINDING]-> Finding -[:EVIDENCE {order}]-> evidence
nodes, Finding -[:BUILDS_ON]-> Finding. Agents never pass findings to each other in memory; they read them
back from here, which is what makes the coordination real (and survive a restart).
"""

import json
from collections import defaultdict
from typing import Any

from whygraph.agents.events import now_ms
from whygraph.graph import client
from whygraph.graph.ids import LABELS
from whygraph.models.events import Finding


def _write(cypher: str, params: dict[str, Any], graph: str | None) -> client.QueryOutput:
    return client.run(cypher, params, graph=graph, read_only=False)


class Board:
    """Graph-backed blackboard for one tenant graph."""

    def __init__(self, graph: str | None = None) -> None:
        self.graph = graph

    def open_investigation(self, incident_id: str, graph_only: bool) -> str:
        out = _write(
            "MERGE (i:Incident {id: $inc}) "
            "WITH i OPTIONAL MATCH (v:Investigation)-[:FOR]->(i) RETURN count(v) AS n",
            {"inc": f"inc:{incident_id}"},
            self.graph,
        )
        inv_id = f"inv:{incident_id}-{out.rows[0]['n'] + 1}"
        _write(
            "MATCH (i:Incident {id: $inc}) "
            "MERGE (v:Investigation {id: $inv}) "
            "ON CREATE SET v.name = $inv, v.started_at = $ts, v.graph_only = $graph_only "
            "MERGE (v)-[:FOR]->(i)",
            {"inc": f"inc:{incident_id}", "inv": inv_id, "ts": now_ms(), "graph_only": graph_only},
            self.graph,
        )
        return inv_id

    def close_investigation(self, inv_id: str) -> None:
        _write(
            "MATCH (v:Investigation {id: $inv}) SET v.ended_at = $ts",
            {"inv": inv_id, "ts": now_ms()},
            self.graph,
        )

    def record_step(
        self,
        inv_id: str,
        seq: int,
        agent: str,
        tool: str,
        query_id: str,
        params: dict,
        ms: float,
        summary: str,
    ) -> None:
        step_id = f"step:{inv_id.removeprefix('inv:')}-{seq:02d}"
        _write(
            "MATCH (v:Investigation {id: $inv}) "
            "MERGE (s:AgentStep {id: $id}) "
            "SET s.name = $tool, s.agent = $agent, s.tool = $tool, s.query_id = $query_id, "
            "s.params = $params, "
            "s.ms = $ms, s.summary = $summary, s.ts = $ts "
            "MERGE (v)-[r:STEP]->(s) SET r.seq = $seq",
            {
                "inv": inv_id,
                "id": step_id,
                "agent": agent,
                "tool": tool,
                "query_id": query_id,
                "params": json.dumps(params, sort_keys=True),
                "ms": ms,
                "summary": summary,
                "ts": now_ms(),
                "seq": seq,
            },
            self.graph,
        )

    def write_finding(self, inv_id: str, finding: Finding) -> None:
        _write(
            "MATCH (v:Investigation {id: $inv}) "
            "MERGE (f:Finding {id: $id}) "
            "SET f.name = $claim, f.agent = $agent, f.claim = $claim, f.confidence = $confidence, "
            "f.query_id = $query_id, f.params = $params, f.node_ids = $node_ids, f.rel_ids = $rel_ids, "
            "f.evidence_json = $evidence_json, f.ts = $ts "
            "MERGE (v)-[:HAS_FINDING]->(f)",
            {
                "inv": inv_id,
                "id": finding.id,
                "agent": finding.agent,
                "claim": finding.claim,
                "confidence": finding.confidence,
                "query_id": finding.query_id,
                "params": json.dumps(finding.params, sort_keys=True),
                "node_ids": [n.id for n in finding.evidence.nodes],
                "rel_ids": [r.id for r in finding.evidence.rels],
                "evidence_json": finding.model_dump_json(),
                "ts": now_ms(),
            },
            self.graph,
        )
        by_label: dict[str, list[dict]] = defaultdict(list)
        for order, node in enumerate(finding.evidence.nodes):
            if node.label in LABELS:  # label goes into the query text, so it must be a known one
                by_label[node.label].append({"id": node.id, "order": order})
        for label, rows in by_label.items():
            _write(
                f"MATCH (f:Finding {{id: $id}}) UNWIND $rows AS r MATCH (n:{label} {{id: r.id}}) "
                "MERGE (f)-[e:EVIDENCE]->(n) SET e.order = r.order",
                {"id": finding.id, "rows": rows},
                self.graph,
            )
        if finding.builds_on:
            _write(
                "MATCH (f:Finding {id: $id}) UNWIND $ids AS b MATCH (prev:Finding {id: b}) "
                "MERGE (f)-[:BUILDS_ON]->(prev)",
                {"id": finding.id, "ids": finding.builds_on},
                self.graph,
            )

    def read_findings(self, inv_id: str) -> list[Finding]:
        out = client.run(
            "MATCH (:Investigation {id: $inv})-[:HAS_FINDING]->(f:Finding) "
            "RETURN f.evidence_json AS finding ORDER BY f.ts",
            {"inv": inv_id},
            graph=self.graph,
        )
        return [Finding.model_validate_json(r["finding"]) for r in out.rows]

    def latest_investigation(self, incident_id: str) -> str | None:
        out = client.run(
            "MATCH (v:Investigation)-[:FOR]->(:Incident {id: $inc}) "
            "RETURN v.id AS id ORDER BY v.started_at DESC LIMIT 1",
            {"inc": f"inc:{incident_id}"},
            graph=self.graph,
        )
        return out.rows[0]["id"] if out.rows else None

    def incident(self, incident_id: str) -> dict | None:
        out = client.run(
            "MATCH (i:Incident {id: $inc}) "
            "OPTIONAL MATCH (i)-[:TRIGGERED_BY]->(a:Alert)-[:FIRED_ON]->(s:Service) "
            "RETURN i, collect({id: a.id, service: s.name, signal: a.signal, value: a.value, "
            "threshold: a.threshold, "
            "severity: a.severity, ts: a.ts, source: a.source}) AS alerts",
            {"inc": f"inc:{incident_id}"},
            graph=self.graph,
        )
        if not out.rows:
            return None
        props = out.rows[0]["i"]["props"]
        alerts = [a for a in out.rows[0]["alerts"] if a.get("id")]
        return {
            "id": incident_id,
            "title": props.get("title", incident_id),
            "severity": props.get("severity", "sev3"),
            "status": props.get("status", "open"),
            "started_at": props.get("started_at"),
            "alerts": alerts,
        }


class MemoryBoard(Board):
    """In-memory blackboard for unit tests and dry runs (no database)."""

    def __init__(self) -> None:
        super().__init__(None)
        self.steps: list[dict] = []
        self.findings: dict[str, list[Finding]] = defaultdict(list)
        self._n: dict[str, int] = defaultdict(int)

    def open_investigation(self, incident_id: str, graph_only: bool) -> str:
        self._n[incident_id] += 1
        return f"inv:{incident_id}-{self._n[incident_id]}"

    def close_investigation(self, inv_id: str) -> None:
        pass

    def record_step(self, inv_id, seq, agent, tool, query_id, params, ms, summary) -> None:
        self.steps.append({"inv": inv_id, "seq": seq, "agent": agent, "tool": tool, "query_id": query_id})

    def write_finding(self, inv_id: str, finding: Finding) -> None:
        self.findings[inv_id].append(finding)

    def read_findings(self, inv_id: str) -> list[Finding]:
        return list(self.findings[inv_id])

    def latest_investigation(self, incident_id: str) -> str | None:
        n = self._n.get(incident_id)
        return f"inv:{incident_id}-{n}" if n else None

    def incident(self, incident_id: str) -> dict | None:
        return {"id": incident_id, "title": incident_id, "severity": "sev3", "status": "open", "alerts": []}
