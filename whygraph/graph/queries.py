"""The named query catalog: the ONLY Cypher agents, MCP tools and the UI may run.

Each entry has a stable `id` (used in findings and the API), a short `code` for docs (Q0..Q12), a
plain-English explanation, and example params. `scripts/gen_query_docs.py` turns this into docs/queries.md
for the README.

Conventions every query follows:
- Incident params are the human id (`"INC-1031"`); the node id is `'inc:' + $id`.
- Commit params accept a full or short sha; the node id is `'commit:' + substring($sha, 0, 7)`.
- Queries return **paths** (or lists of paths) next to the scalar columns, so `client.run()` can build the
  `Subgraph` the UI highlights and the grounding check verifies.
- `internal=True` entries back the memory functions in whygraph/graph/features.py and whygraph/memory/*.
  They are listed here so every line of Cypher the product runs is in one reviewed place.
"""

import re
from dataclasses import dataclass, field
from typing import Any

from whygraph.memory.templates import TIMEOUT_BELOW_P99


@dataclass(frozen=True)
class CatalogQuery:
    id: str
    code: str
    title: str
    explain: str
    cypher: str
    example_params: dict[str, Any] = field(default_factory=dict)
    read_only: bool = True
    # internal = backs a Python memory function (features, similarity, detectors, lessons); agents and MCP
    # call that function instead, so tool generators should skip these.
    internal: bool = False


CATALOG: dict[str, CatalogQuery] = {}


def register(q: CatalogQuery) -> CatalogQuery:
    if q.id in CATALOG:
        raise ValueError(f"duplicate query id {q.id!r}")
    CATALOG[q.id] = q
    return q


def get(query_id: str) -> CatalogQuery:
    try:
        return CATALOG[query_id]
    except KeyError:
        raise KeyError(f"unknown query {query_id!r}; known: {sorted(CATALOG)}") from None


def required_params(q: CatalogQuery) -> set[str]:
    return set(re.findall(r"\$([A-Za-z_][A-Za-z0-9_]*)", q.cypher))


def run(query_id: str, params: dict[str, Any] | None = None, *, graph=None, timeout_ms: int | None = None):
    """Run a catalog query by id (read-only queries go through GRAPH.RO_QUERY). Returns client.QueryOutput.

    Missing parameters are rejected here, before FalkorDB sees them: v4.22.1 can segfault on its own
    missing-parameter error path (seen with the vector procedures in Q8v)."""
    from whygraph.graph import client

    q = get(query_id)
    if missing := required_params(q) - set(params or {}):
        raise ValueError(f"{query_id}: missing parameters {sorted(missing)}")
    kwargs = {"timeout_ms": timeout_ms} if timeout_ms else {}
    return client.run(q.cypher, params or {}, graph=graph, read_only=q.read_only, **kwargs)


ACT1_ALERT_TS = 1_792_297_800_000  # a-901 in the Act 1 fixture

# --- example: copy this shape ---------------------------------------------------------------

register(
    CatalogQuery(
        id="service_neighbors",
        code="QX",
        title="Service neighbours",
        explain=(
            "What a service calls directly, and who calls it directly. Returns the edges as paths so the UI "
            "can draw them and show p99 latency on each call."
        ),
        cypher="""
MATCH (s:Service {name: $svc})
OPTIONAL MATCH out = (s)-[:CALLS]->(:Service)
OPTIONAL MATCH inn = (:Service)-[:CALLS]->(s)
RETURN s, collect(DISTINCT out) AS calls, collect(DISTINCT inn) AS called_by
""".strip(),
        example_params={"svc": "checkout"},
    )
)

# --- Q0–Q6: investigation (F-A2) ------------------------------------------------------------

register(
    CatalogQuery(
        id="root_alert",
        code="Q0",
        title="Root alert",
        explain=(
            "Which alerting service is the root of an incident: the one that is alerting while nothing it "
            "calls (up to 4 hops down) is alerting too. Errors above it are just propagation. Also returns "
            "its direct callees, the ones without an alert listed as healthy, and the alerting callers above "
            "it, so the UI can show 'checkout fails, payment below it is fine, frontend above it suffers'."
        ),
        cypher="""
MATCH (a:Alert {incident_id: $inc})-[:FIRED_ON]->(s:Service)
OPTIONAL MATCH (s)-[:CALLS*1..4]->(d:Service)<-[:FIRED_ON]-(:Alert {incident_id: $inc})
WITH a, s, count(d) AS deeper
WHERE deeper = 0
MATCH path = (a)-[:FIRED_ON]->(s)
OPTIONAL MATCH down = (s)-[:CALLS]->(callee:Service)
WITH a, s, path, collect(DISTINCT down) AS callees, collect(DISTINCT callee.name) AS callee_names
OPTIONAL MATCH up = (:Alert {incident_id: $inc})-[:FIRED_ON]->(:Service)-[:CALLS*1..4]->(s)
WITH a, s, path, callees, callee_names, collect(DISTINCT up) AS upstream
OPTIONAL MATCH (:Alert {incident_id: $inc})-[:FIRED_ON]->(alerting:Service)
WITH a, s, path, callees, upstream, callee_names, collect(DISTINCT alerting.name) AS alerting
RETURN s.name AS service, a.id AS alert, a.signal AS signal, a.ts AS ts,
       [n IN callee_names WHERE NOT n IN alerting] AS healthy_callees,
       [n IN alerting WHERE n <> s.name] AS alerting_above, path, callees, upstream
ORDER BY ts
""".strip(),
        example_params={"inc": "INC-1031"},
    )
)

register(
    CatalogQuery(
        id="blast_radius",
        code="Q1",
        title="Blast radius",
        explain=(
            "Who suffers when a service fails. Walks CALLS backwards up to 5 hops: every caller that "
            "synchronously depends on it, with the shortest path and hop count. Services that consume a "
            "topic the failing service publishes are listed separately as 'delayed': their work queues up, "
            "but they don't throw 5xx."
        ),
        cypher="""
MATCH (s:Service {name: $svc})
CALL {
  WITH s
  MATCH p = (s)<-[:CALLS*1..5]-(up:Service)
  WITH up, p ORDER BY length(p)
  WITH up, collect(p)[0] AS path
  RETURN up.name AS service, up.tier AS tier, length(path) AS hops, 'sync' AS impact, path
  UNION
  WITH s
  MATCH path = (s)-[:PUBLISHES]->(:Topic)<-[:CONSUMES]-(c:Service)
  RETURN c.name AS service, c.tier AS tier, 2 AS hops, 'delayed' AS impact, path
}
RETURN service, tier, hops, impact, path
ORDER BY impact DESC, hops, service
""".strip(),
        example_params={"svc": "checkout"},
    )
)

register(
    CatalogQuery(
        id="suspect_changes",
        code="Q2",
        title="Suspect changes",
        explain=(
            "What changed right before the alert. Three kinds of suspects: deploys on the root service or "
            "anything it depends on (up to 3 CALLS hops down); deploys anywhere whose commit changed a "
            "config "
            "key that TARGETS one of those services (a caller's retries or timeout aimed at the root); and "
            "deploys on the root's direct callers (a caller can overload it). Each is "
            "scored by recency (half-life about 10 minutes), closeness to the root (hops) and how often that "
            "service broke before. Returns the commit, its author and whether the author is a human or an "
            "agent, plus the paths: root -> ... -> deploy -> commit, the author, changed config and the PR."
        ),
        cypher="""
MATCH (s:Service {name: $root})
CALL {
  WITH s
  MATCH p = (s)-[:CALLS*0..3]->(dep:Service)<-[:OF]-(d:Deploy)-[:SHIPS]->(c:Commit)
  WHERE d.ts <= $alert_ts AND d.ts >= $alert_ts - $window_ms
  OPTIONAL MATCH (dep)<-[:IMPACTED]-(past:Incident {status: 'resolved'})
  RETURN c, d, dep.name AS service, length(p) - 2 AS hops, p AS path, count(DISTINCT past) AS prior,
         'deployed' AS via
  UNION
  WITH s
  MATCH p = (s)-[:CALLS*0..3]->(dep:Service)<-[:TARGETS]-(:ConfigKey)<-[:CHANGES]-(c:Commit)
            <-[:SHIPS]-(d:Deploy)
  WHERE d.ts <= $alert_ts AND d.ts >= $alert_ts - $window_ms
  OPTIONAL MATCH (dep)<-[:IMPACTED]-(past:Incident {status: 'resolved'})
  RETURN c, d, dep.name AS service, length(p) - 3 AS hops, p AS path, count(DISTINCT past) AS prior,
         'config targets' AS via
  UNION
  WITH s
  MATCH p = (s)<-[:CALLS]-(caller:Service)<-[:OF]-(d:Deploy)-[:SHIPS]->(c:Commit)
  WHERE d.ts <= $alert_ts AND d.ts >= $alert_ts - $window_ms
  OPTIONAL MATCH (caller)<-[:IMPACTED]-(past:Incident {status: 'resolved'})
  RETURN c, d, caller.name AS service, 1 AS hops, p AS path, count(DISTINCT past) AS prior,
         'caller deployed' AS via
}
WITH c, d, service, hops, path, prior, via ORDER BY hops
WITH c, d, collect(service)[0] AS service, collect(path)[0] AS path, collect(via)[0] AS via,
     min(hops) AS hops, max(prior) AS prior
MATCH author = (c)-[:AUTHORED_BY]->(who:Engineer)
OPTIONAL MATCH config = (c)-[:CHANGES]->(:ConfigKey)-[:TARGETS|CONFIGURES]->(:Service)
OPTIONAL MATCH pr = (:PR)-[:CONTAINS]->(c)
WITH c, d, who, author, service, path, via, hops, prior, collect(DISTINCT config) AS config,
     collect(DISTINCT pr) AS pr
RETURN c.sha AS sha, c.message AS message, who.handle AS author, who.kind AS kind, service, via,
       d.id AS deploy, ($alert_ts - d.ts) / 60000 AS minutes_before, hops, prior,
       size(config) > 0 AS config_change,
       0.5 / (1 + ($alert_ts - d.ts) / 600000.0) + 0.3 / (1 + hops) + 0.2 * prior / (prior + 1.0) AS score,
       path, author AS author_path, config, pr
ORDER BY score DESC
LIMIT 5
""".strip(),
        example_params={"root": "checkout", "alert_ts": ACT1_ALERT_TS, "window_ms": 1_800_000},
    )
)

register(
    CatalogQuery(
        id="config_vs_reality",
        code="Q3",
        title="Config vs reality",
        explain=(
            "Did this commit set a config value the running system can't live with? For every key the commit "
            "changed, follows the key to the caller it configures and the callee it targets, and compares "
            "the new timeout with the callee's p99 latency at the time of the change. below_p99 = true means "
            "the caller now gives up before a normal slow request finishes. The path is the full evidence "
            "chain: commit -> key -> caller -> callee, plus the PR, author, deploy and the alerts that "
            "followed on the caller."
        ),
        cypher="""
MATCH (c:Commit {id: 'commit:' + substring($sha, 0, 7)})
MATCH path = (c)-[ch:CHANGES]->(k:ConfigKey)-[:CONFIGURES]->(a:Service)-[e:CALLS]->(b:Service)
MATCH target = (k)-[:TARGETS]->(b)
OPTIONAL MATCH pr = (:PR)-[:CONTAINS]->(c)
OPTIONAL MATCH author = (c)-[:AUTHORED_BY]->(:Engineer)
OPTIONAL MATCH deploy = (a)<-[:OF]-(:Deploy)-[:SHIPS]->(c)
OPTIONAL MATCH alert = (al:Alert)-[:FIRED_ON]->(a)
WHERE al.ts >= c.ts AND al.ts <= c.ts + 7200000
WITH c, ch, k, a, e, b, path, target, coalesce(ch.callee_p99_at_change, e.p99_ms) AS p99,
     collect(DISTINCT pr) AS pr, collect(DISTINCT author) AS author, collect(DISTINCT deploy) AS deploy,
     collect(DISTINCT alert) AS alerts
RETURN a.name AS caller, b.name AS callee, k.key AS key, k.kind AS kind, ch.old AS old, ch.new AS new,
       p99 AS callee_p99_at_change, e.p99_ms AS callee_p99_now,
       CASE WHEN k.kind = 'timeout' THEN ch.new < p99 ELSE null END AS below_p99,
       path, target, pr, author, deploy, alerts
""".strip(),
        example_params={"sha": "9f2c1ab"},
    )
)

register(
    CatalogQuery(
        id="commit_details",
        code="Q3b",
        title="Commit details",
        explain=(
            "Everything the graph knows about one commit: author, PR, files touched, config keys changed "
            "(with old and new values on the CHANGES edge) and the deploys that shipped it to which services."
        ),
        cypher="""
MATCH (c:Commit {id: 'commit:' + substring($sha, 0, 7)})
OPTIONAL MATCH author = (c)-[:AUTHORED_BY]->(:Engineer)
OPTIONAL MATCH pr = (:PR)-[:CONTAINS]->(c)
OPTIONAL MATCH files = (c)-[:TOUCHES]->(:File)
OPTIONAL MATCH config = (c)-[:CHANGES]->(:ConfigKey)
OPTIONAL MATCH deploy = (:Service)<-[:OF]-(:Deploy)-[:SHIPS]->(c)
RETURN c.sha AS sha, c.message AS message, c.ts AS ts, collect(DISTINCT author) AS author,
       collect(DISTINCT pr) AS pr, collect(DISTINCT files) AS files, collect(DISTINCT config) AS config,
       collect(DISTINCT deploy) AS deploys
""".strip(),
        example_params={"sha": "9f2c1ab"},
    )
)

register(
    CatalogQuery(
        id="similar_incidents",
        code="Q4",
        title="Similar incidents (shape)",
        explain=(
            "Past resolved incidents with the same shape. Features are service-agnostic facts such as "
            "'a timeout was lowered below the callee p99' or 'the author was an agent', so checkout->payment "
            "can match shipping->quote. Score = Jaccard of the two feature sets (shared / union). Returns "
            "the "
            "shared features as paths current -> feature <- past, the past fix, and the active lesson "
            "learned "
            "from it (following SUPERSEDES to the newest version). Python adds 0.3 x vector similarity."
        ),
        cypher="""
MATCH (cur:Incident {id: 'inc:' + $id})-[:HAS_FEATURE]->(f:Feature)<-[:HAS_FEATURE]-(past:Incident)
WHERE past.status = 'resolved' AND past <> cur
WITH cur, past, collect(DISTINCT f.name) AS shared
MATCH (cur)-[:HAS_FEATURE]->(cf:Feature)
WITH cur, past, shared, count(DISTINCT cf) AS cn
MATCH (past)-[:HAS_FEATURE]->(pf:Feature)
WITH cur, past, shared, cn, count(DISTINCT pf) AS pn
WITH cur, past, shared, toFloat(size(shared)) / (cn + pn - size(shared)) AS jaccard
ORDER BY jaccard DESC, past.id
LIMIT 10
MATCH evidence = (cur)-[:HAS_FEATURE]->(sf:Feature)<-[:HAS_FEATURE]-(past)
WITH past, shared, jaccard, collect(evidence) AS evidence
OPTIONAL MATCH (l:Lesson)-[:LEARNED_FROM]->(past)
OPTIONAL MATCH lesson = (active:Lesson {status: 'active'})-[:SUPERSEDES*0..10]->(l)
WITH past, shared, jaccard, evidence, collect(DISTINCT lesson) AS lesson, collect(DISTINCT active.id) AS ids
RETURN past.id AS incident, past.title AS title, shared, jaccard, past.fix AS fix, ids[0] AS lesson_id,
       evidence, lesson
ORDER BY jaccard DESC, incident
""".strip(),
        example_params={"id": "INC-1031"},
    )
)

register(
    CatalogQuery(
        id="similar_incidents_vec",
        code="Q4v",
        title="Similar incidents (text)",
        explain=(
            "Past resolved incidents whose summary reads like this one, by Voyage embedding. FalkorDB's "
            "vector score is a cosine distance (0 = identical), so similarity = 1 - score. Uses the "
            "incident's own stored embedding, so no vector has to be passed in. It is the 0.3 tie-breaker "
            "next to the feature Jaccard (Q4)."
        ),
        cypher="""
MATCH (cur:Incident {id: 'inc:' + $id})
WHERE cur.embedding IS NOT NULL
CALL db.idx.vector.queryNodes('Incident', 'embedding', 12, cur.embedding) YIELD node, score
WITH cur, node, score
WHERE node <> cur AND node.status = 'resolved'
RETURN node.id AS incident, node.title AS title, 1 - score AS vector_sim, node
ORDER BY vector_sim DESC
""".strip(),
        example_params={"id": "INC-1031"},
    )
)

register(
    CatalogQuery(
        id="who_knows",
        code="Q5",
        title="Who knows this service",
        explain=(
            "Who to page or ask about a service. Candidates are the owning team's members, anyone who "
            "committed to its files or changed config that configures or targets it (agents included), and "
            "anyone who resolved an incident on it. Ranked owners first, then on-call, then incidents "
            "resolved, then hands-on changes. Paths show the ownership chain and the config changes."
        ),
        cypher="""
MATCH (s:Service {name: $svc})
OPTIONAL MATCH (s)<-[:OWNS]-(:Team)<-[:MEMBER_OF]-(m:Engineer)
OPTIONAL MATCH (s)<-[:BELONGS_TO]-(:File)<-[:TOUCHES]-(:Commit)-[:AUTHORED_BY]->(w:Engineer)
OPTIONAL MATCH (s)<-[:CONFIGURES|TARGETS]-(:ConfigKey)<-[:CHANGES]-(:Commit)-[:AUTHORED_BY]->(x:Engineer)
OPTIONAL MATCH (s)<-[:IMPACTED]-(:Incident)<-[:RESOLVED]-(r:Engineer)
WITH s, collect(DISTINCT m) + collect(DISTINCT w) + collect(DISTINCT x) + collect(DISTINCT r) AS people
UNWIND people AS e
WITH DISTINCT s, e
OPTIONAL MATCH (e)-[:MEMBER_OF]->(t:Team)
OPTIONAL MATCH owns = (s)<-[:OWNS]-(:Team)<-[:MEMBER_OF]-(e)
WITH s, e, t, collect(owns) AS owns
OPTIONAL MATCH (e)<-[:AUTHORED_BY]-(c:Commit)-[:TOUCHES]->(:File)-[:BELONGS_TO]->(s)
WITH s, e, t, owns, count(DISTINCT c) AS commits
OPTIONAL MATCH changed = (:PR)-[:CONTAINS]->(cc:Commit)-[:AUTHORED_BY]->(e)
WHERE (cc)-[:CHANGES]->(:ConfigKey)-[:CONFIGURES|TARGETS]->(s)
WITH s, e, t, owns, commits, collect(DISTINCT changed) AS changed, count(DISTINCT cc) AS config_changes
OPTIONAL MATCH (e)-[:RESOLVED]->(i:Incident)-[:IMPACTED]->(s)
WITH s, e, t, owns, commits, changed, config_changes, count(DISTINCT i) AS resolved
RETURN e.handle AS handle, e.name AS name, e.kind AS kind, e.on_call AS on_call, t.name AS team,
       size(owns) > 0 AS owner, commits, config_changes, resolved, owns AS path, changed
ORDER BY owner DESC, on_call DESC, resolved DESC, commits + config_changes DESC, handle
LIMIT 8
""".strip(),
        example_params={"svc": "payment"},
    )
)

register(
    CatalogQuery(
        id="guard_timeout_below_p99",
        code="Q6",
        title="Guard: timeout below callee p99",
        explain=(
            "Detector D-1 as a plain query: for proposed config changes (before merge), flags any timeout "
            "set "
            "below 1.5 x the callee's current p99, and returns safe_min = ceil(1.5 x p99). It never names a "
            "service, so the rule learned on checkout->payment also catches shipping->quote. The Detector "
            "node stores this same Cypher with factor as a parameter."
        ),
        cypher=TIMEOUT_BELOW_P99.cypher.replace("$factor", "1.5"),
        example_params={
            "changes": [{"service": "shipping", "key": "timeouts_ms.quote", "old": 600, "new": 100}]
        },
    )
)

# --- Q7–Q10: company brain (F-A5) -----------------------------------------------------------

register(
    CatalogQuery(
        id="why_is",
        code="Q7",
        title="Why is this config value what it is",
        explain=(
            "The history behind a config key, newest change first: which commit and PR set each value and "
            "who "
            "wrote it, and, when the PR followed a lesson, the chain PR -> IMPLEMENTS Decision <- FROM "
            "Lesson "
            "-> LEARNED_FROM Incident -> CAUSED_BY the commit and PR that broke things originally. Answers "
            "'why is shipping->quote 450 ms?' with a path, not a guess. Accepts 'shipping.timeouts_ms.quote' "
            "or the node id."
        ),
        cypher="""
MATCH (k:ConfigKey)
WHERE k.id IN [$key, 'cfg:' + $key]
OPTIONAL MATCH changed = (k)<-[ch:CHANGES]-(c:Commit)<-[:CONTAINS]-(pr:PR)
OPTIONAL MATCH author = (c)-[:AUTHORED_BY]->(who:Engineer)
OPTIONAL MATCH why = (pr)-[:IMPLEMENTS]->(:Decision)-[:FROM]->(l:Lesson)-[:LEARNED_FROM]->(i:Incident)
OPTIONAL MATCH origin = (i)-[:CAUSED_BY]->(:Commit)<-[:CONTAINS]-(:PR)
OPTIONAL MATCH applied = (pr)-[:APPLIED]->(:Lesson)
OPTIONAL MATCH broke = (:Incident)-[:CAUSED_BY]->(c)
RETURN k.id AS key, k.value AS value, c.sha AS sha, pr.number AS pr, who.handle AS author, ch.old AS old,
       ch.new AS new, ch.ts AS ts, collect(DISTINCT l.id) AS lessons, collect(DISTINCT i.id) AS incidents,
       changed, author AS author_path, collect(DISTINCT why) AS why, collect(DISTINCT origin) AS origin,
       collect(DISTINCT applied) AS applied, collect(DISTINCT broke) AS caused_incident
ORDER BY ts DESC
""".strip(),
        example_params={"key": "checkout.timeouts_ms.payment"},
    )
)

register(
    CatalogQuery(
        id="doc_search",
        code="Q8",
        title="Search runbooks and chat",
        explain=(
            "Full-text search over runbooks and incident chat: the best 5 runbooks first, then the best 5 "
            "chat lines (short chat lines would otherwise out-score the runbook that answers the question). "
            "`terms` uses FalkorDB full-text syntax: words "
            "separated by | match any of them. Runbooks come back with what they MENTION (config keys, "
            "services), so an answer can point at the graph, not just at text. whygraph.memory.search."
            "doc_search adds the vector half (Q8v) and builds the terms from a plain question."
        ),
        cypher="""
CALL {
  CALL db.idx.fulltext.queryNodes('Runbook', $terms) YIELD node, score
  RETURN node, score, 'runbook' AS kind
  ORDER BY score DESC
  LIMIT 5
  UNION
  CALL db.idx.fulltext.queryNodes('ChatMessage', $terms) YIELD node, score
  RETURN node, score, 'chat' AS kind
  ORDER BY score DESC
  LIMIT 5
}
OPTIONAL MATCH mentions = (node)-[:MENTIONS]->()
RETURN node.id AS id, kind, coalesce(node.title, node.channel) AS title, node.text AS text, score, node,
       collect(mentions) AS mentions
ORDER BY kind DESC, score DESC
""".strip(),
        example_params={"terms": "timeout|payment"},
    )
)

register(
    CatalogQuery(
        id="doc_search_vec",
        code="Q8v",
        title="Search runbooks and lessons by meaning",
        explain=(
            "Vector half of doc_search: runbooks and lessons whose Voyage embedding is closest to the "
            "question "
            "(similarity = 1 - cosine distance). Needs the question's embedding as $q, which "
            "whygraph.memory.search.doc_search computes."
        ),
        cypher="""
CALL {
  CALL db.idx.vector.queryNodes('Runbook', 'embedding', 5, vecf32($q)) YIELD node, score
  RETURN node, 1 - score AS score, 'runbook' AS kind
  UNION
  CALL db.idx.vector.queryNodes('Lesson', 'embedding', 5, vecf32($q)) YIELD node, score
  RETURN node, 1 - score AS score, 'lesson' AS kind
}
WITH node, score, kind
OPTIONAL MATCH mentions = (node)-[:MENTIONS|LEARNED_FROM]->()
RETURN node.id AS id, kind, coalesce(node.title, node.name) AS title, node.text AS text, score, node,
       collect(mentions) AS mentions
ORDER BY score DESC
""".strip(),
        internal=True,
    )
)

register(
    CatalogQuery(
        id="criticality",
        code="Q9",
        title="Service criticality (PageRank)",
        explain=(
            "How much of the system depends on each service: PageRank over CALLS, run inside FalkorDB "
            "(algo.pageRank). Services many others call, directly or transitively, rank high. The top fifth "
            "is 'high', the next 30% 'medium', the rest 'low'; it feeds incident severity and the PR Guard "
            "risk tier."
        ),
        cypher="""
CALL algo.pageRank('Service', 'CALLS') YIELD node, score
WITH node, score
ORDER BY score DESC, node.name
WITH collect({name: node.name, tier: node.tier, score: score}) AS ranked
UNWIND range(0, size(ranked) - 1) AS i
WITH ranked[i] AS s, i, size(ranked) AS n
RETURN s.name AS service, s.tier AS tier, s.score AS score, i + 1 AS rank,
       CASE WHEN i < n * 0.2 THEN 'high' WHEN i < n * 0.5 THEN 'medium' ELSE 'low' END AS criticality
ORDER BY rank
""".strip(),
    )
)

register(
    CatalogQuery(
        id="stale_runbooks",
        code="Q10",
        title="Stale runbooks",
        explain=(
            "Runbooks that are out of date: they MENTION a config key that has been changed since the "
            "runbook "
            "was last updated, so the value they tell on-call to expect is probably wrong. Returns the "
            "newest "
            "such change per key as a path runbook -> key <- commit."
        ),
        cypher="""
MATCH p = (r:Runbook)-[:MENTIONS]->(k:ConfigKey)<-[ch:CHANGES]-(c:Commit)
WHERE ch.ts > r.updated_at
WITH r, k, p, ch
ORDER BY ch.ts DESC
WITH r, k, collect(p)[0] AS path, collect(ch.new)[0] AS changed_to, max(ch.ts) AS changed_at,
     count(ch) AS changes_since
RETURN r.id AS runbook, r.title AS title, r.updated_at AS updated_at, k.id AS key, k.value AS value,
       changed_to, changed_at, changes_since, path
ORDER BY changed_at DESC
""".strip(),
    )
)

# --- memory (F-A3): features, detectors, lessons. Internal: called through Python functions ---

register(
    CatalogQuery(
        id="incident_symptoms",
        code="M1",
        title="Incident symptoms",
        explain=(
            "Facts for the symptom and topology features of an incident: its root alerting service(s) (as in "
            "Q0), the signals that fired on the root, how many of the root's callees are NOT alerting "
            "(healthy), whether the root consumes a topic, all signals in the incident and when it started."
        ),
        cypher="""
MATCH (:Alert {incident_id: $id})-[:FIRED_ON]->(s:Service)
WITH collect(DISTINCT s.name) AS alerting
MATCH (a:Alert {incident_id: $id})-[:FIRED_ON]->(r:Service)
OPTIONAL MATCH (r)-[:CALLS*1..4]->(d:Service)
WHERE d.name IN alerting
WITH alerting, r, collect(DISTINCT a.signal) AS root_signals, count(d) AS deeper
WHERE deeper = 0
OPTIONAL MATCH (r)-[:CALLS]->(callee:Service)
WHERE NOT callee.name IN alerting
OPTIONAL MATCH (r)-[:CONSUMES]->(t:Topic)
WITH alerting, r, root_signals, count(DISTINCT callee) AS healthy_callees, count(DISTINCT t) > 0 AS consumes
MATCH (x:Alert {incident_id: $id})
RETURN r.name AS root, root_signals, healthy_callees, consumes, alerting,
       collect(DISTINCT x.signal) AS signals, min(x.ts) AS started
""".strip(),
        example_params={"id": "INC-1031"},
        internal=True,
    )
)

register(
    CatalogQuery(
        id="change_facts",
        code="M2",
        title="Change facts for a commit",
        explain=(
            "Facts for the change, author and trigger features, and the detector input for one commit: every "
            "config key it changed (kind, old, new, the callee p99 at the time, whether the key sits on a "
            "sync "
            "CALLS edge), the files it touched, the author's kind (human or agent), its PR and when it was "
            "deployed."
        ),
        cypher="""
MATCH (c:Commit {id: 'commit:' + substring($sha, 0, 7)})
OPTIONAL MATCH (c)-[:AUTHORED_BY]->(who:Engineer)
OPTIONAL MATCH (c)-[ch:CHANGES]->(k:ConfigKey)
OPTIONAL MATCH (k)-[:CONFIGURES]->(:Service)-[e:CALLS]->(callee:Service)<-[:TARGETS]-(k)
WITH c, who, collect(DISTINCT {service: k.service, key: k.key, kind: k.kind, old: ch.old, new: ch.new,
     p99_at_change: coalesce(ch.callee_p99_at_change, e.p99_ms), sha: c.sha,
     sync: callee IS NOT NULL}) AS changes
OPTIONAL MATCH (c)-[:TOUCHES]->(f:File)
OPTIONAL MATCH (d:Deploy)-[:SHIPS]->(c)
OPTIONAL MATCH (pr:PR)-[:CONTAINS]->(c)
RETURN c.sha AS sha, c.id AS commit_id, who.handle AS author, who.kind AS author_kind,
       [x IN changes WHERE x.service IS NOT NULL] AS changes, collect(DISTINCT f.path) AS files,
       collect(DISTINCT d.ts) AS deploy_ts, collect(DISTINCT pr.number) AS prs
""".strip(),
        example_params={"sha": "9f2c1ab"},
        internal=True,
    )
)

register(
    CatalogQuery(
        id="incident_cause",
        code="M3",
        title="Known cause of an incident",
        explain=(
            "The commit an incident is pinned on, if anyone has said so yet: a confirmed CAUSED_BY edge "
            "first, "
            "otherwise the commit in the evidence of the Cause agent's best finding."
        ),
        cypher="""
MATCH (i:Incident {id: 'inc:' + $id})
CALL {
  WITH i
  MATCH (i)-[:CAUSED_BY]->(c:Commit)
  RETURN c.sha AS sha, 0 AS rank, 1.0 AS confidence
  UNION
  WITH i
  MATCH (i)<-[:FOR]-(:Investigation)-[:HAS_FINDING]->(f:Finding {agent: 'cause'})-[:EVIDENCE]->(c:Commit)
  RETURN c.sha AS sha, 1 AS rank, f.confidence AS confidence
}
RETURN sha, rank, confidence
ORDER BY rank, confidence DESC
LIMIT 1
""".strip(),
        example_params={"id": "INC-1004"},
        internal=True,
    )
)

register(
    CatalogQuery(
        id="finding_commit",
        code="M4",
        title="Commit cited by a finding",
        explain=(
            "Which commit a finding points at: a Commit in its EVIDENCE edges, else a commit id in its "
            "node_ids, else the sha in its params. Used when a human confirms the root cause."
        ),
        cypher="""
MATCH (f:Finding {id: $finding_id})
OPTIONAL MATCH (f)-[:EVIDENCE]->(c:Commit)
OPTIONAL MATCH (n:Commit)
WHERE n.id IN coalesce(f.node_ids, [])
RETURN f.id AS finding, f.params AS params, collect(DISTINCT c.sha) AS evidence,
       collect(DISTINCT n.sha) AS cited
""".strip(),
        example_params={"finding_id": "find:INC-1031-1-4"},
        internal=True,
    )
)

register(
    CatalogQuery(
        id="write_features",
        code="M5",
        title="Write incident features",
        explain=(
            "Replace an incident's HAS_FEATURE edges with the freshly extracted set. Features are shared "
            "nodes (feat:<name>), so two incidents with the same shape point at the same Feature node."
        ),
        cypher="""
MATCH (i:Incident {id: 'inc:' + $id})
OPTIONAL MATCH (i)-[old:HAS_FEATURE]->(:Feature)
DELETE old
WITH DISTINCT i
UNWIND $features AS x
MERGE (f:Feature {id: 'feat:' + x.name})
ON CREATE SET f.name = x.name, f.kind = x.kind
MERGE (i)-[:HAS_FEATURE]->(f)
RETURN count(f) AS features
""".strip(),
        example_params={"id": "INC-1031", "features": [{"name": "author:agent", "kind": "author"}]},
        read_only=False,
        internal=True,
    )
)

register(
    CatalogQuery(
        id="detector_backtest",
        code="Q12",
        title="Detector backtest input",
        explain=(
            "Every historical config change (each CHANGES edge) in the detector input shape, with the callee "
            "p99 at the time of the change. A detector's stored Cypher is run over this list to count how "
            "many past changes it would have fired on: 'fires on 1 of 40 past config changes'."
        ),
        cypher="""
MATCH (c:Commit)-[ch:CHANGES]->(k:ConfigKey)
RETURN collect({service: k.service, key: k.key, old: ch.old, new: ch.new,
                p99_at_change: ch.callee_p99_at_change, sha: c.sha}) AS changes,
       count(ch) AS total
""".strip(),
        internal=True,
    )
)

register(
    CatalogQuery(
        id="active_detectors",
        code="M6",
        title="Active detectors",
        explain=(
            "Procedural memory: every active Detector with its stored Cypher and params, the FailurePattern "
            "it detects, and the active Lesson about that pattern with the incident it was learned from and "
            "that incident's cause (commit and PR). check_changes runs each stored Cypher on proposed "
            "changes."
        ),
        cypher="""
MATCH detects = (d:Detector {status: 'active'})-[:DETECTS]->(p:FailurePattern)
OPTIONAL MATCH lesson = (p)<-[:ABOUT]-(l:Lesson {status: 'active'})-[:LEARNED_FROM]->(i:Incident)
OPTIONAL MATCH cause = (i)-[:CAUSED_BY]->(:Commit)<-[:CONTAINS]-(:PR)
RETURN d.id AS detector_id, d.template AS template, d.cypher AS cypher, d.params AS params,
       p.name AS pattern, l.id AS lesson_id, l.text AS lesson_text, l.confidence AS confidence,
       i.id AS incident_id, i.started_at AS learned_at, detects, lesson, cause
ORDER BY detector_id, learned_at
""".strip(),
        internal=True,
    )
)

register(
    CatalogQuery(
        id="set_backtest",
        code="M7",
        title="Store a detector's backtest",
        explain="Store how many past config changes a detector fires on (backtest_hits / backtest_total).",
        cypher="""
MATCH (d:Detector {id: $detector_id})
SET d.backtest_hits = $hits, d.backtest_total = $total
RETURN d.id AS detector_id
""".strip(),
        example_params={"detector_id": "det:D-1", "hits": 1, "total": 40},
        read_only=False,
        internal=True,
    )
)

register(
    CatalogQuery(
        id="memory_ids",
        code="M8",
        title="Lesson and detector ids in use",
        explain=(
            "All Lesson and Detector ids, so a new lesson gets the next free number (L-1, D-1 in the demo), "
            "plus any live lesson already learned from this incident (confirming twice must not duplicate)."
        ),
        cypher="""
OPTIONAL MATCH (l:Lesson)
WITH collect(l.id) AS lessons
OPTIONAL MATCH (d:Detector)
WITH lessons, collect(d.id) AS detectors
OPTIONAL MATCH (mine:Lesson)-[:LEARNED_FROM]->(:Incident {id: 'inc:' + $id})
RETURN lessons, detectors, collect(mine.id) AS learned_from_incident
""".strip(),
        example_params={"id": "INC-1031"},
        internal=True,
    )
)

register(
    CatalogQuery(
        id="pattern_memory",
        code="M9",
        title="Memory for a failure pattern",
        explain=(
            "The active lesson and active detector we already have for a failure pattern. If both exist, a "
            "new incident of that pattern reinforces them instead of minting new ones."
        ),
        cypher="""
OPTIONAL MATCH (p:FailurePattern {id: $pattern_id})
OPTIONAL MATCH (l:Lesson {status: 'active'})-[:ABOUT]->(p)
OPTIONAL MATCH (d:Detector {status: 'active'})-[:DETECTS]->(p)
RETURN collect(DISTINCT l.id) AS lessons, collect(DISTINCT d.id) AS detectors
""".strip(),
        example_params={"pattern_id": "pat:timeout_below_p99"},
        internal=True,
    )
)

register(
    CatalogQuery(
        id="write_lesson",
        code="M10",
        title="Write a lesson",
        explain=(
            "Semantic memory write-back when a human confirms the root cause: the incident becomes resolved "
            "and CAUSED_BY the commit; a Lesson (LEARNED_FROM the incident, ABOUT its FailurePattern) and a "
            "Decision (FROM the lesson) are merged. An existing lesson is reinforced instead: one more "
            "LEARNED_FROM edge, uses + 1 and confidence + 0.1 (max 0.95)."
        ),
        cypher="""
MATCH (i:Incident {id: 'inc:' + $id})
MATCH (c:Commit {id: $commit_id})
SET i.status = 'resolved', i.resolved_at = coalesce(i.resolved_at, $now), i.fix = $fix
MERGE (i)-[:CAUSED_BY]->(c)
MERGE (p:FailurePattern {id: $pattern_id})
ON CREATE SET p.name = $pattern, p.description = $pattern_description
MERGE (l:Lesson {id: $lesson_id})
ON CREATE SET l.name = $lesson_name, l.text = $text, l.status = 'active', l.source = 'live',
              l.created_at = $now, l.confidence = 0.6, l.uses = 0, l.prevented = 0
ON MATCH SET l.uses = l.uses + $reinforce,
             l.confidence = toFloat(round(CASE WHEN l.confidence + 0.1 * $reinforce > 0.95 THEN 0.95
                                               ELSE l.confidence + 0.1 * $reinforce END * 100)) / 100
MERGE (l)-[:LEARNED_FROM]->(i)
MERGE (l)-[:ABOUT]->(p)
MERGE (dec:Decision {id: $decision_id})
ON CREATE SET dec.name = $decision_title, dec.title = $decision_title, dec.text = $decision_text,
              dec.created_at = $now
MERGE (dec)-[:FROM]->(l)
RETURN l.id AS lesson_id, l.text AS text, l.confidence AS confidence, l.uses AS uses
""".strip(),
        example_params={
            "id": "INC-1031",
            "commit_id": "commit:9f2c1ab",
            "fix": "revert PR #12",
            "now": ACT1_ALERT_TS + 900_000,
            "pattern_id": "pat:timeout_below_p99",
            "pattern": "timeout_below_p99",
            "pattern_description": "...",
            "lesson_id": "lesson:L-1",
            "lesson_name": "L-1",
            "text": "...",
            "reinforce": 0,
            "decision_id": "dec:timeouts-at-least-1-5x-callee-p99",
            "decision_title": "...",
            "decision_text": "...",
        },
        read_only=False,
        internal=True,
    )
)

register(
    CatalogQuery(
        id="write_detector",
        code="M11",
        title="Write a detector",
        explain=(
            "Procedural memory write-back: store the chosen detector template's Cypher and params on a "
            "Detector node that DETECTS the failure pattern, with its backtest result. From now on "
            "check_changes runs this stored Cypher on every proposed change."
        ),
        cypher="""
MATCH (p:FailurePattern {id: $pattern_id})
MERGE (d:Detector {id: $detector_id})
ON CREATE SET d.created_at = $now, d.source = 'live', d.learned_from = $id
SET d.name = $name, d.template = $template, d.cypher = $cypher, d.params = $params, d.status = 'active',
    d.backtest_hits = $hits, d.backtest_total = $total
MERGE (d)-[:DETECTS]->(p)
RETURN d.id AS detector_id
""".strip(),
        example_params={
            "id": "INC-1031",
            "pattern_id": "pat:timeout_below_p99",
            "detector_id": "det:D-1",
            "name": "D-1 timeout_below_p99",
            "template": "timeout_below_p99",
            "cypher": "...",
            "params": '{"factor": 1.5}',
            "hits": 1,
            "total": 40,
            "now": ACT1_ALERT_TS + 900_000,
        },
        read_only=False,
        internal=True,
    )
)

register(
    CatalogQuery(
        id="lesson_evidence",
        code="M12",
        title="Lesson evidence",
        explain=(
            "Why a lesson exists, as a subgraph: lesson -> incident -> cause commit -> changed config key, "
            "the "
            "PR and author of that commit, the pattern and the detector that guards it, and the decision "
            "taken from the lesson."
        ),
        cypher="""
MATCH (l:Lesson {id: $lesson_id})
OPTIONAL MATCH learned = (l)-[:LEARNED_FROM]->(i:Incident)-[:CAUSED_BY]->(c:Commit)-[:CHANGES]->(:ConfigKey)
OPTIONAL MATCH authored = (:PR)-[:CONTAINS]->(c)-[:AUTHORED_BY]->(:Engineer)
OPTIONAL MATCH guarded = (l)-[:ABOUT]->(:FailurePattern)<-[:DETECTS]-(:Detector)
OPTIONAL MATCH decided = (:Decision)-[:FROM]->(l)
RETURN l.id AS lesson_id, l.text AS text, l.confidence AS confidence, collect(DISTINCT learned) AS learned,
       collect(DISTINCT authored) AS authored, collect(DISTINCT guarded) AS guarded,
       collect(DISTINCT decided) AS decided
""".strip(),
        example_params={"lesson_id": "lesson:L-1017"},
        internal=True,
    )
)

register(
    CatalogQuery(
        id="guard_outcome",
        code="M13",
        title="Record a PR Guard outcome",
        explain=(
            "Close the loop with our SDE agents: PR -[:WARNED_WITH|APPLIED|IGNORED]-> Lesson. 'warned' "
            "counts "
            "a use; 'applied' (the PR followed the lesson) adds 0.2 confidence, prevented + 1, and the PR "
            "IMPLEMENTS the lesson's decision; 'ignored' just records the override. Each edge is written "
            "once "
            "per PR and lesson, so retries don't double count."
        ),
        cypher="""
MERGE (pr:PR {id: $pr_id})
ON CREATE SET pr.number = $number, pr.name = '#' + toString($number)
WITH pr
MATCH (l:Lesson {id: $lesson_id})
OPTIONAL MATCH (pr)-[seen]->(l)
WHERE type(seen) = $rel
WITH pr, l, count(seen) = 0 AS first
FOREACH (_ IN CASE WHEN first AND $rel = 'WARNED_WITH' THEN [1] ELSE [] END |
  MERGE (pr)-[:WARNED_WITH]->(l)
  SET l.uses = l.uses + 1)
FOREACH (_ IN CASE WHEN first AND $rel = 'APPLIED' THEN [1] ELSE [] END |
  MERGE (pr)-[:APPLIED]->(l)
  SET l.prevented = l.prevented + 1,
      l.confidence = toFloat(round(CASE WHEN l.confidence + 0.2 > 1.0 THEN 1.0
                                        ELSE l.confidence + 0.2 END * 100)) / 100)
FOREACH (_ IN CASE WHEN first AND $rel = 'IGNORED' THEN [1] ELSE [] END |
  MERGE (pr)-[:IGNORED]->(l))
WITH pr, l, first
OPTIONAL MATCH (d:Decision)-[:FROM]->(l)
FOREACH (_ IN CASE WHEN first AND $rel = 'APPLIED' AND d IS NOT NULL THEN [1] ELSE [] END |
  MERGE (pr)-[:IMPLEMENTS]->(d))
RETURN DISTINCT l.id AS lesson_id, l.confidence AS confidence, l.uses AS uses, l.prevented AS prevented, first
""".strip(),
        example_params={"pr_id": "pr:15", "number": 15, "lesson_id": "lesson:L-1", "rel": "APPLIED"},
        read_only=False,
        internal=True,
    )
)

register(
    CatalogQuery(
        id="set_incident_embedding",
        code="M14",
        title="Store an incident embedding",
        explain="Store the Voyage embedding of an incident's summary (vector index on Incident.embedding).",
        cypher="MATCH (i:Incident {id: 'inc:' + $id}) SET i.embedding = vecf32($vec) RETURN i.id AS id",
        example_params={"id": "INC-1031", "vec": [0.0]},
        read_only=False,
        internal=True,
    )
)

register(
    CatalogQuery(
        id="set_lesson_embedding",
        code="M15",
        title="Store a lesson embedding",
        explain="Store the Voyage embedding of a lesson's text (vector index on Lesson.embedding).",
        cypher="MATCH (l:Lesson {id: $lesson_id}) SET l.embedding = vecf32($vec) RETURN l.id AS id",
        example_params={"lesson_id": "lesson:L-1", "vec": [0.0]},
        read_only=False,
        internal=True,
    )
)

register(
    CatalogQuery(
        id="incident_text",
        code="M16",
        title="Incident text",
        explain="An incident's title, summary, status and whether it already has an embedding.",
        cypher="""
MATCH (i:Incident {id: 'inc:' + $id})
RETURN i.title AS title, i.summary AS summary, i.embedding IS NOT NULL AS embedded, i.status AS status
""".strip(),
        example_params={"id": "INC-1031"},
        internal=True,
    )
)
