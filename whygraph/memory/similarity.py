"""Episodic recall: which resolved incidents looked like this one (F-A3).

    score = 0.7 x Jaccard(HAS_FEATURE sets)  +  0.3 x (1 - vector distance of the summaries)

The structural part does the real work: features are service-agnostic, so a timeout cut below the callee p99
on recommendation->product-catalog matches the one on checkout->payment. The vector part only breaks ties
between incidents with similar shapes; without Voyage it is 0 and recall still works.
"""

from dataclasses import dataclass, field

from whygraph.graph import queries
from whygraph.graph.features import human_id
from whygraph.memory.evidence import merge, row_subgraph, try_embed
from whygraph.models.events import Subgraph

STRONG_MATCH = 0.5
W_JACCARD = 0.7
W_VECTOR = 0.3


@dataclass
class Match:
    incident_id: str  # human id, e.g. "INC-1031"
    score: float
    jaccard: float
    vector_sim: float
    shared: list[str]
    lesson_id: str | None  # active lesson learned from it, e.g. "lesson:L-1"
    fix: str | None
    evidence: Subgraph
    title: str | None = None
    lesson: Subgraph = field(default_factory=Subgraph)

    @property
    def strong(self) -> bool:
        return self.score >= STRONG_MATCH


def ensure_incident_embedding(incident_id: str, graph: str | None = None) -> bool:
    """Embed the incident's summary once, so the vector half of the score has something to compare."""
    inc = human_id(incident_id)
    rows = queries.run("incident_text", {"id": inc}, graph=graph).rows
    if not rows:
        return False
    if rows[0]["embedded"]:
        return True
    vec = try_embed(rows[0]["summary"] or rows[0]["title"])
    if vec is None:
        return False
    queries.run("set_incident_embedding", {"id": inc, "vec": vec}, graph=graph)
    return True


def similar_incidents(incident_id: str, graph: str | None = None, k: int = 5) -> list[Match]:
    """0.7*Jaccard(HAS_FEATURE) + 0.3*(1 - vector distance). Resolved incidents only."""
    inc = human_id(incident_id)
    ensure_incident_embedding(inc, graph)
    shape = queries.run("similar_incidents", {"id": inc}, graph=graph)
    text = queries.run("similar_incidents_vec", {"id": inc}, graph=graph)

    matches: dict[str, Match] = {}
    for row in shape.rows:
        matches[row["incident"]] = Match(
            incident_id=human_id(row["incident"]),
            score=0.0,
            jaccard=round(row["jaccard"], 3),
            vector_sim=0.0,
            shared=sorted(row["shared"]),
            lesson_id=row["lesson_id"],
            fix=row["fix"],
            evidence=row_subgraph(shape, row, ["evidence"]),
            title=row["title"],
            lesson=row_subgraph(shape, row, ["lesson"]),
        )
    for row in text.rows:
        m = matches.get(row["incident"])
        if m is None:  # similar text, nothing structural in common
            m = matches[row["incident"]] = Match(
                incident_id=human_id(row["incident"]),
                score=0.0,
                jaccard=0.0,
                vector_sim=0.0,
                shared=[],
                lesson_id=None,
                fix=None,
                evidence=Subgraph(),
                title=row["title"],
            )
        m.vector_sim = round(max(0.0, min(1.0, row["vector_sim"])), 3)
        m.evidence = merge(m.evidence, row_subgraph(text, row, ["node"]))
    for m in matches.values():
        m.score = round(W_JACCARD * m.jaccard + W_VECTOR * m.vector_sim, 3)
    return sorted(matches.values(), key=lambda m: (-m.score, m.incident_id))[:k]
