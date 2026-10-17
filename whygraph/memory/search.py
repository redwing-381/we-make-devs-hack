"""doc_search for the Brain: full-text (Q8) + vector (Q8v) over runbooks, chat and lessons (F-A5).

Agents can't send a 1024-d vector, so they call this function with a plain question; it builds the full-text
terms and the embedding itself. Without Voyage it degrades to full-text only.
"""

import re
from dataclasses import dataclass

from whygraph.graph import queries
from whygraph.memory.evidence import merge, row_subgraph, try_embed
from whygraph.models.events import Subgraph

STOPWORDS = set(
    "a an and are as at be by did do does for from how i in is it its me my of on or our so that the this to "
    "was we what when where which who why with you".split()
)


@dataclass
class Doc:
    id: str
    kind: str  # runbook | chat | lesson
    title: str | None
    text: str
    score: float  # max of normalised full-text score and vector similarity
    evidence: Subgraph


def terms(question: str) -> str:
    """'Why is shipping->quote 450 ms?' -> 'shipping|quote|450|ms' (FalkorDB full-text OR syntax)."""
    words = [w for w in re.findall(r"[a-z0-9_]+", question.lower()) if w not in STOPWORDS and len(w) > 1]
    return "|".join(dict.fromkeys(words))


def doc_search(question: str, graph: str | None = None, k: int = 5) -> list[Doc]:
    docs: dict[str, Doc] = {}
    t = terms(question)
    if t:
        out = queries.run("doc_search", {"terms": t}, graph=graph)
        top = {
            k: max((r["score"] for r in out.rows if r["kind"] == k), default=1.0) or 1.0
            for k in ("runbook", "chat")
        }
        for r in out.rows:
            docs[r["id"]] = Doc(
                r["id"],
                r["kind"],
                r["title"],
                r["text"],
                round(r["score"] / top[r["kind"]] * (1.0 if r["kind"] == "runbook" else 0.8), 3),
                row_subgraph(out, r, ["node", "mentions"]),
            )
    vec = try_embed(question)
    if vec is not None:
        out = queries.run("doc_search_vec", {"q": vec}, graph=graph)
        for r in out.rows:
            ev = row_subgraph(out, r, ["node", "mentions"])
            if r["id"] in docs:
                d = docs[r["id"]]
                d.score, d.evidence = max(d.score, round(r["score"], 3)), merge(d.evidence, ev)
            else:
                docs[r["id"]] = Doc(r["id"], r["kind"], r["title"], r["text"], round(r["score"], 3), ev)
    return sorted(docs.values(), key=lambda d: (-d.score, d.id))[:k]
