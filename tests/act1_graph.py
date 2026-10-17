"""A fake Act 1 graph slice: rows in exactly the shape the real catalog queries return for INC-1031.

Keep these columns in sync with whygraph/graph/queries.py; tests/test_e2e_act1.py checks the real thing
against FalkorDB. The Recorder also rejects any call whose params don't match the real query's $params.
"""

from falkordb import Edge, Node, Path

from whygraph.agents.blackboard import MemoryBoard
from whygraph.graph import queries
from whygraph.graph.client import to_output
from whygraph.graph.queries import CatalogQuery

ALERT_TS = 1_800_000_000_000
SHA = "9f2c1ab4d1e07c3a"

_ids = iter(range(1, 1000))


def n(label, id, **props):
    return Node(node_id=next(_ids), labels=label, properties={"id": id, "name": id.split(":", 1)[1], **props})


def e(src, rel, dst, **props):
    return Edge(src.id, rel, dst.id, edge_id=next(_ids), properties=props)


def p(*nodes_and_edges):
    return Path(
        [x for x in nodes_and_edges if isinstance(x, Node)],
        [x for x in nodes_and_edges if isinstance(x, Edge)],
    )


alert, alert2 = n("Alert", "alert:a-901"), n("Alert", "alert:a-902")
frontend, checkout, payment = (
    n("Service", "svc:frontend", tier="edge"),
    n("Service", "svc:checkout"),
    n("Service", "svc:payment"),
)
accounting, orders = n("Service", "svc:accounting"), n("Topic", "topic:orders")
deploy, commit = n("Deploy", "deploy:d-311"), n("Commit", "commit:9f2c1ab")
bot = n("Engineer", "eng:coder-bot", kind="agent")
key = n("ConfigKey", "cfg:checkout.timeouts_ms.payment", kind="timeout")
incident, past = n("Incident", "inc:INC-1031"), n("Incident", "inc:INC-0977")
symptom = n("Feature", "feat:symptom:caller_5xx_callee_healthy")
team, priya = n("Team", "team:payments"), n("Engineer", "eng:priya", kind="human", on_call=True)
quote_key = n("ConfigKey", "cfg:shipping.timeouts_ms.quote", kind="timeout")
commit15, pr15 = n("Commit", "commit:5e1d2aa"), n("PR", "pr:15")
decision = n("Decision", "dec:caller-timeouts", title="Keep caller timeouts ≥ 1.5× the callee p99")
lesson1 = n("Lesson", "lesson:L-1", text="a timeout below the callee p99 turns slow calls into errors")
runbook = n("Runbook", "rb:payment-latency")

ROWS = {
    "root_alert": (
        [
            "service",
            "alert",
            "signal",
            "ts",
            "healthy_callees",
            "alerting_above",
            "path",
            "callees",
            "upstream",
        ],
        [
            [
                "checkout",
                "alert:a-901",
                "error_rate",
                ALERT_TS,
                ["payment"],
                ["frontend"],
                p(alert, e(alert, "FIRED_ON", checkout), checkout),
                [p(checkout, e(checkout, "CALLS", payment), payment)],
                [
                    p(
                        alert2,
                        e(alert2, "FIRED_ON", frontend),
                        frontend,
                        e(frontend, "CALLS", checkout),
                        checkout,
                    )
                ],
            ]
        ],
    ),
    "blast_radius": (
        ["service", "tier", "hops", "impact", "path"],
        [
            [
                "accounting",
                "core",
                2,
                "delayed",
                p(
                    checkout,
                    e(checkout, "PUBLISHES", orders),
                    orders,
                    e(accounting, "CONSUMES", orders),
                    accounting,
                ),
            ],
            ["frontend", "edge", 1, "sync", p(checkout, e(frontend, "CALLS", checkout), frontend)],
        ],
    ),
    "suspect_changes": (
        [
            "sha",
            "message",
            "author",
            "kind",
            "service",
            "via",
            "deploy",
            "minutes_before",
            "hops",
            "prior",
            "config_change",
            "score",
            "path",
            "author_path",
            "config",
            "pr",
        ],
        [
            [
                SHA,
                "lower payment timeout",
                "coder-bot",
                "agent",
                "checkout",
                "deployed",
                "deploy:d-311",
                3,
                0,
                0,
                True,
                0.88,
                p(checkout, e(deploy, "OF", checkout), deploy, e(deploy, "SHIPS", commit), commit),
                p(commit, e(commit, "AUTHORED_BY", bot), bot),
                [p(commit, e(commit, "CHANGES", key), key, e(key, "TARGETS", payment), payment)],
                [],
            ]
        ],
    ),
    "config_vs_reality": (
        [
            "caller",
            "callee",
            "key",
            "kind",
            "old",
            "new",
            "callee_p99_at_change",
            "callee_p99_now",
            "below_p99",
            "path",
            "target",
            "pr",
            "author",
            "deploy",
            "alerts",
        ],
        [
            [
                "checkout",
                "payment",
                "timeouts_ms.payment",
                "timeout",
                800,
                200,
                450,
                452,
                True,
                p(
                    commit,
                    e(commit, "CHANGES", key),
                    key,
                    e(key, "CONFIGURES", checkout),
                    checkout,
                    e(checkout, "CALLS", payment),
                    payment,
                ),
                p(key, e(key, "TARGETS", payment), payment),
                [],
                [],
                [],
                [],
            ]
        ],
    ),
    "similar_incidents": (
        ["incident", "title", "shared", "jaccard", "fix", "lesson_id", "evidence", "lesson"],
        [
            [
                "inc:INC-0977",
                "cart retry storm",
                ["symptom:caller_5xx_callee_healthy"],
                0.31,
                "add jittered backoff to cart retries",
                "lesson:L-7",
                [
                    p(
                        incident,
                        e(incident, "HAS_FEATURE", symptom),
                        symptom,
                        e(past, "HAS_FEATURE", symptom),
                        past,
                    )
                ],
                [],
            ]
        ],
    ),
    "who_knows": (
        [
            "handle",
            "name",
            "kind",
            "on_call",
            "team",
            "owner",
            "commits",
            "config_changes",
            "resolved",
            "path",
            "changed",
        ],
        [
            [
                "priya",
                "Priya",
                "human",
                True,
                "payments",
                True,
                4,
                1,
                2,
                [p(checkout, e(team, "OWNS", checkout), team, e(priya, "MEMBER_OF", team), priya)],
                [],
            ],
        ],
    ),
    "why_is": (
        [
            "key",
            "value",
            "sha",
            "pr",
            "author",
            "old",
            "new",
            "ts",
            "lessons",
            "incidents",
            "changed",
            "author_path",
            "why",
            "origin",
            "applied",
            "caused_incident",
        ],
        [
            [
                "cfg:shipping.timeouts_ms.quote",
                450,
                "5e1d2aa0",
                15,
                "coder-bot",
                600,
                450,
                ALERT_TS,
                ["lesson:L-1"],
                ["inc:INC-1031"],
                p(
                    quote_key,
                    e(commit15, "CHANGES", quote_key),
                    commit15,
                    e(pr15, "CONTAINS", commit15),
                    pr15,
                ),
                p(commit15, e(commit15, "AUTHORED_BY", bot), bot),
                [
                    p(
                        pr15,
                        e(pr15, "IMPLEMENTS", decision),
                        decision,
                        e(decision, "FROM", lesson1),
                        lesson1,
                        e(lesson1, "LEARNED_FROM", incident),
                        incident,
                    )
                ],
                [],
                [],
                [],
            ]
        ],
    ),
    "doc_search": (
        ["id", "kind", "title", "text", "score", "node", "mentions"],
        [
            [
                "rb:payment-latency",
                "runbook",
                "Payment latency",
                "Check payment p99 before tuning timeouts",
                0.81,
                runbook,
                [p(runbook, e(runbook, "MENTIONS", key), key)],
            ]
        ],
    ),
    "stale_runbooks": (
        [
            "runbook",
            "title",
            "updated_at",
            "key",
            "value",
            "changed_to",
            "changed_at",
            "changes_since",
            "path",
        ],
        [
            [
                "rb:payment-latency",
                "Payment latency",
                ALERT_TS - 86_400_000,
                "cfg:checkout.timeouts_ms.payment",
                200,
                200,
                ALERT_TS,
                1,
                p(runbook, e(runbook, "MENTIONS", key), key, e(commit, "CHANGES", key), commit),
            ]
        ],
    ),
}


class Recorder:
    """Fake query runner: answers from ROWS, and rejects params the real query wouldn't accept."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, query_id, params, graph):
        self.calls.append((query_id, params))
        missing = queries.required_params(queries.get(query_id)) - set(params)
        assert not missing, f"{query_id} called without {sorted(missing)} (got {sorted(params)})"
        columns, rows = ROWS[query_id]
        return to_output(columns, rows)


class Act1Board(MemoryBoard):
    def incident(self, incident_id):
        return {
            "id": incident_id,
            "title": "checkout error rate spike",
            "severity": "sev2",
            "status": "open",
            "started_at": ALERT_TS,
            "alerts": [
                {"id": "alert:a-901", "service": "checkout", "ts": ALERT_TS},
                {"id": "alert:a-902", "service": "frontend", "ts": ALERT_TS + 4000},
            ],
        }


def register_stubs() -> list[str]:
    """Register placeholder catalog entries for any query not in the catalog; returns what was added."""
    added = []
    for qid in ROWS:
        if qid not in queries.CATALOG:
            queries.register(
                CatalogQuery(id=qid, code="T", title=qid, explain="test stub", cypher=f"// {qid}")
            )
            added.append(qid)
    return added
