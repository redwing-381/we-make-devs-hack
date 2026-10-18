import { useEffect, useState } from "react";
import { api, type MemoryState } from "../api/client";

const TYPES: { key: "episodic" | "semantic" | "procedural"; title: string; what: string }[] = [
  { key: "episodic", title: "Episodic", what: "what happened: incidents, investigations, grounded findings" },
  { key: "semantic", title: "Semantic", what: "what it means: lessons and failure patterns" },
  { key: "procedural", title: "Procedural", what: "what to do: detectors (stored Cypher) and runbooks" },
];

export function MemoryPage() {
  const [mem, setMem] = useState<MemoryState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = () =>
    api
      .memory()
      .then((m) => {
        setMem(m);
        setError(null);
      })
      .catch((e) => setError(String(e)));
  useEffect(() => {
    load();
  }, []);

  if (error) return <p className="error">{error}</p>;
  if (!mem) return <p className="muted">Loading…</p>;
  const live = mem.lessons.filter((l) => l.source === "live");
  return (
    <div className="page">
      <h2>
        Memory <button onClick={load}>Refresh</button>
      </h2>
      <div className="types">
        {TYPES.map((t) => (
          <section key={t.key} className="type-card">
            <h4>{t.title}</h4>
            <p className="muted">{t.what}</p>
            <div className="counts">
              {Object.entries(mem.types[t.key]).map(([k, v]) => (
                <span key={k}>
                  <strong>{v}</strong> {k}
                </span>
              ))}
            </div>
          </section>
        ))}
      </div>
      <h3>Lessons {live.length > 0 && <span className="badge">{live.length} learned live</span>}</h3>
      <table>
        <thead>
          <tr>
            <th>Lesson</th>
            <th>Learned from</th>
            <th>Confidence</th>
            <th>Uses</th>
            <th>Prevented</th>
            <th>PRs</th>
          </tr>
        </thead>
        <tbody>
          {mem.lessons.map((l) => (
            <tr key={l.id} className={l.source === "live" ? "live" : l.status === "superseded" ? "faded" : ""}>
              <td>
                <strong>{l.id.replace("lesson:", "")}</strong> {l.text}
                {l.status === "superseded" && <span className="badge">superseded</span>}
              </td>
              <td>{l.incident?.replace("inc:", "")}</td>
              <td>
                <div className="bar">
                  <i style={{ width: `${Math.round((l.confidence ?? 0) * 100)}%` }} />
                </div>
                {l.confidence?.toFixed(2)}
              </td>
              <td>{l.uses ?? 0}</td>
              <td>{l.prevented ?? 0}</td>
              <td>
                {l.outcomes.map((o) => (
                  <span key={`${o.pr}${o.outcome}`} className={`badge outcome-${o.outcome.toLowerCase()}`}>
                    #{o.pr} {o.outcome.toLowerCase().replace("_with", "")}
                  </span>
                ))}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <h3>Detectors</h3>
      <table>
        <thead>
          <tr>
            <th>Detector</th>
            <th>Pattern</th>
            <th>Backtest</th>
            <th>Stored Cypher</th>
          </tr>
        </thead>
        <tbody>
          {mem.detectors.map((d) => (
            <tr key={d.id} className={d.source === "live" ? "live" : ""}>
              <td>
                <strong>{d.id.replace("det:", "")}</strong> {d.template}
              </td>
              <td>{d.pattern}</td>
              <td>{d.backtest_total != null ? `${d.backtest_hits}/${d.backtest_total} past changes` : "n/a"}</td>
              <td>
                <details>
                  <summary>show</summary>
                  <pre>{d.cypher}</pre>
                </details>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
