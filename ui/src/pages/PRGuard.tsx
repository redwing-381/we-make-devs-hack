import { useEffect, useState } from "react";
import { api, type GuardPR } from "../api/client";
import type { ChangeRiskResponse, ConfigChange } from "../types/events";

const PRESETS: { label: string; change: ConfigChange }[] = [
  { label: "Act 2 · shipping→quote 600→100", change: { service: "shipping", key: "timeouts_ms.quote", old: 600, new: 100 } },
  { label: "Act 2 fixed · 600→450", change: { service: "shipping", key: "timeouts_ms.quote", old: 600, new: 450 } },
  { label: "Act 3 · catalog 400→80", change: { service: "recommendation", key: "timeouts_ms.product-catalog", old: 400, new: 80 } },
];

function Verdict({ title, res }: { title: string; res: ChangeRiskResponse | null }) {
  if (!res) return null;
  return (
    <section className={`verdict risk-${res.risk}`}>
      <h4>
        {title} <span className={`badge risk-${res.risk}`}>{res.risk} risk</span>
      </h4>
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
      <h2>PR Guard</h2>
      <p className="muted">
        The check our SDE agents run over MCP (<code>check_change_risk</code>) before a PR: every stored detector and
        lesson against the proposed change.
      </p>
      <div className="presets">
        {PRESETS.map((p) => (
          <button key={p.label} onClick={() => setChange(p.change)}>
            {p.label}
          </button>
        ))}
      </div>
      <div className="form-row">
        <label>service {field("service")}</label>
        <label>key {field("key")}</label>
        <label>old {field("old")}</label>
        <label>new {field("new")}</label>
        <button className="primary" onClick={() => check(false)}>
          Check
        </button>
        <button onClick={() => check(true)}>A/B: learned vs fresh tenant</button>
      </div>
      {error && <p className="error">{error}</p>}
      <div className={fresh ? "ab" : ""}>
        <Verdict title="whygraph_demo (learned)" res={demo} />
        <Verdict title="whygraph_fresh (never learned)" res={fresh} />
      </div>
      <h3>PRs seen by the guard</h3>
      {prs.length === 0 ? (
        <p className="muted">No PRs yet. They appear once PR Guard or an MCP check sees them.</p>
      ) : (
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
                  {p.author} {p.author_kind === "agent" && <span className="badge">agent</span>}
                </td>
                <td>{p.state}</td>
                <td>
                  {p.outcomes.map((o) => (
                    <span key={o.lesson + o.outcome} className={`badge outcome-${o.outcome.toLowerCase()}`}>
                      {o.lesson.replace("lesson:", "")} {o.outcome.toLowerCase().replace("_with", "")}
                    </span>
                  ))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
