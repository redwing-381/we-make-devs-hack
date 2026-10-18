import { useEffect, useState } from "react";
import { api, type GuardPR } from "../api/client";
import type { ChangeRiskResponse, ConfigChange } from "../types/events";

const PRESETS: { label: string; change: ConfigChange }[] = [
  { label: "Act 2 · shipping→quote 600→100", change: { service: "shipping", key: "timeouts_ms.quote", old: 600, new: 100 } },
  { label: "Act 2 fixed · 600→460", change: { service: "shipping", key: "timeouts_ms.quote", old: 600, new: 460 } },
  { label: "Act 3 · catalog 400→80", change: { service: "recommendation", key: "timeouts_ms.product-catalog", old: 400, new: 80 } },
];

function Verdict({ title, res }: { title: string; res: ChangeRiskResponse | null }) {
  if (!res) return null;
  return (
    <section className={`verdict risk-${res.risk}`}>
      <h4>{title}</h4>
      <div className="big">{res.risk === "none" ? "No known risk" : `${res.risk[0].toUpperCase()}${res.risk.slice(1)} risk`}</div>
      <p>{res.advice}</p>
      {res.warnings.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Change</th>
              <th>Proposed</th>
              <th>Safe min</th>
              <th>Lesson</th>
              <th>Learned from</th>
            </tr>
          </thead>
          <tbody>
            {res.warnings.map((w, i) => (
              <tr key={i}>
                <td>
                  <code>
                    {w.service}.{w.key}
                  </code>
                </td>
                <td>{w.proposed}</td>
                <td>{w.safe_min != null ? `≥ ${Math.ceil(w.safe_min)}` : "n/a"}</td>
                <td>{w.lesson_id?.replace("lesson:", "") ?? w.detector_id}</td>
                <td>{w.incident_id?.replace("inc:", "") ?? "n/a"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

export function PRGuardPage() {
  const [change, setChange] = useState<ConfigChange>(PRESETS[0].change);
  const [demo, setDemo] = useState<ChangeRiskResponse | null>(null);
  const [fresh, setFresh] = useState<ChangeRiskResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [prs, setPrs] = useState<GuardPR[]>([]);

  useEffect(() => {
    api.guardPrs().then(setPrs).catch(() => setPrs([]));
  }, [demo]);

  async function check(ab: boolean) {
    setError(null);
    try {
      setDemo(await api.guardCheck([change]));
      setFresh(ab ? await api.guardCheck([change], "whygraph_fresh") : null);
    } catch (e) {
      setError(String(e));
    }
  }

  const field = (k: keyof ConfigChange) => (
    <input
      value={String(change[k] ?? "")}
      onChange={(e) => {
        const v = e.target.value;
        setChange({ ...change, [k]: k === "old" || k === "new" ? (v === "" ? null : Number(v)) : v } as ConfigChange);
      }}
    />
  );

  return (
    <div className="page">
      <header className="page-head">
        <h1>Check a change before it ships</h1>
        <p>
          The same check coding agents run over MCP (<code>check_change_risk</code>) before they open a PR. Every
          stored detector and lesson is tested against the proposed change.
        </p>
      </header>
      <div className="presets">
        {PRESETS.map((p) => (
          <button key={p.label} onClick={() => setChange(p.change)}>
            {p.label}
          </button>
        ))}
      </div>
      <div className="form-row">
        <label>Service {field("service")}</label>
        <label>Key {field("key")}</label>
        <label>Current {field("old")}</label>
        <label>Proposed {field("new")}</label>
        <button className="primary" onClick={() => check(false)}>
          Check
        </button>
        <button onClick={() => check(true)}>Compare with a fresh graph</button>
      </div>
      {error && <p className="error">{error}</p>}
      <div className={fresh ? "ab" : ""}>
        <Verdict title="whygraph_demo, the graph that learned" res={demo} />
        <Verdict title="whygraph_fresh, same code, never learned" res={fresh} />
      </div>
      <h3>Pull requests the guard has seen</h3>
      {prs.length === 0 ? (
        <p className="empty">No pull requests yet. They show up here once PR Guard or an agent's MCP check sees one.</p>
      ) : (
        <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>PR</th>
              <th>Author</th>
              <th>State</th>
              <th>Lessons</th>
            </tr>
          </thead>
          <tbody>
            {prs.map((p) => (
              <tr key={p.number}>
                <td>{p.url ? <a href={p.url}>#{p.number}</a> : `#${p.number}`} {p.title}</td>
                <td>
                  {p.author} {p.author_kind === "agent" && <span className="flag">agent</span>}
                </td>
                <td>{p.state}</td>
                <td>
                  {p.outcomes.map((o) => (
                    <span key={o.lesson + o.outcome} className={`flag outcome-${o.outcome.toLowerCase()}`}>
                      {o.lesson.replace("lesson:", "")} {o.outcome.toLowerCase().replace("_with", "")}
                    </span>
                  ))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      )}
    </div>
  );
}
