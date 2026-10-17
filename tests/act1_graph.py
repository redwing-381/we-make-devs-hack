"""A fake Act 1 graph slice: what the F-A2 catalog queries should return for INC-1031."""

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


alert = n("Alert", "alert:a-901")
frontend, checkout, payment = (
    n("Service", "svc:frontend", tier="edge"),
    n("Service", "svc:checkout"),
    n("Service", "svc:payment"),
)
accounting, orders = n("Service", "svc:accounting"), n("Topic", "topic:orders")
deploy, commit = n("Deploy", "deploy:9f2c1ab"), n("Commit", "commit:9f2c1ab")
bot = n("Engineer", "eng:coder-bot", kind="agent")
key = n("ConfigKey", "cfg:checkout.timeouts_ms.payment", kind="timeout")

ROWS = {
    "root_alert": (
        ["service", "alert", "path"],
        [["checkout", "alert:a-901", Path([alert, checkout], [e(alert, "FIRED_ON", checkout)])]],
    ),
    "blast_radius": (
        ["service", "tier", "hops", "delayed", "path"],
        [
            ["frontend", "edge", 1, False, Path([checkout, frontend], [e(frontend, "CALLS", checkout)])],
            [
                "accounting",
                "core",
                2,
                True,
                Path(
                    [checkout, orders, accounting],
                    [e(checkout, "PUBLISHES", orders), e(accounting, "CONSUMES", orders)],
                ),
            ],
        ],
    ),
    "suspect_changes": (
        ["sha", "message", "author", "author_kind", "service", "hops", "mins_before", "score", "path"],
        [
            [
                SHA,
                "lower payment timeout",
                "coder-bot",
                "agent",
                "checkout",
                0,
                3,
                0.88,
                Path(
                    [checkout, deploy, commit, bot],
                    [e(deploy, "OF", checkout), e(deploy, "SHIPS", commit), e(commit, "AUTHORED_BY", bot)],
                ),
            ]
        ],
    ),
    "config_vs_reality": (
        ["caller", "callee", "key", "old", "new", "callee_p99_at_change", "below_p99", "path"],
        [
            [
                "checkout",
                "payment",
                "timeouts_ms.payment",
                800,
                200,
                450,
                True,
                Path(
                    [commit, key, checkout, payment],
                    [
                        e(commit, "CHANGES", key),
                        e(key, "CONFIGURES", checkout),
                        e(checkout, "CALLS", payment),
                    ],
                ),
            ]
        ],
    ),
}


class Recorder:
    """Fake query runner: records calls, answers from ROWS."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, query_id, params, graph):
        self.calls.append((query_id, params))
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
    """Register placeholder catalog entries for any F-A2 query not merged yet; returns what was added."""
    added = []
    for qid in ROWS:
        if qid not in queries.CATALOG:
            queries.register(
                CatalogQuery(id=qid, code="T", title=qid, explain="test stub", cypher=f"// {qid}")
            )
            added.append(qid)
    return added
