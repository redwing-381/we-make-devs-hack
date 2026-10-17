"""Cause: which recent change broke the root service, and how. The one open-ended Sonnet loop.

Reads catalog queries (columns per docs/work-split.md §4 F-A2):
  suspect_changes(root, alert_ts, window_ms)
      -> sha, message, author, kind, service, via, deploy, minutes_before, hops, prior, score,
         path, author_path, config, pr
         (deploys to the root service or anything it depends on, ranked by recency, distance, past failures)
  config_vs_reality(sha)
      -> caller, callee, key, old, new, callee_p99_at_change, below_p99, path
"""

import asyncio
import time

from whygraph.agents.base import AgentRun, BaseAgent, path_ids
from whygraph.graph.client import QueryOutput
from whygraph.models.events import Finding

WINDOW_MS = 30 * 60_000  # work-split §2: deploys up to 30 min before the alert


def short(sha: str | None) -> str:
    return (sha or "?")[:7]


class CauseAgent(BaseAgent):
    name = "cause"
    required = ("suspect_changes", "config_vs_reality")
    tools = ("suspect_changes", "config_vs_reality", "commit_details", "doc_search")
    system = """You are the Cause agent. Triage has already found the root alert and blast radius (see the
board). Your job: find the change that broke the root service.
1. Call suspect_changes for the root service, alert time and window you are given.
2. For the top suspects, call config_vs_reality to see what each commit changed versus how the system behaves.
3. Record a finding naming the top suspect (commit, author, how long before the alert), then a finding
   that explains the mechanism if the evidence shows one (e.g. a timeout set below the callee's p99). Say
   plainly when the evidence does not support a cause. Use builds_on to link your findings to Triage's root
   finding."""

    async def prepare(self, run: AgentRun, prior: list[Finding]) -> bool:
        ctx = run.ctx
        incident = await asyncio.to_thread(ctx.board.incident, ctx.incident_id) or {}
        alerts = [a for a in incident.get("alerts", []) if a.get("service")]
        root_finding = next((f for f in prior if f.agent == "triage" and f.query_id == "root_alert"), None)
        root = None
        if root_finding:
            root = next(
                (
                    n.name or n.id.split(":", 1)[1]
                    for n in root_finding.evidence.nodes
                    if n.label == "Service"
                ),
                None,
            )
        if root is None and alerts:
            root = min(alerts, key=lambda a: a.get("ts") or 0)["service"]  # no Triage finding: earliest alert
        if root is None:
            run.scope["skip"] = "no root service to investigate"
            return False
        root_ts = [a["ts"] for a in alerts if a["service"] == root and a.get("ts")]
        alert_ts = min(
            root_ts or [a["ts"] for a in alerts if a.get("ts")] or [incident.get("started_at") or 0]
        )
        run.scope.update(
            root=root,
            alert_ts=int(alert_ts or time.time() * 1000),
            root_finding=root_finding.id if root_finding else None,
        )
        return True

    def task(self, run: AgentRun, prior: list[Finding]) -> str:
        from whygraph.agents.llm import prior_text

        s = run.scope
        root_finding = s["root_finding"] or "none"
        return (
            f"Incident {run.ctx.incident_id}. Root service: {s['root']}. "
            f"Alert time (epoch ms): {s['alert_ts']}. Window: {WINDOW_MS} ms. "
            f"Triage's root finding: {root_finding}.\n\n{prior_text(prior)}"
        )

    def confidence(self, query_id: str, out: QueryOutput) -> float:
        if query_id == "config_vs_reality":
            return 0.92 if any(r.get("below_p99") for r in out.rows) else 0.3
        return super().confidence(query_id, out)

    async def deterministic(self, run: AgentRun, prior: list[Finding]) -> None:
        s = run.scope
        params = {"root": s["root"], "alert_ts": s["alert_ts"], "window_ms": WINDOW_MS}
        sc = await run.query("suspect_changes", params)
        if not sc.rows:
            run.scope["result"] = f"no deploys to {s['root']} or its dependencies in the window"
            return
        top = sc.rows[0]
        who = top.get("author") or "unknown"
        if (top.get("kind") or top.get("author_kind")) == "agent":
            who += " (AI agent)"
        hops = top.get("hops", 0)
        sha, target = short(top.get("sha")), top.get("service", s["root"])
        claim = (
            f"Top suspect: commit {sha} by {who}, deployed to {target} "
            f"{top.get('minutes_before', top.get('mins_before', '?'))} min before the alert, "
            f"{hops} hop{'s' if hops != 1 else ''} "
            f"from {s['root']}."
        )
        if len(sc.rows) > 1:
            claim += f" {len(sc.rows) - 1} other change{'s' if len(sc.rows) > 2 else ''} ranked lower."
        nodes, rels = path_ids(top)
        suspect = await run.finding(
            claim,
            "suspect_changes",
            params,
            nodes,
            rels,
            builds_on=[s["root_finding"]] if s["root_finding"] else [],
            out=sc,
        )

        cv = await run.query("config_vs_reality", {"sha": top.get("sha")})
        bad = [r for r in cv.rows if r.get("below_p99")]
        row = bad[0] if bad else (cv.rows[0] if cv.rows else None)
        if row is None:
            run.scope["result"] = f"{sha} changed no tracked config"
            return
        edge, p99 = f"{row['caller']}→{row['callee']}", row["callee_p99_at_change"]
        if bad:
            claim = (
                f"Root cause: {sha} set the {edge} timeout ({row['key']}) from {row['old']} to "
                f"{row['new']} ms, below {row['callee']}'s p99 of {p99} ms, "
                f"so most {edge} calls now time out."
            )
        else:
            claim = (
                f"{sha} changed {row['caller']} {row['key']} {row['old']}→{row['new']}, which stays above "
                f"{row['callee']}'s p99 ({p99} ms); it does not explain the alert on its own."
            )
        nodes, rels = path_ids(row)
        await run.finding(
            claim,
            "config_vs_reality",
            {"sha": top.get("sha")},
            nodes,
            rels,
            builds_on=[suspect.id],
            confidence=round(min(0.99, 0.6 + 0.4 * suspect.confidence), 2) if bad else 0.3,
            out=cv,
        )
        run.scope["result"] = f"root cause: {sha}" if bad else "no mechanism found"

    def summary(self, run: AgentRun) -> str:
        return run.scope.get("result") or super().summary(run)
