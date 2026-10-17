# Why-Graph: Hackathon Build Plan (FalkorDB "Graph Hacks", deadline Sun Oct 18, 11:59 PM IST)

## Context

We have about 30 hours, 3 people and an empty repo (`we-make-devs-hack`, not yet a git repo).

**The brief.** FalkorDB must be central: "if the product still works once FalkorDB is taken out, the graph is
decoration." The judges want agents whose decisions you can trace. There are three tracks: act on connected
data, memory and coordination, and company brain. We enter all three.

**What we're building: Why-Graph.**
1. Agents investigate production incidents and prove each conclusion with a graph path.
2. They remember what fixed each incident.
3. They feed those lessons back to **our own AI SDE agent team** (which opens GitHub PRs and can call MCP
   tools), so the same mistake is caught before it ships again.

**Decisions made:**
- Python (FastAPI) + React/Vite.
- Claude: `claude-sonnet-5-5` for reasoning, `claude-haiku-5-5` for cheap steps.
- Voyage embeddings.
- A closed loop with our SDE agents through MCP and GitHub PRs.
- A real mini app that actually breaks.
- A live deployment.

**Pitch:** "Your AI engineers ship 24/7. Why-Graph is the shared graph brain that works out why prod broke,
proves it with a path, and makes sure no agent ships that mistake twice."

| Track | What judges see |
|---|---|
| 1. Act on connected data | Multi-hop root-cause and blast-radius queries, graph algorithms as agent tools, tools served over MCP, real actions (PR comments, paging owners via OWNS edges) |
| 2. Memory & coordination | **Episodic** (Incident, Investigation, Finding), **semantic** (Lesson, FailurePattern + vectors), **procedural** (Detector = stored Cypher); 4 agents sharing one graph blackboard; memory survives restarts; one graph per tenant |
| 3. Company brain | People, teams, agents, ownership, commits, runbooks, decisions in one graph; "who knows checkout?"; "why is this timeout 400 ms?" traced back to the incident and PR; stale-runbook detection |

**The anti-decoration proof is a UI toggle called "Graph-only mode".** With the LLM switched off, the same
root cause, evidence path and lesson match still come out. The LLM only writes the narrative.

---

## 1. Demo arc (everything is built backwards from this; video about 3 min)

**Act 1: never seen before (about 90 s)**
1. SDE agent task: "Reduce checkout latency." Its PR sets the `checkout → payment` timeout to **200 ms**.
   Payment's p99 is about 450 ms, measured on the callee side.
2. PR Guard comments "No known risk" and the PR merges.
3. The deployer hot-reloads, checkout starts throwing real 5xx errors, and the watcher fires alerts on checkout
   and frontend.
4. The agents work it out live:
   - **Triage** finds the root alert (the deepest alerting service is checkout; payment is healthy) and lights
     up the blast radius.
   - **Cause** ranks PR #12 by `coder-bot` first, with this evidence path:
     `Alert → checkout -[CALLS p99=450]→ payment ← TARGETS ← ConfigKey(timeout: 800→200) ← CHANGES ← Commit ← PR#12 ← coder-bot`
   - **Memory** says "No strong match (best 0.31). New failure pattern."
   - **Comms** drafts the status update and pages the payments on-call engineer and the PR author.
5. A human clicks **Confirm root cause + fix**. Memory then writes a Lesson, a Decision and a Detector. The
   Detector is stored Cypher, self-validated against this incident and backtested over history ("fires on 1 of
   312 past commits").

**Restart on camera (about 10 s).** Run `docker compose restart api` and start a brand-new SDE agent session.
Nothing lives in process memory; only the graph remembers.

**Act 2: the AI now knows (about 40 s, the money shot)**
1. SDE agent task: "Tune the `shipping → quote` timeout for speed." The prompt says nothing about the lesson.
2. Before opening the PR, the agent calls the MCP tool `whygraph.check_change_risk`. Detector D-1 fires, and the
   agent gets Lesson L-1, the evidence path and `safe_min ≈ 1.5×p99`.
3. The agent picks 450 ms instead of 100 ms. The PR comment reads "Lesson L-1 applied".
4. In the Memory tab the lesson goes from confidence 0.6 to 0.8 with `prevented: 1`.
5. **Tenant A/B:** run the same call against `whygraph_fresh`. It returns no warning. Same code, different graph,
   different behavior.

**Act 3 (optional, about 20 s): override and recall**
1. A human overrides the PR Guard warning on `recommendation → product-catalog` ("catalog is fast") and merges.
2. The incident follows, and Memory recalls INC-1031 **in about 3 s** compared with Act 1's 90 s.
3. The graph records `PR-[:IGNORED]->Lesson`.

**Close (about 20 s)**
1. Click any claim to open the Cypher drawer, click **Run live**, and watch the path re-highlight.
2. Flip **Graph-only mode** and get the same answer.
3. Ask the Brain "Why is shipping→quote 450 ms?" and it answers Decision ← L-1 ← INC-1031 ← PR #12 ← coder-bot.

**Every act has a fallback:**
- `scenarios/actN.patch`, a pre-made commit.
- `scenarios/inject.py`, which replays deploy + alert events with no app.
- `scripts/reset_to.py actN`, which snapshots or restores the graph so we can rehearse in a loop.

---

## 2. Resources we provide up front (Hour 0)

**Keys** (go in `.env`, never committed; commit `.env.example`):
- `ANTHROPIC_API_KEY`.
- `VOYAGE_API_KEY`. The auth0 link you shared is the old dashboard. New keys come from **MongoDB Atlas → AI
  Model APIs**, and SDK 0.3.7+ picks the endpoint on its own. **Add a card:** that lifts the limit from 3 RPM /
  10K TPM to 2000 RPM, and the 200M free tokens still apply.
- `GITHUB_TOKEN`. A fine-grained PAT scoped to `astro-mini` only, so it can read PRs and write PR comments.

**Repos**
- `we-make-devs-hack`: `git init` it and create a public GitHub remote. This is the submission.
- `astro-mini`: a new public repo for the demo app. Our SDE agents open PRs here using a bot account, which shows
  up in the graph as `Engineer{kind:'agent'}`.

**Infra**
- A VM (4 vCPU / 8 GB, any provider) with a subdomain or `sslip.io`, and Caddy for HTTPS.
- `falkordb/falkordb:v6.0.2`, which includes the Browser on port 3000.
- Pin the version only after the Hour-1 smoke test. 6.0 is a brand-new Rust engine, so the 4.x line is the
  fallback.

**Synthetic data** (seeded, template-based, committed; no LLM-written filler):
- **Services:** about 30. The 9 at the core follow the OpenTelemetry demo topology (Apache-2.0, credited):
  frontend, checkout, payment, cart, currency, product-catalog, recommendation, shipping and quote, plus a
  Kafka `orders` topic feeding accounting and fraud-detection. Around them are synthetic ones: auth, search,
  inventory, notifications and so on.
- **People:** 6 teams, 20 engineers plus our SDE agents, with on-call flags.
- **History:** 30 days with about 120 deploys and 300 commits.
- **Past incidents:** 20, across 6 patterns: DB pool exhaustion, retry storm, cert expiry, bad dependency bump,
  flag misconfig and Kafka lag. Each comes with a resolution, a lesson, a runbook and a short chat thread. The
  timeout pattern is **deliberately missing**, so Act 1 is genuinely new.
- **Embeddings:** `voyage-4-lite` at 1024 dims, cached in `seed/embeddings_cache.json` so reseeding works
  offline.

**SDE agent kit**
- The MCP URL and token.
- A system-prompt snippet: "Before opening a PR that changes config or call paths, call
  `whygraph.check_change_risk` with your proposed changes; follow its advice and cite any lesson id in the PR
  body."
- Task prompts in `scenarios/act{1,2,3}.md`.

---

## 3. Architecture: how it all connects

```
 Our SDE agents ──open PR──▶ GitHub: astro-mini ◀──poll 10s / comment── GitHub ingester ─┐
      │  MCP (check_change_risk, who_knows, why_is, get_service_context)                  │
      ▼                              │ merge                                               ▼
 Why-Graph API (FastAPI) ◀──POST /deploys── deployer (git pull 5s → hot reload)        FalkorDB
   ├─ /mcp  (FastMCP; the same tool registry our own agents use via in-memory client)    ▲
   ├─ orchestrator → Triage ∥ Memory → Cause → Memory(refine) → Comms ── read/write ──────┘
   ├─ SSE /incidents/{id}/stream  (every event also logged to JSONL for replay)
   └─ /query/run (read-only, allow-listed) · /brain/ask · /graph-only toggle
 astro-mini (1 container, 9 services as routers calling each other over real HTTP with real timeouts)
   └─ watcher: load gen + reads callee-side latency/err → POST /telemetry (updates CALLS.p99_ms), /alerts
 UI (React + @falkordb/canvas): Incident · PR Guard · Memory · Brain · Replay
```

**astro-mini**
- One FastAPI app with one router per service. Services call each other through `httpx` over localhost, using
  the timeouts in `config/services.yaml`.
- Each service's own latency is simulated with a seeded RNG: payment ~N(350,60), quote ~N(300,50),
  product-catalog ~N(120,30).
- `/metrics` reports **callee-side** processing p99. If the caller measured latency, the timeout would clip it
  and corrupt the evidence.
- It's one container instead of 9: the HTTP calls and timeouts are real, but there's much less to operate.

**Ingestion is deterministic.** The `services.yaml` diff between base and head is parsed on the server into
`CHANGES{old,new,ts,callee_p99_at_change}` edges. No LLM is involved in parsing.

**Alert grouping.** Alerts that arrive within 2 minutes of each other join one Incident.

---

## 4. Graph schema (one graph per tenant: `whygraph_demo`, `whygraph_fresh`, `whygraph_sbx_<id>`)

**Nodes**
- **Org:**
  - `Service{name, tier:edge|core|data}`
  - `Topic`
  - `Team`
  - `Engineer{handle, kind:human|agent, on_call}`
- **Change:**
  - `PR{number, title, state}`
  - `Commit{sha, message, ts}`
  - `File{path}`
  - `ConfigKey{service, key, kind:timeout|retries|pool|flag, value}`
  - `Deploy{id, ts}`
- **Incident:**
  - `Alert{id, ts, signal, incident_id}`
  - `Incident{id, title, summary, status, severity, started_at, resolved_at, embedding}`
  - `Feature{name}`, used for service-agnostic shape matching
- **Episodic:**
  - `Investigation`
  - `AgentStep{agent, tool, params, ms, ts}`
  - `Finding{id, agent, claim, confidence, query_id, params, node_ids, rel_ids}`
- **Semantic:**
  - `Lesson{id, text, embedding, confidence, uses, prevented, status, created_at}`
  - `FailurePattern{name}`
  - `Decision{title, text}`
  - `Runbook{title, text, updated_at, embedding}`
  - `ChatMessage{text, ts}`
- **Procedural:** `Detector{id, template, cypher, params, backtest_hits}`

**Edges**
- **Topology and ownership:**
  - `(Service)-[:CALLS{p99_ms, error_rate}]->(Service)`
  - `(Service)-[:PUBLISHES]->(Topic)<-[:CONSUMES]-(Service)`
  - `(Team)-[:OWNS]->(Service)`
  - `(Engineer)-[:MEMBER_OF]->(Team)`
- **Changes:**
  - `(PR)-[:CONTAINS]->(Commit)-[:AUTHORED_BY]->(Engineer)`
  - `(Commit)-[:TOUCHES]->(File)-[:BELONGS_TO]->(Service)`
  - `(Commit)-[:CHANGES{old,new,ts,callee_p99_at_change}]->(ConfigKey)-[:CONFIGURES]->(caller)`, with
    `(ConfigKey)-[:TARGETS]->(callee)`
  - `(Deploy)-[:SHIPS]->(Commit)` and `(Deploy)-[:OF]->(Service)`
- **Incidents:**
  - `(Alert)-[:FIRED_ON]->(Service)` and `(Incident)-[:TRIGGERED_BY]->(Alert)`
  - `(Incident)-[:IMPACTED|HAS_FEATURE|CAUSED_BY|RESOLVED_BY]->(…)`
  - `(Incident)-[:SIMILAR_TO{score, shared}]->(Incident)`
- **Agent blackboard:**
  - `(Investigation)-[:FOR]->(Incident)`
  - `(Investigation)-[:STEP{seq}]->(AgentStep)`
  - `(Investigation)-[:HAS_FINDING]->(Finding)-[:EVIDENCE{order}]->(any)`
  - `(Finding)-[:BUILDS_ON]->(Finding)`: this is the handoff between agents
- **Learning:**
  - `(Lesson)-[:LEARNED_FROM]->(Incident)`
  - `(Lesson)-[:ABOUT]->(FailurePattern)<-[:DETECTS]-(Detector)`
  - `(Lesson)-[:SUPERSEDES]->(Lesson)`
  - `(PR)-[:WARNED_WITH|APPLIED|IGNORED]->(Lesson)`
  - `(Decision)-[:FROM]->(Lesson)`
  - `(PR)-[:IMPLEMENTS]->(Decision)`
  - `(Runbook)-[:MENTIONS]->(ConfigKey|Service)`
  - `(Engineer)-[:RESOLVED]->(Incident)`

**Indexes**
- Unique constraints and indexes on every `id`, `sha` and `name`. All writes use `MERGE`, so they're idempotent
  and safe when agents write at the same time.
- Vector indexes (1024 dims, cosine) on `Incident`, `Lesson` and `Runbook`.
- A full-text index on `Runbook.text` and `ChatMessage.text`.
- All times are epoch-ms integers, because FalkorDB has no temporal arithmetic.

---

## 5. Named query catalog (`whygraph/graph/queries.py`)

Each query has an id, its Cypher, a plain-English explanation and example params. The same catalog generates
the README section, the agent tools and the MCP tools. **Agents can only call these.** The one exception is an
optional read-only "explore" tool through the official `@falkordb/mcpserver`.

```cypher
// Q0 root_alert — the deepest alerting service (alerting, with nothing alerting below it)
MATCH (a:Alert {incident_id:$inc})-[:FIRED_ON]->(s:Service)
OPTIONAL MATCH (s)-[:CALLS*1..4]->(d:Service)<-[:FIRED_ON]-(:Alert {incident_id:$inc})
WITH s, a, count(d) AS deeper WHERE deeper = 0
RETURN s.name, a.id

// Q1 blast_radius — callers that suffer, transitively (async consumers returned separately as "delayed")
MATCH (s:Service {name:$svc}) MATCH p=(s)<-[:CALLS*1..5]-(up:Service)
WITH up, p ORDER BY length(p) WITH up, collect(p)[0] AS path
RETURN up.name, up.tier, length(path) AS hops, path ORDER BY hops

// Q2 suspect_changes — recent changes on the root service, its dependencies, or config that targets them
MATCH (s:Service {name:$root}) MATCH p=(s)-[:CALLS*0..3]->(dep:Service)
MATCH (dep)<-[:OF]-(d:Deploy)-[:SHIPS]->(c:Commit)-[:AUTHORED_BY]->(who:Engineer)
WHERE d.ts <= $alert_ts AND d.ts >= $alert_ts - $window_ms
OPTIONAL MATCH (dep)<-[:IMPACTED]-(past:Incident)
WITH c, who, dep, d, count(DISTINCT past) AS prior, min(length(p)) AS hops, collect(p)[0] AS path
RETURN c.sha, c.message, who.handle, who.kind, dep.name, hops, prior,
       0.5/(1+($alert_ts-d.ts)/600000.0) + 0.3/(1+hops) + 0.2*prior/(prior+1.0) AS score, path
ORDER BY score DESC LIMIT 5

// Q3 config_vs_reality — did the change set a timeout below what the callee needs?
MATCH (c:Commit {sha:$sha})-[ch:CHANGES]->(k:ConfigKey)-[:CONFIGURES]->(a:Service)-[e:CALLS]->(b:Service)<-[:TARGETS]-(k)
RETURN a.name, b.name, k.key, ch.old, ch.new, ch.callee_p99_at_change, ch.new < ch.callee_p99_at_change AS below_p99

// Q4 similar_incidents — shape-feature Jaccard in Cypher (primary) + Voyage cosine (tie-breaker, 0.3 weight)
MATCH (cur:Incident {id:$id})-[:HAS_FEATURE]->(f)<-[:HAS_FEATURE]-(past:Incident {status:'resolved'})
WITH cur, past, collect(f.name) AS shared
MATCH (cur)-[:HAS_FEATURE]->(cf) WITH past, shared, count(cf) AS cn
MATCH (past)-[:HAS_FEATURE]->(pf) WITH past, shared, cn, count(pf) AS pn
RETURN past.id, shared, toFloat(size(shared))/(cn+pn-size(shared)) AS jaccard ORDER BY jaccard DESC LIMIT 5
// + CALL db.idx.vector.queryNodes('Incident','embedding',10,vecf32($q)) YIELD node, score

// Q5 who_knows — ownership + on-call + hands-on history (commits, resolutions)
MATCH (s:Service {name:$svc})<-[:OWNS]-(t:Team)<-[:MEMBER_OF]-(e:Engineer)
OPTIONAL MATCH (e)<-[:AUTHORED_BY]-(c:Commit)-[:TOUCHES]->(:File)-[:BELONGS_TO]->(s)
OPTIONAL MATCH (e)-[:RESOLVED]->(i:Incident)-[:IMPACTED]->(s)
RETURN e.handle, e.kind, e.on_call, t.name, count(DISTINCT c) AS commits, count(DISTINCT i) AS resolved
ORDER BY e.on_call DESC, resolved DESC, commits DESC LIMIT 5

// Q6 = Detector D-1 (template timeout_below_p99) — service-agnostic, runs pre-merge on proposed changes
UNWIND $changes AS ch
MATCH (k:ConfigKey {service:ch.service, key:ch.key, kind:'timeout'})-[:CONFIGURES]->(a)-[e:CALLS]->(b)<-[:TARGETS]-(k)
WHERE ch.new < e.p99_ms * 1.5
RETURN a.name, b.name, ch.new, e.p99_ms, toInteger(e.p99_ms * 1.5) AS safe_min
```

Other catalog entries:
- **Q7 `why_is`:** walks from a ConfigKey through CHANGES, Commit and PR to the Decision, Lesson and Incident.
- **Q8 `doc_search`:** vector plus full-text search over runbooks and chat.
- **Q9 `criticality`:** `algo.pageRank('Service','CALLS')`. It feeds **incident severity** and the **PR Guard
  risk tier**, so the result visibly changes something.
- **Q10 `stale_runbooks`:** runbooks that mention a ConfigKey changed after the runbook's `updated_at`.
- **Q11 `investigation_timeline`.**
- **Q12 `detector_backtest`:** runs a detector over every historical CHANGES edge.

**Hour-1 smoke test on FalkorDB 6.0.2:**
- The vector index, including whether `score` is a distance or a similarity.
- `collect(p)[0]`.
- Variable-length paths with `OPTIONAL MATCH`.
- `algo.pageRank` and `algo.betweenness`.
- The full-text index.
- Constraints.
- `GRAPH.COPY` (for snapshots and sandboxes; if it's missing, fall back to reloading the seed).

---

## 6. Agents (`whygraph/agents/`). Four named agents, one shared graph blackboard

**The orchestrator is deterministic Python.**
1. On an alert it creates the Incident and Investigation.
2. It runs **Triage ∥ Memory(first pass)** at the same time; they write concurrently.
3. **Cause** runs next and reads Triage's Findings from the graph.
4. Features are extracted.
5. **Memory(refine)** runs.
6. **Comms** runs last.

Every agent has:
- a deterministic **graph-only** path;
- a step budget (8 or fewer tool calls);
- a timeout per call;
- a fallback to graph-only if the LLM fails.

| Agent | How it works | Tools (catalog ids) |
|---|---|---|
| **Triage** | Deterministic queries; Haiku writes a one-line summary | Q0, Q1, Q9 |
| **Cause** | The one open-ended **Sonnet tool loop**. It picks among the tools, then must ground its claim | Q2, Q3, `commit_details`, Q8, `read_findings` |
| **Memory** | Deterministic Feature extraction + Q4 + all active Detectors. Haiku writes the phrasing. On resolve, Sonnet picks a detector template and params, which are **self-validated** (the detector must fire on this incident) and **backtested** (Q12) before saving | Q4, Q6…, Q12, `write_lesson` |
| **Comms** | One Haiku call over Findings + Q5. Writes `ChatMessage` nodes (status update, who was paged) | Q5, `read_findings` |
| **Brain** | Sonnet Q&A for the Brain tab. Answers come with clickable source chips | Q5, Q7, Q8, Q10 |

- **Grounding rule ("no claim without a path"):**
  - `record_finding(claim, query_id, params, node_ids, rel_ids)` re-runs the cited query and checks that every
    id is in the result. If not, the finding is rejected and the agent retries.
  - **Confidence is computed from graph signals** (hops, recency, whether a detector fired, Jaccard, lesson
    uses). The LLM never assigns it.
- **Tools reach the agents through MCP.**
  - The catalog is served by FastMCP at `/mcp` for our SDE agents.
  - Our own agents load the same tools through FastMCP's in-memory client. The UI shows a tool-selection trace
    (`AgentStep` nodes).
- **Features** are deterministic Cypher run after Cause. Examples:
  - `symptom:caller_5xx_callee_healthy`
  - `change:timeout_decrease`
  - `motif:timeout_lt_callee_p99`, which means detector template D-1 fired
  - `author:agent`
  - `trigger:deploy_lt_10m`
  - `topology:sync_call`

  Because none of them name a service, checkout→payment matches shipping→quote.
- **`check_change_risk`** (MCP and PR Guard) is deterministic:
  1. Run the active Detectors and Q9 for the risk tier.
  2. Run a vector search for lessons similar to the PR title and diff.
  3. Haiku writes the advice.
  4. Write `PR-[:WARNED_WITH]->Lesson`, and later `APPLIED` or `IGNORED`.
- **Lesson lifecycle:**
  - Applied: confidence up, `prevented` +1.
  - Ignored and then an incident: confidence up, and an `IGNORED` edge.
  - Unused for a long time: slow decay.
  - Replaced by a newer lesson: `SUPERSEDES`.

---

## 7. UI (`ui/`, React + Vite + TS)

- **Incident view:**
  - Agent lanes showing live steps over SSE.
  - The graph canvas: `@falkordb/canvas`, the sponsor's component, in tree layout for the causal chain. Spike it
    in the first hour; fall back to react-force-graph or Cytoscape.
  - **Finding cards.** Clicking one highlights the exact nodes and edges in its path, dims everything else, and
    opens a **Cypher drawer** with the query, the params and **Run live** (`ro_query`, allow-listed, 2 s
    timeout).
  - A **Confirm root cause + fix** button.
  - The **Graph-only mode** toggle.
- **PR Guard tab:** PRs with their risk verdict, the detector that fired, and the lesson cited.
- **Memory tab:** lessons with confidence, uses and prevented counts over time; detectors with their backtest
  hits; labeled episodic, semantic and procedural.
- **Brain tab:** an ask box whose answers carry source chips.
- **Replay:** replays a recorded JSONL event log at 1–4× speed. **This is the live site's default.**

---

## 8. Repo layout

```
we-make-devs-hack/
  docker-compose.yml  .env.example  Caddyfile  README.md
  docs/  schema.md  events.md  demo-script.md
  whygraph/
    api/main.py               # routes, SSE, /query/run, /brain/ask
    graph/  client.py  queries.py  writeback.py  features.py
    memory/ detectors.py      # templates, self-validate, backtest
    agents/ base.py  orchestrator.py  triage.py  cause.py  memory.py  comms.py  brain.py
    integrations/ mcp_server.py  github.py  ingest.py
    embeddings.py             # Voyage + cache
  seed/  generate.py  load.py  data/*.json  embeddings_cache.json
  scripts/ reset_to.py  smoke_falkordb.py
  scenarios/ act1.md act2.md act3.md  *.patch  inject.py  recordings/*.jsonl
  ui/src/ pages/Incident.tsx  components/{GraphCanvas,FindingCard,CypherDrawer,PRGuard,Memory,Brain}.tsx
  tests/ test_queries.py  test_grounding.py  test_scenarios.py
astro-mini/  app/main.py  config/services.yaml  watcher/  deployer/  Dockerfile
```

---

## 9. Team split (each person owns their area and can explain it to judges)

| | **A: Graph & Memory** | **B: Agents & Integrations** | **C: UI, demo app & deploy** |
|---|---|---|---|
| Tonight | Smoke test, generator + loader, constraints/indexes, Q0–Q5, `test_queries.py`, embedding cache | Catalog → tools, `record_finding` grounding, orchestrator + SSE + JSONL log, Triage + Cause end-to-end on `inject.py` | astro-mini + watcher + deployer, UI shell, canvas spike, render the fixture investigation |
| Morning | Features, Q4, detectors + self-validate + backtest, lesson/decision write-back, Q6, Q7, `reset_to.py` | Memory + Comms, resolve flow, FastMCP server, wire up our SDE agents, GitHub ingester + PR comments | Path highlight, Cypher drawer + Run live, agent lanes, Graph-only toggle, PR Guard + Memory tabs |
| Afternoon | Q8–Q10, tenant A/B graphs, README schema and queries | Brain agent, reliability pass (budgets, fallbacks, prompt caching) | VM deploy (compose + Caddy), replay player, Brain tab, polish |
| Evening | README and blog post (side prize) | Drive the SDE agents for recording | Record and edit the video |

**Hour-0 contracts.** All three people write these together, so everyone can explain the model:
- `docs/schema.md`
- `docs/events.md`, which defines:
  - the Alert, Deploy, Telemetry and PR payloads;
  - the SSE event `{type: step|finding|handoff|done, agent, payload, node_ids, rel_ids}`.
- API route stubs.
- `scenarios/recordings/fixture.jsonl`, so C can build the UI before any agent exists.

---

## 10. Timeline (IST)

| When | Milestone |
|---|---|
| Sat 18:00–19:00 | Keys, repos, `git init`, compose up, FalkorDB-6 smoke test, contracts |
| 19:00–00:30 | Tonight's column of the split |
| **00:30 checkpoint** | `inject.py act1` → Triage + Cause findings → UI highlights the evidence path |
| 00:30–07:00 | Sleep |
| 07:00–12:00 | Morning's column |
| **12:00 GATE** | Act 1 runs end-to-end locally with a real SDE agent PR. **If it doesn't, cut Act 3, the sandbox and Brain on the spot** |
| 12:00–16:30 | Restart + Act 2, tenant A/B, VM deploy, replay, Brain, polish |
| **16:30** | **Feature freeze.** Bug fixes only from here |
| 16:30–20:30 | Rehearse 3× with `reset_to.py`, record each act separately and keep the best take, README, blog |
| **21:00** | **Submit.** Buffer until 23:59 |

## 11. Scope

- **Must:**
  - Smoke test, seed data, query catalog Q0–Q6, the 4 agents with grounding and graph-only mode.
  - Lesson + Detector write-back with self-validation; MCP `check_change_risk`.
  - astro-mini breaking for real.
  - Evidence-path UI + Cypher drawer.
  - Acts 1 and 2, `reset_to.py`, README, video.
- **Should:**
  - PR Guard comment on GitHub.
  - Detector backtest.
  - Tenant A/B.
  - pageRank feeding severity.
  - Stale runbooks.
  - Live VM in replay mode.
  - The Brain tab.
- **Could:**
  - Act 3 (override and recall).
  - A per-visitor sandbox (GRAPH.COPY + graph-only live runs).
  - Voyage `rerank-3`.
  - A JS UDF for scoring.
  - The blog post.
- **Cut:**
  - LLM-parsed diffs.
  - LLM-assigned confidence.
  - Free-form Cypher from agents.
  - 9 separate service containers.
  - Graphiti. It calls an LLM on every episode, which is too slow, and our own schema is easier to explain.

## 12. Risks → mitigations

- **The LLM goes off-script.**
  - Deterministic orchestrator, catalog-only tools, step budgets, the grounding check and graph-only fallback.
  - Cache prompts and responses for demo mode.
  - The live site defaults to Replay.
  - A global cost kill-switch and per-IP rate limit.
- **"The graph is decoration."** The Graph-only toggle, every feature being a named query, and detectors as
  stored Cypher.
- **"It looks AI-generated."**
  - All 3 of us can explain every query.
  - The README is plain prose, with a "real vs simulated" table and measured query latencies.
  - Commits come from all 3 people.
  - AI use is disclosed in two parts: the AI coding assistants we used to build, and the fact that our
    **pre-existing** SDE agent team is an *external MCP client and actor in the demo*. All Why-Graph and
    FalkorDB work is new.
- **Voyage limits.** Add a card and cache all seed and scenario embeddings. Structural similarity works even
  if Voyage is down.
- **FalkorDB 6 quirks.** The Hour-1 smoke test plus `test_queries.py`, with the 4.x image as fallback.
- **The SDE agent flakes on camera.** Fall back to `.patch` plus a CLI that calls the same MCP tool, and record
  each act separately.

## 13. Submission checklist

- A public repo.
- A README with:
  - pitch and architecture;
  - a Mermaid schema diagram;
  - the query catalog with plain-English explanations;
  - setup (`docker compose up && python seed/load.py`);
  - the live link;
  - **all 3 tracks named**;
  - the AI disclosure;
  - OTel Apache-2.0 attribution.
- The demo video (about 3 min).
- A link to the `astro-mini` repo.

## 14. Verification

**`pytest tests/`:**
- Every catalog query runs on the seeded graph.
- Q0 on the Act 1 fixture returns `checkout`. Q2 ranks PR #12 first. Q3 gives `below_p99 = true`.
- Q6 fires for 200 ms and stays silent for 800 ms.
- `test_scenarios`:
  - Act 1's best Memory match is under the threshold (0.5).
  - After the lesson is written, Act 2's detector fires and the Q4 Jaccard is at least 0.6.
  - The `whygraph_fresh` tenant returns no warning.
- `test_grounding`: a fabricated `node_id` gets rejected.

**Manual end-to-end runs:**
1. `inject.py act1`. Every finding's ids exist. After Confirm,
   `MATCH (l:Lesson)-[:LEARNED_FROM]->(:Incident {id:'INC-1031'}) RETURN l` returns one row.
2. Restart `api`. Call MCP `check_change_risk` with `{service:'shipping', key:'quote', new:100}` and get back
   L-1 and `safe_min`.
3. Toggle Graph-only mode: the root cause and the lesson match stay the same.
4. Full live run on the VM in a browser: a real SDE agent PR, merge, real 5xx, alert, investigation, resolve,
   restart, then Act 2.

## 15. First moves after approval (this session)

1. Hour-0 scaffold: `git init`, `docker-compose.yml` (FalkorDB pinned), `.env.example`, `docs/schema.md`,
   `docs/events.md`.
2. `scripts/smoke_falkordb.py`, checking every FalkorDB feature listed in §5.
3. Start on track A: the seed generator and loader, the query catalog Q0–Q6, and `tests/test_queries.py`.

Teammates B and C start their tonight columns against the contracts. Our SDE agents can build `astro-mini` from
the spec in §3, with a human reviewing.
