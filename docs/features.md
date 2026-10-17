# Feature board

Each row is **one branch and one PR**. Owners: **A** = Graph & Memory (**Shoban**), **B** = Agents &
Integrations (**Solai**), **C** = UI, demo app & deploy (**Sakthi**). Per-person build guide with specs and
signatures: [work-split.md](work-split.md). The full design is in [plan.md](plan.md).

**Rule for parallel work: only touch the files listed for your feature.**
- Shared contract files need a heads-up in the PR: `docs/schema.md`, `docs/events.md`,
  `whygraph/models/events.py`, `ui/src/types/events.ts`.
- The base already wires every router, page and package, so most PRs only add or fill in their own files.

## Tonight (target: 00:30 checkpoint, `inject.py act1` → findings → UI highlights path)

| ID | Owner | Branch | Files | Depends on | Done when |
|---|---|---|---|---|---|
| F-A1 | A | `feat/seed-data` | `seed/generate.py`, `seed/load.py`, `seed/data/*.json`, `seed/embeddings_cache.json` | base | `python seed/load.py` builds `whygraph_demo` + `whygraph_fresh`: ~30 services (OTel core 9), 6 teams, 20 engineers + agent engineers, 300 commits, 120 deploys, 20 past incidents over 6 patterns (**no** timeout pattern), runbooks, chat |
| F-A2 | A | `feat/query-catalog` | `whygraph/graph/queries.py`, `tests/test_queries.py` | F-A1 | Q0–Q6 registered with explanations; tests prove Q0 = checkout, Q2 ranks PR #12 first, Q6 fires at 200 ms and is silent at 800 ms on the Act 1 fixture |
| F-B1 | B | `feat/agent-runtime` | `whygraph/agents/base.py`, `whygraph/agents/orchestrator.py`, `whygraph/agents/events.py`, `whygraph/api/routes/incidents.py` | base | Tool loop (Claude), `record_finding` grounding check, step budget, graph-only fallback, live SSE + JSONL recording |
| F-B2 | B | `feat/ingest` | `whygraph/integrations/ingest.py`, `whygraph/api/routes/ingest.py`, `scenarios/inject.py` | F-A1 | `/alerts` (2-min grouping → Incident), `/deploys`, `/telemetry` (updates `CALLS.p99_ms`) write to the graph; `inject.py act1` replays a deploy + alerts |
| F-B3 | B | `feat/agents-triage-cause` | `whygraph/agents/triage.py`, `whygraph/agents/cause.py` | F-A2, F-B1 | Act 1 alert produces grounded Triage + Cause findings |
| F-C1 | C | `feat/ui-incident` | `ui/src/pages/Incident.tsx`, `ui/src/components/GraphCanvas.tsx`, `ui/src/components/FindingCard.tsx`, `ui/src/components/AgentLanes.tsx` | base | Replays `act1-fixture` over SSE; clicking a finding highlights its exact nodes and edges (`@falkordb/canvas` spike, fallback react-force-graph) |
| F-C2 | C | `astro-mini` repo | separate repo: `app/main.py`, `config/services.yaml`, `watcher/`, `deployer/` | events.md | A real `checkout→payment` timeout of 200 ms causes real 5xx; the watcher posts telemetry + alerts; the deployer posts deploys |

## Tomorrow morning (target: 12:00 GATE, Act 1 end-to-end with a real SDE-agent PR)

| ID | Owner | Branch | Files | Depends on | Done when |
|---|---|---|---|---|---|
| F-A3 | A | `feat/memory-core` | `whygraph/graph/features.py`, `whygraph/memory/{similarity,detectors,lessons}.py`, `tests/test_scenarios.py` | F-A2 | Features + Q4 similarity; Detector templates with self-validate + backtest (Q12); Lesson/Decision write-back; Act 1 best match < 0.5, Act 2 detector fires |
| F-A4 | A | `feat/snapshots` | `scripts/reset_to.py` | F-A1 | `reset_to.py act1` restores the graph state before Act 1 (GRAPH.COPY or reseed) |
| F-B4 | B | `feat/agents-memory-comms` | `whygraph/agents/memory.py`, `whygraph/agents/comms.py`, resolve route in `routes/incidents.py` | F-A3, F-B3 | Memory + Comms findings; "Confirm root cause" writes Lesson + Detector and emits `memory.lesson_written` |
| F-B5 | B | `feat/mcp` | `whygraph/integrations/mcp_server.py`, `scenarios/sde-agent-kit.md` | F-A3 | `/mcp` serves `check_change_risk`, `who_knows`, `why_is`, `get_service_context`; our SDE agents connect |
| F-B6 | B | `feat/pr-guard` | `whygraph/integrations/github.py` | F-B5 | Polls astro-mini PRs, parses the `services.yaml` diff into `CHANGES`, posts a PR Guard comment |
| F-C3 | C | `feat/ui-cypher-drawer` | `ui/src/components/CypherDrawer.tsx`, `ui/src/components/GraphOnlyToggle.tsx` | F-A2 | Drawer shows query + params; **Run live** calls `/api/query/run` and re-highlights the path |
| F-C4 | C | `feat/ui-tabs` | `ui/src/pages/PRGuard.tsx`, `ui/src/pages/Memory.tsx` | F-B4 | PR verdicts with lessons; lesson confidence/uses/prevented; memory type labels |

## Afternoon (12:00 to 16:30 freeze)

| ID | Owner | Branch | Files | Done when |
|---|---|---|---|---|
| F-A5 | A | `feat/brain-queries` | `whygraph/graph/queries.py` (Q7–Q10) | `why_is`, `doc_search`, `criticality` (feeds severity), `stale_runbooks` |
| F-B7 | B | `feat/brain-agent` | `whygraph/agents/brain.py`, `whygraph/api/routes/brain.py` | Answers carry source chips (node ids) |
| F-C5 | C | `feat/ui-brain-replay` | `ui/src/pages/Brain.tsx`, `ui/src/pages/Replay.tsx` | Ask box + replay picker at 1–4× speed |
| F-C6 | C | `feat/deploy` | `Caddyfile`, `deploy/` | Live VM: replay is the default; live runs are token-gated |
| F-ALL | all | `docs/readme-final` | `README.md`, `docs/queries.md` | Tracks named, schema diagram, query explanations, AI disclosure, OTel attribution |
