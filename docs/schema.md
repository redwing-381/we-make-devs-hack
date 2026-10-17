# Graph data model (contract)

> **Contract file.** If you change it, say so in the PR description and ping the other two owners.
> Code mirrors: `whygraph/graph/ids.py` (id helpers), `whygraph/graph/schema.py` (indexes).

FalkorDB uses **one graph per tenant**:

| Graph | Purpose |
|---|---|
| `whygraph_demo` | Main demo company: the seeded history plus everything the agents learn |
| `whygraph_fresh` | Same seed, but it never learns. Used for the A/B "same code, different graph" proof |
| `whygraph_sbx_<id>` | Per-visitor sandbox, copied from a snapshot |
| `test_<random>` | Created and deleted by the test suite |

## Identity rule

Every node has a **stable string `id`** with a type prefix, and every write uses `MERGE` on `id`.
- The UI, findings and SSE events refer to nodes **only** by this `id`, never by FalkorDB's internal ids, which
  change on reload.
- A relationship is identified as `"<src id>|<TYPE>|<dst id>"`, for example `svc:checkout|CALLS|svc:payment`.

| Label | id format | Example |
|---|---|---|
| Service | `svc:<name>` | `svc:checkout` |
| Topic | `topic:<name>` | `topic:orders` |
| Team | `team:<slug>` | `team:payments` |
| Engineer | `eng:<handle>` | `eng:priya`, `eng:coder-bot` |
| PR | `pr:<number>` | `pr:12` |
| Commit | `commit:<sha7>` | `commit:9f2c1ab` |
| File | `file:<path>` | `file:config/services.yaml` |
| ConfigKey | `cfg:<service>.<key>` | `cfg:checkout.timeouts_ms.payment` |
| Deploy | `deploy:<id>` | `deploy:d-311` |
| Alert | `alert:<id>` | `alert:a-901` |
| Incident | `inc:<ID>` | `inc:INC-1031` |
| Feature | `feat:<name>` | `feat:motif:timeout_lt_callee_p99` |
| Investigation | `inv:<incident>-<n>` | `inv:INC-1031-1` |
| AgentStep | `step:<investigation>-<seq>` | `step:INC-1031-1-07` |
| Finding | `find:<investigation>-<n>` | `find:INC-1031-1-3` |
| Lesson | `lesson:<ID>` | `lesson:L-1` |
| FailurePattern | `pat:<slug>` | `pat:timeout_below_p99` |
| Detector | `det:<ID>` | `det:D-1` |
| Decision | `dec:<slug>` | `dec:checkout-payment-timeout` |
| Runbook | `rb:<slug>` | `rb:payment-latency` |
| ChatMessage | `msg:<id>` | `msg:INC-1031-1` |

All timestamps are **epoch milliseconds (int)**, because FalkorDB has no temporal arithmetic. Every node also
carries a human `name` for display, falling back to the id.

## Nodes

### Org
- **Service**
  - `name`
  - `tier: edge|core|data`
  - `lang`
- **Topic:** `name`
- **Team:** `name`
- **Engineer**
  - `handle`
  - `name`
  - `kind: human|agent`
  - `on_call: bool`

### Change
- **PR**
  - `number`
  - `title`
  - `state: open|merged|closed`
  - `url`
  - `opened_at`
  - `merged_at`
- **Commit**
  - `sha`
  - `message`
  - `ts`
- **File:** `path`
- **ConfigKey**
  - `service`
  - `key`, a dotted path in `services.yaml`, for example `timeouts_ms.payment`
  - `kind: timeout|retries|pool|flag`
  - `value`, which is always the current value
- **Deploy**
  - `ts`
  - `sha`
  - `status`

### Incident
- **Alert**
  - `ts`
  - `signal: error_rate|latency_p99|saturation|custom`
  - `value`
  - `threshold`
  - `severity`
  - `incident_id`
- **Incident**
  - `title`
  - `summary`
  - `status: open|resolved`
  - `severity: sev1|sev2|sev3`
  - `started_at`
  - `resolved_at`
  - `embedding: vecf32`
- **Feature**
  - `name`, for example `symptom:caller_5xx_callee_healthy`
  - `kind: symptom|change|motif|author|trigger|topology`

  Features are service-agnostic shape features. They are what lets an incident match a past incident on a
  *different* service.

### Episodic memory
- **Investigation**
  - `started_at`
  - `ended_at`
  - `graph_only: bool`
- **AgentStep**
  - `agent`
  - `tool`
  - `query_id`
  - `params` (JSON string)
  - `ms`
  - `summary`
  - `ts`
- **Finding**
  - `agent`
  - `claim`
  - `confidence`, computed from graph signals and never by the LLM
  - `query_id`
  - `params` (JSON string)
  - `node_ids: [str]`
  - `rel_ids: [str]`
  - `ts`

### Semantic memory
- **Lesson**
  - `text`
  - `embedding`
  - `confidence`
  - `uses`
  - `prevented`
  - `status: active|superseded`
  - `created_at`
- **FailurePattern**
  - `name`
  - `description`
- **Decision**
  - `title`
  - `text`
  - `created_at`
- **Runbook**
  - `title`
  - `text`
  - `updated_at`
  - `embedding`
- **ChatMessage**
  - `channel`
  - `text`
  - `ts`
  - `author`

### Procedural memory
- **Detector**
  - `template`
  - `cypher`
  - `params` (JSON string)
  - `backtest_hits`
  - `backtest_total`
  - `created_at`

## Relationships

```
(Service)-[:CALLS {p99_ms, error_rate, updated_at}]->(Service)        caller -> callee
(Service)-[:PUBLISHES]->(Topic)<-[:CONSUMES]-(Service)
(Team)-[:OWNS]->(Service)
(Engineer)-[:MEMBER_OF]->(Team)

(PR)-[:CONTAINS]->(Commit)-[:AUTHORED_BY]->(Engineer)
(PR)-[:OPENED_BY]->(Engineer)                written by PR Guard when it checks an open PR
(Commit)-[:TOUCHES]->(File)-[:BELONGS_TO]->(Service)
(Commit)-[:CHANGES {old, new, ts, callee_p99_at_change}]->(ConfigKey)
(ConfigKey)-[:CONFIGURES]->(Service)       the caller that reads the key
(ConfigKey)-[:TARGETS]->(Service)          the callee the key is about (timeouts, retries)
(Deploy)-[:SHIPS]->(Commit)
(Deploy)-[:OF]->(Service)

(Alert)-[:FIRED_ON]->(Service)
(Incident)-[:TRIGGERED_BY]->(Alert)
(Incident)-[:IMPACTED]->(Service)
(Incident)-[:HAS_FEATURE]->(Feature)
(Incident)-[:CAUSED_BY]->(Commit)
(Incident)-[:RESOLVED_BY]->(PR)
(Incident)-[:SIMILAR_TO {score, shared}]->(Incident)
(Engineer)-[:RESOLVED]->(Incident)

(Investigation)-[:FOR]->(Incident)
(Investigation)-[:STEP {seq}]->(AgentStep)
(Investigation)-[:HAS_FINDING]->(Finding)
(Finding)-[:EVIDENCE {order}]->(any node)
(Finding)-[:BUILDS_ON]->(Finding)          agent-to-agent handoff

(Lesson)-[:LEARNED_FROM]->(Incident)
(Lesson)-[:ABOUT]->(FailurePattern)
(Detector)-[:DETECTS]->(FailurePattern)
(Lesson)-[:SUPERSEDES]->(Lesson)
(PR)-[:WARNED_WITH|APPLIED|IGNORED]->(Lesson)
(Decision)-[:FROM]->(Lesson)
(PR)-[:IMPLEMENTS]->(Decision)
(Runbook)-[:MENTIONS]->(ConfigKey|Service)
(ChatMessage)-[:ABOUT]->(Incident)        status updates written by Comms
(ChatMessage)-[:PAGES]->(Engineer)        who Comms paged
(Runbook)-[:FOR]->(FailurePattern)
```

### Direction conventions

- **Blast radius** (who suffers): walk `CALLS` **backwards** from the failing service, `(s)<-[:CALLS*]-(caller)`.
- **Root cause** (what's under it): walk `CALLS` **forwards**, `(s)-[:CALLS*0..]->(dep)`. Changes on those
  services, and ConfigKeys that `CONFIGURE` or `TARGET` them, are the suspects.
- **Async** `PUBLISHES`/`CONSUMES` impact is reported separately as "delayed", never mixed into 5xx propagation.

## Indexes

These are created by `whygraph.graph.schema.ensure_schema()` and are idempotent:
- A range index on `id` for every label. `Service.name`, `Commit.sha`, `Deploy.ts` and `Alert.incident_id` are
  indexed too.
- Vector indexes on `Incident.embedding`, `Lesson.embedding` and `Runbook.embedding`, with `EMBED_DIM` (1024)
  dimensions and cosine similarity.
- Full-text indexes on `Runbook.text` and `ChatMessage.text`.
