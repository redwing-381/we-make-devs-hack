import { useState } from "react";
import { api } from "../api/client";
import type { Finding, Subgraph } from "../types/events";

interface Props {
  finding: Finding;
  graph?: string;
  onRun: (subgraph: Subgraph | null) => void;
  onClose: () => void;
}

/** The evidence behind a claim: the catalog query, its params, and Run live against FalkorDB. */
export function CypherDrawer({ finding, graph, onRun, onClose }: Props) {
  const [state, setState] = useState<{ ms: number; rows: number } | { error: string } | null>(null);
  const [busy, setBusy] = useState(false);

  async function runLive() {
    setBusy(true);
    try {
      const res = await api.runQuery(finding.query_id, finding.params, graph);
      setState({ ms: res.ms, rows: res.rows.length });
      onRun(res.subgraph);
    } catch (e) {
      setState({ error: String(e) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="drawer">
      <header>
        <span className={`agent agent-${finding.agent}`}>{finding.agent}</span>
        <code>{finding.query_id}</code>
        <span className="muted">confidence {Math.round(finding.confidence * 100)}% · from graph signals</span>
        <button className="ghost" onClick={onClose}>
          Close
        </button>
      </header>
      <p className="claim">{finding.claim}</p>
      <div className="drawer-grid">
        <div>
          <h4>Cypher</h4>
          <pre>{finding.cypher ?? "(catalog query)"}</pre>
        </div>
        <div>
          <h4>Params</h4>
          <pre>{JSON.stringify(finding.params, null, 2)}</pre>
          <h4>Evidence path</h4>
          <ol className="hops">
            {finding.evidence.rels.map((r) => (
              <li key={r.id}>
                <code>{r.src.split(":").slice(1).join(":")}</code> <span className="rel">-[{r.type}]→</span>{" "}
                <code>{r.dst.split(":").slice(1).join(":")}</code>
              </li>
            ))}
          </ol>
        </div>
      </div>
      <footer>
        <button className="primary" onClick={runLive} disabled={busy}>
          {busy ? "Running…" : "Run live"}
        </button>
        {state && "ms" in state && (
          <span className="muted">
            {state.rows} rows in {state.ms} ms. The canvas now highlights what FalkorDB returned
          </span>
        )}
        {state && "error" in state && <span className="error">{state.error}</span>}
      </footer>
    </section>
  );
}
