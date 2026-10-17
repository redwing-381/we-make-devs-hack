# Events and API payloads (contract)

> **Contract file.** If you change it, say so in the PR description and ping the other two owners.
> Code mirrors: `whygraph/models/events.py` (pydantic, the source of truth) and `ui/src/types/events.ts`.
> `tests/test_events_contract.py` validates the replay fixtures against these models.

## 1. Ingest (POST, JSON, from the astro-mini watcher, deployer and GitHub ingester)

### `POST /api/alerts`, body `AlertIn`
```json
{ "id": "a-901", "service": "checkout", "signal": "error_rate", "value": 0.62, "threshold": 0.10,
  "severity": "sev2", "ts": 1792305000000, "source": "watcher" }
```
Alerts that arrive within 2 minutes of each other are grouped into one Incident on the server. The response
is `{incident_id, created, investigating}`; a new incident starts the agents after `ALERT_GRACE_S` (5 s), so
sibling alerts land first.

### `POST /api/deploys`, body `DeployIn`
```json
{ "sha": "9f2c1ab", "repo": "org/astro-mini", "services": ["checkout"], "ts": 1792304820000,
  "pr_number": 12, "author": "coder-bot", "message": "Reduce checkout latency",
  "config_changes": [ { "service": "checkout", "key": "timeouts_ms.payment", "old": 800, "new": 200 } ] }
```
`config_changes` is the `services.yaml` diff between the old and new sha, computed by the deployer. Each one
becomes `(Commit)-[:CHANGES {old, new, ts, callee_p99_at_change}]->(ConfigKey)`, with the callee's current
`CALLS.p99_ms` captured so the evidence doesn't drift as telemetry updates. An author ending in `bot` is
stored as `Engineer {kind: 'agent'}`.

### `POST /api/telemetry`, body `TelemetryIn`
`p99_ms` is measured on the **callee side**, so a caller's own timeout can't clip it.
```json
{ "ts": 1792305010000,
  "edges": [ { "caller": "checkout", "callee": "payment", "p99_ms": 452.0, "error_rate": 0.61 } ] }
```

## 2. Agent event stream (SSE)

The stream is served at:
- `GET /api/incidents/{id}/stream` for live runs
- `GET /api/replay/{name}/stream?speed=2` for recorded runs

Every SSE `data:` line is one `AgentEvent`. The live stream replays the history first, then follows until the
investigation finishes and sends `event: end`; add `?follow=false` to get only the history.
`POST /api/incidents/{id}/investigate` re-runs the agents on an existing incident.
`POST /api/incidents/{id}/resolve` with `{fix, cause_finding_id?, resolved_by?}` confirms the root cause
(default: Cause's root-cause finding), closes the incident (`CAUSED_BY`, `RESOLVED`) and, once F-A3 lands,
has Memory write the lesson; it returns `{root_cause_finding_id, caused_by, lesson, lesson_pending}`.

Live events are also written to `scenarios/recordings/live/<incident>.jsonl` and are reloaded after an API
restart. Live runs also append each event to a JSONL file. That is how
`scenarios/recordings/*.jsonl` get produced, and it's why replay and live use exactly the same format.

```json
{ "seq": 12, "ts": 1792305031000, "incident_id": "INC-1031", "type": "agent.finding",
  "agent": "cause", "payload": { "finding": { /* Finding */ } } }
```

| `type` | `agent` | `payload` |
|---|---|---|
| `incident.opened` | orchestrator | `{incident: {id, title, severity, status, started_at}, alerts: [AlertIn], investigation_id, graph_only}` |
| `agent.started` | any | `{phase}`: Memory runs twice (1 = symptoms only, 2 = after Cause) |
| `agent.step` | any | `{tool, query_id, params, ms, summary}`: one tool call (also stored as an `AgentStep` node) |
| `agent.finding` | any | `{finding: Finding}` |
| `agent.handoff` | from-agent | `{to, finding_ids}` |
| `agent.done` | any | `{summary, error?}`: `error: true` if the agent crashed (the investigation carries on) |
| `incident.resolved` | orchestrator | `{root_cause_finding_id, fix, caused_by, lesson_pending}` |
| `memory.lesson_written` | memory | `{lesson: {id, text, confidence}, detector: {id, template, backtest_hits, backtest_total}, evidence: Subgraph}` |
| `guard.checked` | guard | `ChangeRiskResponse` |

The `agent` field is one of `orchestrator`, `triage`, `cause`, `memory`, `comms`, `brain` or `guard`.

### `Finding`
```json
{ "id": "find:INC-1031-1-3", "agent": "cause",
  "claim": "PR #12 by coder-bot lowered checkout→payment timeout 800→200 ms, below payment p99 450 ms",
  "confidence": 0.91, "query_id": "config_vs_reality", "params": { "sha": "9f2c1ab" },
  "cypher": "MATCH ...", "builds_on": ["find:INC-1031-1-1"],
  "evidence": { "nodes": [Node], "rels": [Rel] } }
```

### `Subgraph`, the unit the UI draws and highlights
```json
{ "nodes": [ { "id": "svc:checkout", "label": "Service", "name": "checkout", "props": { "tier": "core" } } ],
  "rels":  [ { "id": "svc:checkout|CALLS|svc:payment", "type": "CALLS",
               "src": "svc:checkout", "dst": "svc:payment", "props": { "p99_ms": 450 } } ] }
```
`evidence.nodes` and `evidence.rels` are ordered along the path. A finding is only accepted if every id in
them appears in the result of re-running `query_id` with `params`. This is the grounding rule.

## 3. Query API (Cypher drawer: "Run live")

- `GET /api/queries` returns the catalog: `[{id, code, title, explain, cypher, example_params}]`.
- `POST /api/query/run` takes `{"query_id": "blast_radius", "params": {...}, "graph": "whygraph_demo"}`.
  - It returns `{rows, subgraph, ms}`.
  - It runs read-only and allow-listed (catalog queries only), with a 2 s timeout.

## 3b. Company Brain

`POST /api/brain/ask` with `{question, graph?, graph_only?}` returns
`{ask_id, question, answer, sources: [node ids], evidence: Subgraph, findings: [Finding], steps: [step payloads],
graph_only}`. Every source is a node from a grounded finding; an LLM answer with no grounded finding is
replaced by the graph-only answer.

## 4. MCP tools (served at `/mcp/` for our SDE agents; same registry our own agents use)

Streamable HTTP, header `Authorization: Bearer $WHYGRAPH_API_TOKEN`; setup in `scenarios/sde-agent-kit.md`.
The same check is available as `POST /api/guard/check?graph=<tenant>` (body `ChangeRiskRequest`), for the
UI's PR Guard tab and the tenant A/B demo.

### `check_change_risk`, input `ChangeRiskRequest`
```json
{ "changes": [ { "service": "shipping", "key": "timeouts_ms.quote", "old": 600, "new": 100 } ],
  "title": "Tune shipping→quote timeout", "diff": "...", "author": "coder-bot", "pr_number": 15 }
```

### Output `ChangeRiskResponse`
```json
{ "risk": "high",
  "warnings": [ { "detector_id": "det:D-1", "lesson_id": "lesson:L-1",
                  "lesson_text": "A caller timeout must stay ≥ 1.5× the callee p99…",
                  "incident_id": "inc:INC-1031", "service": "shipping", "key": "timeouts_ms.quote",
                  "proposed": 100, "safe_min": 450, "evidence": Subgraph } ],
  "advice": "Set timeouts_ms.quote ≥ 450 ms (quote p99 ≈ 300 ms). Lesson L-1 from INC-1031." }
```

### Other tools
- `who_knows(service)` uses the `who_knows` query.
- `why_is(config_key)` uses the `why_is` query.
- `get_service_context(service)` returns owners, dependencies, current p99s, recent incidents and active
  lessons.
- `incident_report(incident_id?)` returns `{found, incident, investigation_id, investigated, root_cause,
  guilty_commit, blast_radius, memory, status_update, findings}`. With no id, it reports the latest open
  incident. It's what an external coordinator reads before assigning a fix.
