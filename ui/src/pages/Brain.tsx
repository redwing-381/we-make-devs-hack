import { useState } from "react";
import { api, type BrainAnswer } from "../api/client";
import { GraphCanvas } from "../components/GraphCanvas";
import type { Subgraph } from "../types/events";

const EXAMPLES = [
  "Who knows payment?",
  "Why is shipping→quote 450 ms?",
  "Why is checkout timeouts_ms.payment 200?",
  "Which runbooks are out of date?",
  "How do we handle kafka consumer lag?",
];

export function BrainPage() {
  const [question, setQuestion] = useState(EXAMPLES[0]);
  const [graphOnly, setGraphOnly] = useState(false);
  const [res, setRes] = useState<BrainAnswer | null>(null);
  const [focus, setFocus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function ask(q = question) {
    setQuestion(q);
    setBusy(true);
    setError(null);
    setFocus(null);
    try {
      setRes(await api.ask(q, graphOnly));
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  const highlight: Subgraph | null =
    res && focus
      ? { nodes: res.evidence.nodes.filter((n) => n.id === focus), rels: res.evidence.rels.filter((r) => r.src === focus || r.dst === focus) }
      : null;

  return (
    <div className="page">
      <header className="page-head">
        <h1>Ask the company brain</h1>
        <p>People, ownership, changes, decisions and runbooks sit in one graph. Every answer cites the nodes it came from.</p>
      </header>
      <div className="presets">
        {EXAMPLES.map((q) => (
          <button key={q} onClick={() => ask(q)}>
            {q}
          </button>
        ))}
      </div>
      <div className="ask-row">
        <input className="wide" value={question} onChange={(e) => setQuestion(e.target.value)} onKeyDown={(e) => e.key === "Enter" && ask()} />
        <label className="check">
          <input type="checkbox" checked={graphOnly} onChange={(e) => setGraphOnly(e.target.checked)} /> Graph-only
        </label>
        <button className="primary" onClick={() => ask()} disabled={busy}>
          {busy ? "Asking…" : "Ask"}
        </button>
      </div>
      {error && <p className="error">{error}</p>}
      {res && (
        <>
          <section className="answer">
            <p>{res.answer.split("`").map((part, i) => (i % 2 ? <code key={i}>{part}</code> : part))}</p>
            <div className="chips">
              {res.sources.map((s) => (
                <button key={s} className={`chip ${focus === s ? "on" : ""}`} onClick={() => setFocus(focus === s ? null : s)}>
                  {s}
                </button>
              ))}
            </div>
            <p className="muted">
              {res.graph_only ? "Graph-only answer" : "Written by Claude from grounded facts"} · {res.steps.length} queries:{" "}
              {res.steps.map((s) => s.query_id).join(", ")}
            </p>
          </section>
          {res.evidence.nodes.length > 0 && <GraphCanvas graph={res.evidence} highlight={highlight} height={380} />}
        </>
      )}
    </div>
  );
}
