# Who builds what: Solai · Shoban · Sakthi

This is the build guide for each of us. Read **§0–§3** (5 minutes), then go to your own section. The full design
is in [plan.md](plan.md), and every PR is a row in [features.md](features.md).

| | Person | GitHub | Role | Feature IDs |
|---|---|---|---|---|
| **A** | **Shoban** | @shobanravichandran | Graph & Memory: seed data, Cypher catalog, similarity, detectors, lessons | F-A1 … F-A5 |
| **B** | **Solai** | @redwing-381 | Agents & Integrations: agent runtime, the 4 agents, ingest, MCP, PR Guard, SDE agents | F-B1 … F-B7 |
| **C** | **Sakthi** | @ShakthiSundar-K | UI, the astro-mini demo app, live deploy, demo video | F-C1 … F-C6 |

**Sakthi:** accept the GitHub invite first (github.com/redwing-381/we-make-devs-hack/invitations).

---

## 0. Get started (everyone, about 15 minutes)

```bash
git clone https://github.com/redwing-381/we-make-devs-hack && cd we-make-devs-hack
cp .env.example .env          # Solai shares the keys privately; never commit .env
make install                  # uv sync + npm install
make db                       # FalkorDB on :6379, Browser on http://localhost:3000
make smoke                    # all 10 checks should PASS
make test                     # 19 passed
make api & make ui            # http://localhost:5173 replays the Act 1 fixture
```

How we work ([CONTRIBUTING.md](../CONTRIBUTING.md)):
- One branch per feature row, named like `feat/seed-data`.
- Open a PR into `main`. CI (`backend` + `ui`) must be green before merging; no approval is required.
- Squash-merge your own PR once it's green, and post the link in the chat.
- **Only touch your own files.** Contract files (`docs/schema.md`, `docs/events.md`,
  `whygraph/models/events.py`, `ui/src/types/events.ts`) need a `[contract]` tag in the PR title plus a ping to
  the others.

## 1. Timeline and checkpoints (IST)

| When | What must be true |
|---|---|
| **Sat 21:00** | **Shoban** merges the *Act 1 slice* (the minimal seed), so Solai can run agents on real data |
| **Sat 00:30**, checkpoint 1 | `python scenarios/inject.py act1` → Triage + Cause findings in the graph → the UI highlights the evidence path. astro-mini breaks for real when the timeout is 200 ms |
| Sat 00:30 → Sun 07:00 | Sleep. Post a one-line status in the chat before you sign off |
| **Sun 12:00**, GATE | **Act 1 end to end, live:** an SDE agent PR → merge → real 5xx → alert → 4 agents → Confirm → Lesson written. If this isn't working, we cut Act 3, the sandbox and Brain on the spot |
| Sun 12:00–16:30 | Restart → Act 2 (prevention via MCP) → tenant A/B → live VM → replay → polish |
| **Sun 16:30** | **Feature freeze.** Bug fixes only from here |
| Sun 16:30–20:30 | Rehearse with `reset_to.py`; record each act separately; README; blog post |
| **Sun 21:00** | **Submit** (deadline 23:59) |

## 2. Shared demo constants. Don't change these without telling everyone

Everyone's tests and the demo depend on these exact values.

**astro-mini services** (the OpenTelemetry demo core): frontend, checkout, payment, cart, currency,
product-catalog, recommendation, shipping, quote.

```
frontend       → cart, currency, checkout, shipping, product-catalog, recommendation
checkout       → cart, currency, payment, product-catalog, shipping
shipping       → quote
recommendation → product-catalog
(seed only, not in astro-mini: checkout -PUBLISHES-> topic:orders <-CONSUMES- accounting, fraud-detection)
```

**The canonical `astro-mini/config/services.yaml`.** Sakthi creates it and Why-Graph parses diffs of it.

```yaml
services:
  frontend:
    timeouts_ms: {cart: 300, currency: 300, checkout: 2500, shipping: 1500, product-catalog: 500, recommendation: 1000}
  checkout:
    timeouts_ms: {cart: 300, currency: 300, payment: 800, product-catalog: 500, shipping: 1500}
  shipping:
    timeouts_ms: {quote: 600}
  recommendation:
    timeouts_ms: {product-catalog: 400}
latency_ms:            # each service's own simulated work: [mean, sd] → p99 ≈ mean + 2.33·sd
  payment: [330, 50]           # p99 ≈ 450
  quote: [220, 35]             # p99 ≈ 300
  product-catalog: [100, 22]   # p99 ≈ 150
  cart: [15, 4]
  currency: [10, 3]
  shipping: [20, 5]
  recommendation: [30, 8]
  checkout: [10, 3]
  frontend: [5, 2]
```

- **ConfigKey mapping.** The key `services.checkout.timeouts_ms.payment` becomes the node
  `cfg:checkout.timeouts_ms.payment` with `service:'checkout'`, `key:'timeouts_ms.payment'` and
  `kind:'timeout'` (the kind comes from the `timeouts_ms` prefix). It has `-[:CONFIGURES]->(svc:checkout)` and
  `-[:TARGETS]->(svc:payment)`.

**The scenarios.**

| Act | Change | Callee p99 | Expected outcome |
|---|---|---|---|
| 1 (new) | `checkout.timeouts_ms.payment` 800 → **200** | ~450 | Real 5xx on checkout + frontend → investigation → Lesson L-1 + Detector D-1 |
| 2 (prevention) | `shipping.timeouts_ms.quote` 600 → **100** proposed | ~300 | MCP `check_change_risk` warns; `safe_min` = 450; the agent ships 450 |
| 3 (optional recall) | `recommendation.timeouts_ms.product-catalog` 400 → **80** (warning overridden) | ~150 | Incident; Memory recalls INC-1031 in about 3 s; `PR-[:IGNORED]->Lesson` |

**Thresholds**

| Setting | Value |
|---|---|
| Alert | Service 5xx rate > **10%** over **20 s**; at most 1 alert per service per 2 min |
| Alert grouping | Alerts within **2 min** join one incident |
| Suspect window | Deploys up to **30 min** before the alert |
| Detector D-1 | Fires when `new < 1.5 × callee p99`; `safe_min = ceil(1.5 × p99)` |
| Memory "strong match" | Combined score **≥ 0.5** |
| Combined score | `0.7 × feature-Jaccard + 0.3 × vector similarity` |

> FalkorDB's vector `score` is a **distance**: 0 means identical (CI smoke test). Use `similarity = 1 - score`.

**Fixture ids:**
- Incident `INC-1031`
- `pr:12`, `commit:9f2c1ab`, `deploy:d-311`
- `eng:priya`, the payments on-call engineer
- `eng:coder-bot`, our SDE agent (`kind:'agent'`). **Solai:** tell Shoban the real GitHub login of our SDE bot
  so the seed uses it.

## 3. Handoffs: who waits on whom

| Needed by | From | What | When |
|---|---|---|---|
| Solai (agents) | Shoban | Act 1 slice: `uv run python -m seed.load --minimal` | Sat 21:00 |
| Solai (agents) | Shoban | Catalog queries `root_alert`, `blast_radius`, `suspect_changes`, `config_vs_reality`, `who_knows` | Sat 23:00 |
| Solai (Memory agent) | Shoban | `similar_incidents`, `extract_features`, `check_changes`, `write_lesson` (signatures in §4) | Sun 09:30 |
| Shoban (tests) | Sakthi | The final `services.yaml` (§2), committed in astro-mini | Sat 20:30 |
| Sakthi (UI) | Solai | Live SSE at `/api/incidents/{id}/stream` in the same format as replay | Sun 09:00 (until then, use the fixture) |
| Solai (ingest) | Sakthi | The watcher + deployer posting to `/api/alerts`, `/api/deploys`, `/api/telemetry` | Sat 23:30 |
| Everyone | Solai | Keys in `.env`; `astro-mini` repo created; the SDE bot account added to it | Sat 20:00 |

Blocked? Use the fixture or a stub that returns hard-coded data in the agreed shape, and keep going. Never wait.

---

## 4. Shoban: Graph & Memory (A)

**Your mission:** the graph *is* the product. You own the data, every Cypher query, and memory (features,
similarity, detectors, lessons). If a judge asks "why does this need FalkorDB?", your queries are the answer.

**Your files:**
- `seed/`
- `whygraph/graph/queries.py`
- `whygraph/graph/features.py`
- `whygraph/memory/*`
- `scripts/reset_to.py`
- `tests/test_queries.py` and `tests/test_scenarios.py`
- `docs/queries.md`, generated with `make docs`

### F-A0: version pin (first 15 minutes, can go in the F-A1 PR)
- Run `docker run --rm falkordb/falkordb:latest redis-server --version` or check
  `docker image inspect` to see what `latest` is.
- Pin that version in `.env.example` (`FALKORDB_IMAGE=…`) and `.github/workflows/ci.yml`.

### F-A1 `feat/seed-data`: the synthetic company. **Ship the `--minimal` Act 1 slice by 21:00 first**

- **Layout:**
  - `seed/__init__.py`, `seed/generate.py` (deterministic, `random.seed(42)`) → `seed/data/*.json` →
    `seed/load.py`.
  - Add `pythonpath = ["."]` to `[tool.pytest.ini_options]` so tests can `import seed`.
- **Loader:**
  - CLI: `uv run python -m seed.load [--graph whygraph_demo] [--minimal] [--no-embed]`.
  - Function: `load(graph="whygraph_demo", *, minimal=False, embed=True)`.
  - Call `ensure_schema()` first, `MERGE` on `id` everywhere (ids per [schema.md](schema.md)), and batch with
    `UNWIND $rows AS r MERGE …`.
  - Load **both** `whygraph_demo` and `whygraph_fresh` from the same data.
- **The `--minimal` slice** has just what Act 1 needs, matching the fixture ids:
  - The 9 core services plus CALLS edges with `p99_ms` from §2 (payment 450, quote 300, product-catalog 150).
  - The `services.yaml` ConfigKeys with CONFIGURES and TARGETS edges.
  - Teams `payments` (owns payment, checkout) and `catalog`, with `eng:priya` (`on_call:true`).
  - `eng:coder-bot` (`kind:'agent'`).
  - A deploy, commit and PR for Act 1 (`deploy:d-311`, `commit:9f2c1ab`, `pr:12`) with
    `CHANGES{old:800, new:200, callee_p99_at_change:450}`.
  - Alerts `alert:a-901` (checkout) and `alert:a-902` (frontend) with `incident_id:'INC-1031'`.
- **The full seed:**
  - **Services:** about 30. Add synthetic ones such as auth, search, inventory, notifications, user-profile,
    ads, email, accounting, fraud-detection and the `orders` topic.
  - **People:** 6 teams (payments, checkout, catalog, platform, data, growth), 20 engineers and the agent
    engineers.
  - **History:** 30 days with about 300 commits and 120 deploys. Most commits touch app files; a few touch
    `services.yaml` keys.
  - **Past incidents:** 20 (`INC-1001`…`INC-1020`), spread over 6 patterns: db_pool_exhaustion, retry_storm,
    cert_expiry, bad_dependency_bump, flag_misconfig and kafka_lag. **No timeout pattern.** Each incident gets:
    - Alerts, `IMPACTED`, `CAUSED_BY`, a resolver
    - Features
    - A short template summary
    - A Lesson + FailurePattern
    - A Runbook (`MENTIONS` ConfigKeys/Services, with `updated_at`)
    - 3–5 ChatMessages
- **Text:** keep it **template-generated, not LLM-written**, and give it realistic small imperfections.
- **Embeddings:** embed `Incident.summary`, `Lesson.text` and `Runbook.text` with `whygraph.embeddings.Embedder`
  (it's cached in `seed/embeddings_cache.json`, which gets committed). Store them with `vecf32($vec)`. That's
  under 100 texts, so it's one Voyage call.

### F-A2 `feat/query-catalog`: Q0–Q6 (target: 23:00)

Register each query in `whygraph/graph/queries.py`, following the `service_neighbors` example. Each one needs a
plain-English `explain`, and you should run `make docs` afterwards. Start from the drafts in
[plan.md §5](plan.md); the query shapes were already checked against real FalkorDB in CI.

| id | code | Params | Must return |
|---|---|---|---|
| `root_alert` | Q0 | `inc` | `service` (name), `alert` (id), `path` (Alert-FIRED_ON->Service). Only the root row(s) |
| `blast_radius` | Q1 | `svc` | One row per hurt service: `service`, `tier`, `hops`, `delayed` (true for async consumers via Topic), `path` |
| `suspect_changes` | Q2 | `root, alert_ts, window_ms` | Ranked rows, best first: `sha` (as stored on Commit), `message`, `author`, `author_kind`, `service`, `hops`, `mins_before`, `score` (0–1), `path` (Service…Deploy-SHIPS->Commit-AUTHORED_BY->Engineer) |
| `config_vs_reality` | Q3 | `sha` | `caller`, `callee`, `key`, `old`, `new`, `callee_p99_at_change`, `below_p99`, `path` (Commit-CHANGES->ConfigKey-CONFIGURES->caller-CALLS->callee) |
| `similar_incidents` | Q4 | `id, q` | Feature-Jaccard rows + vector rows (merged in Python, see F-A3) |
| `who_knows` | Q5 | `svc` | Ranked engineers with team, on_call, commits and resolved counts |
| `guard_timeout_below_p99` | Q6 | `changes` | caller, callee, proposed, p99, `safe_min` |

- **Column names above are what Solai's Triage and Cause agents read** (`whygraph/agents/triage.py`,
  `cause.py`; the expected rows are mocked in `tests/act1_graph.py`). Keep them, or change both sides in one PR.
- **Return paths, not just columns.** The UI and the grounding check need node and edge ids; `client.run()`
  turns paths into a `Subgraph` automatically.
- **Tests** (`tests/test_queries.py`, `db`-marked) run on the minimal slice in a throwaway graph:
  - Q0 returns checkout.
  - Q2 ranks `commit:9f2c1ab` first.
  - Q3 gives `below_p99 = true`.
  - Q6 fires for 200 and stays silent for 800.

### F-A3 `feat/memory-core`: features, similarity, detectors, lessons (target: Sun 09:30)

These are the Python functions Solai calls. Keep these signatures:

```python
# whygraph/graph/features.py
def extract_features(incident_id: str, graph: str | None = None) -> list[str]:
    """Deterministic Cypher; MERGE (Incident)-[:HAS_FEATURE]->(Feature); returns feature names."""


# whygraph/memory/similarity.py
@dataclass
class Match:
    incident_id: str
    score: float
    jaccard: float
    vector_sim: float
    shared: list[str]
    lesson_id: str | None
    fix: str | None
    evidence: Subgraph


def similar_incidents(incident_id: str, graph: str | None = None, k: int = 5) -> list[Match]:
    """0.7*Jaccard(HAS_FEATURE) + 0.3*(1 - vector distance). Resolved incidents only."""


# whygraph/memory/detectors.py
def check_changes(changes: list[ConfigChange], graph: str | None = None) -> list[RiskWarning]:
    """Run every active Detector's stored Cypher on proposed changes (used by MCP + PR Guard)."""


# whygraph/memory/lessons.py
def write_lesson(incident_id: str, cause_finding_id: str, fix: str, graph: str | None = None) -> dict:
    """Lesson + FailurePattern + Decision + Detector (template chosen, self-validated on this incident,
    backtested over all CHANGES). Returns the `memory.lesson_written` payload (docs/events.md)."""


def record_guard_outcome(
    pr_number: int, lesson_id: str, outcome: Literal["warned", "applied", "ignored"], graph: str | None = None
) -> None:
    """PR-[:WARNED_WITH|APPLIED|IGNORED]->Lesson; applied → confidence +0.2, prevented +1."""
```

- **Feature names** (canonical; they never contain a service name):
  - `symptom:caller_5xx_callee_healthy`
  - `symptom:latency_p99`
  - `change:timeout_decrease`
  - `change:retries_increase`
  - `change:pool_decrease`
  - `change:flag_flip`
  - `change:dependency_bump`
  - `motif:timeout_lt_callee_p99`
  - `author:agent`
  - `author:human`
  - `trigger:deploy_lt_10m`
  - `topology:sync_call`
  - `topology:async_consumer`
- **Detector templates:** `timeout_below_p99` (D-1, the demo one), plus `retries_without_backoff`,
  `pool_below_concurrency` and `flag_disables_cache` (decoys used by the history). Each is stored as
  `Detector{template, cypher, params}`, and `check_changes` runs the **stored** Cypher. That stored Cypher is
  our procedural memory.
- **Backtest (Q12):** run a detector over every historical `CHANGES` edge and store `backtest_hits/total`.
  This produces the "fires on 1 of 312 past commits" line in the demo.
- **`tests/test_scenarios.py`** must show that:
  - Act 1's best match is below 0.5 (a new pattern).
  - After `write_lesson`, Act 2's change (shipping→quote 100) gets a D-1 warning with `safe_min` 450.
  - `whygraph_fresh` returns no warning.

### F-A4 `feat/snapshots`: `scripts/reset_to.py` (Sun morning)
- `reset_to.py save act1`: `GRAPH.COPY whygraph_demo → snap_act1`. This passed in CI.
- `reset_to.py act1`: delete `whygraph_demo`, then copy `snap_act1` back. We rehearse in a loop with this.

### F-A5 `feat/brain-queries`: Q7–Q10 (afternoon)
- `why_is(cfg)`: walks ConfigKey ← CHANGES ← Commit ← PR → IMPLEMENTS Decision ← FROM Lesson → LEARNED_FROM
  Incident.
- `doc_search(q, text)`: vector search plus full-text search over Runbook and ChatMessage.
- `criticality`: `algo.pageRank('Service','CALLS')`. It feeds incident severity and the PR Guard risk tier.
- `stale_runbooks`: runbooks that `MENTIONS` a ConfigKey whose latest `CHANGES.ts` is after the runbook's
  `updated_at`.

**Evening:** you own the README sections for the schema diagram (Mermaid) and the query explanations, and the
blog post (side prize).

---

## 5. Solai: Agents & Integrations (B)

**Your mission:** turn queries into agents that act, and close the loop with our SDE agent team. You also drive
the SDE agents during recording.

**Your files:**
- `whygraph/agents/*`
- `whygraph/integrations/*`
- `whygraph/api/routes/{ingest,incidents,brain}.py`
- `scenarios/inject.py`, `scenarios/act*.md`, `scenarios/sde-agent-kit.md`

### Hour 0 (before 20:00): unblock everyone
- **Keys:** Anthropic and Voyage. The Voyage key comes from MongoDB Atlas → AI Model APIs; **add a card**,
  which lifts the 3 RPM limit while the free tokens still apply. Also a GitHub fine-grained PAT. Share them
  privately.
- **Repo:** create the `redwing-381/astro-mini` repo (public). Give Sakthi and our SDE bot account write access,
  and set `GITHUB_REPO` in `.env`.
- **Bot login:** send Shoban our SDE bot's GitHub login.

### F-B1 `feat/agent-runtime` (tonight)
- **Event bus** (`whygraph/agents/events.py`): an in-process pub/sub per incident.
  - `publish(event: AgentEvent)` appends to `scenarios/recordings/live/<incident>.jsonl`, the replay format.
  - Implement `GET /api/incidents/{id}/stream` in the same SSE format as `routes/replay.py`, so the UI just
    swaps the URL.
- **Tool loop** (`agents/base.py`):
  - Uses the Anthropic SDK (`MODEL_REASONING` = `claude-sonnet-5-5`, `MODEL_FAST` = `claude-haiku-5-5`). Load
    the `claude-api` skill in Claude Code when you write it.
  - The tools are generated from the catalog (one tool per query id, with params as its input schema), plus
    `record_finding`.
  - Budget: 8 or fewer tool calls and a timeout on every call. Use prompt caching on the system prompt and the
    tools.
- **`record_finding(claim, query_id, params, node_ids, rel_ids, builds_on)`** is the grounding check:
  - Re-run the query and check that every id appears in `out.subgraph`. If not, raise `GroundingError` so the
    model retries.
  - Confidence comes from graph signals (score, hops, Jaccard, detector hit). Never ask the LLM for it.
  - Write `Finding` and `-[:EVIDENCE{order}]->` edges, and `AgentStep` for every tool call.
- **Graph-only mode:** every agent has a deterministic path, with the queries run in a fixed order and a claim
  template. Use it when `GRAPH_ONLY=true`, when the LLM fails or when it times out.
- **Orchestrator:**
  1. Create the Incident and the Investigation.
  2. Run `Triage ∥ Memory(pass 1)` with `asyncio.gather`.
  3. Run `Cause`.
  4. Run `extract_features`.
  5. Run `Memory(pass 2)`.
  6. Run `Comms`.

### F-B2 `feat/ingest` (tonight)
- **`POST /api/alerts`:**
  - MERGE the Alert; attach it to an open incident from the last 2 min or create `INC-<n>`.
  - Start the orchestrator once per incident (FastAPI `BackgroundTasks`). Return `{incident_id}`.
- **`POST /api/deploys`:** MERGE Deploy, then `-[:SHIPS]->` Commit, `-[:OF]->` Services, and the Engineer by
  author.
  - **Contract addition (do it in this PR, tagged `[contract]`):** add `config_changes: list[ConfigChange]` and
    `message: str | None` to `DeployIn`, in both mirrors.
  - Sakthi's deployer computes the `services.yaml` diff itself, so Act 1 works even before PR Guard exists.
  - Write `CHANGES{old, new, ts, callee_p99_at_change}`, reading the current `CALLS.p99_ms`.
- **`POST /api/telemetry`:** `SET` `CALLS.p99_ms`, `error_rate` and `updated_at` per edge.
- **`scenarios/inject.py act1|act2|act3`:** posts the same deploy + alert payloads with no app running. This is
  the fallback for every act.

### F-B3 `feat/agents-triage-cause` (target: 00:30 checkpoint)
- **Triage:** deterministic `root_alert` → `blast_radius` (+ `criticality` once it exists), then one Haiku line
  of summary. It writes 2 findings and hands off to Cause.
- **Cause:** the one open-ended **Sonnet loop**.
  - It reads Triage's findings from the graph and picks among `suspect_changes`, `config_vs_reality`,
    `commit_details` and `doc_search`.
  - It must end with a grounded finding for the top suspect, whose path runs alert → service → ConfigKey →
    Commit → PR → author.

### F-B4 `feat/agents-memory-comms` (Sun morning)
- **Memory:**
  - Pass 1 runs `similar_incidents` on symptoms only.
  - Pass 2 runs after Cause: `extract_features`, then `similar_incidents`, then `check_changes` on the suspect's
    changes.
  - A finding is either "Seen before: INC-x, fix…" (score ≥ 0.5) or "No strong match (best 0.31)".
- **Comms:** one Haiku call over the findings plus `who_knows`. It writes ChatMessage nodes (the status update
  and who was paged).
- **`POST /api/incidents/{id}/resolve {fix}`:** calls `write_lesson(...)`, emits `memory.lesson_written`,
  `incident.resolved`.

### F-B5 `feat/mcp` (Sun morning, needed for Act 2)
- **Server:** FastMCP 4.x in `integrations/mcp_server.py`, mounted at `/mcp` in `api/main.py` (see the comment
  there; wire up the lifespan). It requires the `WHYGRAPH_API_TOKEN` bearer token.
- **Tools:**
  - `check_change_risk(ChangeRiskRequest) → ChangeRiskResponse`: `check_changes` + `criticality` tier + a Haiku
    advice line. It also calls `record_guard_outcome(…, "warned")`.
  - `who_knows(service)`
  - `why_is(config_key)`
  - `get_service_context(service)`
- **Tenant:** an optional `graph` argument, so the same call can target `whygraph_fresh` for the A/B shot.
- **`scenarios/sde-agent-kit.md`:** the MCP URL, the token header, and the system-prompt line our SDE agents get.
  Connect our SDE agents and test with Act 2.

### F-B6 `feat/pr-guard` (Sun midday)
- `integrations/github.py` polls astro-mini PRs every 10 s with httpx and `GITHUB_TOKEN`.
- For each PR it parses the `services.yaml` diff (base vs head), MERGEs PR/Commit/CHANGES, runs
  `check_change_risk`, and posts or updates **one** PR comment: "No known risk" or the warning with the
  lesson + `safe_min`.
- On merge, if the final value respects the lesson, it calls `record_guard_outcome(…, "applied")`; otherwise
  `"ignored"`.

### F-B7 `feat/brain-agent` (afternoon, cut first)
- `POST /api/brain/ask` runs a Sonnet loop over `who_knows`, `why_is`, `doc_search` and `stale_runbooks`.
- It returns `{answer, sources: [node ids], evidence: Subgraph}`.

**Demo:** write `scenarios/act{1,2,3}.md`, the exact task prompts for our SDE agents. The prompts must *not*
mention lessons. Drive the agents during recording.

---

## 6. Sakthi: UI, astro-mini & deploy (C)

**Your mission:** make it visible. Judges remember the moment the path lights up and the moment an agent gets
warned before it ships. You also build the app that actually breaks.

**Your files:**
- `ui/src/pages/*`, `ui/src/components/*`
- the separate **astro-mini** repo
- `Caddyfile`, `deploy/`
- the video

### F-C2 `astro-mini` (separate repo `redwing-381/astro-mini`; tonight, start here)

This is small on purpose: one FastAPI app, one container. You can ask our SDE agents to build it from this
spec, but **read and test every line**.

```
astro-mini/
  app/main.py            # one router per service: /svc/<name>/...; calls others via httpx over localhost
  config/services.yaml   # EXACTLY the file in §2 — commit it first, tell Shoban
  watcher/watcher.py     # load + metrics → Why-Graph
  deployer/deployer.py   # git pull → reload → POST /api/deploys
  Dockerfile  docker-compose.yml  README.md (credit OpenTelemetry demo, Apache-2.0)
```

- **Services** (`app/main.py`):
  - Each service handler sleeps its own `latency_ms` (seeded `random.gauss`), then calls its downstreams with
    `httpx` using `timeouts_ms[<callee>]`.
  - A downstream timeout or 5xx becomes a **502**.
  - Re-read `services.yaml` when its mtime changes (hot reload with no restart).
  - Frontend entry points: `GET /svc/frontend/checkout`, `/svc/frontend/product/{id}` and
    `/svc/frontend/shipping-quote`.
- **`/metrics`** returns JSON per service: request count, 5xx count, and the **callee-side** latency p99 over
  the last 30 s.
  - Callee-side means it's measured inside the callee's own handler, so a short caller timeout doesn't clip it.
- **Watcher:**
  - Generates constant load (about 5 rps across the frontend endpoints).
  - Every 10 s it posts `/api/telemetry` (edge `caller→callee` with `p99_ms` = the callee's p99 and the error
    rate).
  - It posts `/api/alerts` when a service's 5xx rate stays above 10% for 20 s, at most once per service per
    2 min.
- **Deployer:**
  - Every 5 s it runs `git fetch`. If `origin/main` moved, it runs `git reset --hard`, computes the
    `services.yaml` diff between the old and new sha, and posts `/api/deploys`.
  - The payload carries `{sha, repo, services, ts, pr_number (parse "Merge pull request #N" or "(#N)"), author,
    message, config_changes}`.
- **Done when:** editing `checkout.timeouts_ms.payment` to 200 and pushing makes checkout + frontend return 502
  within about 20 s, an alert arrives at `/api/alerts`, and setting it back recovers.

### F-C1 `feat/ui-incident` (tonight)
- **`GraphCanvas.tsx`:** replace the placeholder with `<falkordb-canvas>` (already installed:
  `@falkordb/canvas`).
  - Feed it with `setData({nodes, links})` and `setConfig({layoutMode:'tree', onNodeClick})`.
  - Keep the props `{graph, highlight}`, so pages don't change.
  - **Highlight:** color the nodes and links of the selected finding, and dim everything else.
  - Give it 1 hour max. If it fights you, fall back to `react-force-graph-2d` or Cytoscape and move on.
- **`AgentLanes.tsx` and `FindingCard.tsx`:** animate steps as they stream in; colored agent chips; confidence
  bar; handoff arrows.
- **Incident header:** title, severity, the alerting services, and a **Confirm root cause + fix** button
  (`POST /api/incidents/{id}/resolve`, Sun).
- **Source of events:** develop against `streamUrl.replay('act1-fixture')`. When Solai's live stream lands,
  switch on `?incident=<id>`.

### F-C3 `feat/ui-cypher-drawer` (Sun morning)
- Clicking a finding opens a drawer with the claim, `query_id`, the Cypher (from `GET /api/queries`), the params
  and **Run live**.
- Run live calls `POST /api/query/run` and re-highlights the returned `subgraph`, showing `ms`.
- Add a **Graph-only mode** toggle in the top bar (Solai exposes the flag; until then it's local state).

### F-C4 `feat/ui-tabs` (Sun morning)
- **PR Guard:** PRs with their verdict (none/low/medium/high), the detector that fired, the lesson + incident
  link, and the A/B (`whygraph_demo` vs `whygraph_fresh`).
- **Memory:** lessons with confidence / uses / prevented, detectors with backtest hits, and badges labelling
  **episodic / semantic / procedural**.

### F-C5 `feat/ui-brain-replay` (afternoon)
- **Replay:** a recordings list (`GET /api/replay`), play at 1–4×, defaulting to the best recorded run.
- **Brain:** an ask box. Answers show as text plus source chips; clicking a chip highlights it in the canvas.

### F-C6 `feat/deploy` (Sun 12:00–16:00)
- **VM:** any provider, about 4 vCPU / 8 GB, running docker compose for `falkordb`, `api`, astro-mini, the
  watcher and the deployer, plus the built UI served by Caddy with HTTPS (a subdomain or `sslip.io`).
- **Public mode:** Replay is the default. Live runs and Confirm need the `WHYGRAPH_API_TOKEN`, so visitors
  can't burn our LLM budget.

**Evening:** you lead the video. Record each act separately and keep the best take, about 3 minutes total
(script in [plan.md §1](plan.md)). Solai drives the SDE agents and Shoban narrates the queries.

---

## 7. Before you merge anything

- `make lint && make test` pass locally, and CI is green.
- New Cypher lives only in the catalog, with an `explain`; `make docs` has been run.
- No secrets in the diff.
- You can explain every line to a judge. They will ask, and the rules let them reject projects that look
  entirely AI-generated.
