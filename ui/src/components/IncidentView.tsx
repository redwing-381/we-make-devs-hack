import { useMemo, useState } from "react";
import { api, mergeGraphs, type ResolveResult } from "../api/client";
import { useEventStream } from "../lib/useEventStream";
import type { Finding, Subgraph } from "../types/events";
import { AgentLanes } from "./AgentLanes";
import { CypherDrawer } from "./CypherDrawer";
import { FindingCard } from "./FindingCard";
import { GraphCanvas } from "./GraphCanvas";

interface Props {
  url: string;
  incidentId?: string; // set for live incidents: enables Confirm + re-investigate
  graph?: string;
}

export function IncidentView({ url, incidentId, graph }: Props) {
  const [run, setRun] = useState(0);
  const { events, done } = useEventStream(`${url}${url.includes("?") ? "&" : "?"}run=${run}`);
  const [selected, setSelected] = useState<Finding | null>(null);
  const [live, setLive] = useState<Subgraph | null>(null);
  const [fix, setFix] = useState("");
  const [resolved, setResolved] = useState<ResolveResult | { error: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const findings = useMemo(
    () => events.filter((e) => e.type === "agent.finding").map((e) => e.payload.finding as Finding),
    [events],
  );
  const graphData = useMemo(() => mergeGraphs(...findings.map((f) => f.evidence)), [findings]);
  const opened = events.find((e) => e.type === "incident.opened");
  const incident = (opened?.payload.incident ?? {}) as { id?: string; title?: string; severity?: string };
  const lessonEvent = [...events].reverse().find((e) => e.type === "memory.lesson_written");
  const resolvedEvent = [...events].reverse().find((e) => e.type === "incident.resolved");
  const rootCause = [...findings].reverse().find((f) => f.agent === "cause" && f.query_id === "config_vs_reality");

  function select(f: Finding | null) {
    setSelected(f);
    setLive(null);
  }

  async function confirm() {
    if (!incidentId) return;
    setBusy(true);
    try {
      setResolved(await api.resolve(incidentId, fix || "Revert the change named as the root cause", "on-call"));
    } catch (e) {
      setResolved({ error: String(e) });
    } finally {
      setBusy(false);
    }
  }

  const lesson =
    (lessonEvent?.payload.lesson as { id: string; text: string; confidence: number } | undefined) ??
    (resolved && "lesson" in resolved ? resolved.lesson?.lesson : undefined);
  const detector = (lessonEvent?.payload.detector ?? (resolved && "lesson" in resolved ? resolved.lesson?.detector : null)) as
    | { id?: string; template?: string; backtest_hits?: number; backtest_total?: number }
    | null
    | undefined;

  return (
    <div className="incident">
      <header className="incident-head">
        <h2>{opened ? `${opened.incident_id} · ${incident.title ?? ""}` : "Waiting for the incident…"}</h2>
        {incident.severity && <span className="badge sev">{incident.severity}</span>}
        {opened?.payload.graph_only === true && <span className="badge">graph-only</span>}
        <span className="muted">{done ? "investigation complete" : `${events.length} events`}</span>
        <span className="spacer" />
        <button
          onClick={() => {
            select(null);
            setRun((n) => n + 1);
          }}
        >
          {incidentId ? "Reload stream" : "Replay"}
        </button>
        {incidentId && (
          <button onClick={() => api.investigate(incidentId).then(() => setRun((n) => n + 1))}>Re-investigate</button>
        )}
      </header>

      <AgentLanes events={events} />

      <div className="incident-body">
        <div className="incident-main">
          <GraphCanvas graph={graphData} highlight={live ?? selected?.evidence ?? null} />
          {selected && (
            <CypherDrawer finding={selected} graph={graph} onRun={setLive} onClose={() => select(null)} />
          )}
        </div>
        <aside className="findings">
          {findings.length === 0 && <p className="muted">Findings appear here as the agents ground them.</p>}
          {findings.map((f) => (
            <FindingCard key={f.id} finding={f} selected={selected?.id === f.id} onSelect={select} />
          ))}
          {incidentId && done && rootCause && !resolvedEvent && !(resolved && "lesson" in resolved) && (
            <section className="confirm">
              <h4>Confirm root cause + fix</h4>
              <p className="muted">Confirming turns this incident into a lesson and a detector.</p>
              <input
                value={fix}
                onChange={(e) => setFix(e.target.value)}
                placeholder="What fixed it, e.g. Restore checkout timeouts_ms.payment to 800"
              />
              <button className="primary" onClick={confirm} disabled={busy}>
                {busy ? "Writing memory…" : "Confirm root cause + fix"}
              </button>
              {resolved && "error" in resolved && <p className="error">{resolved.error}</p>}
            </section>
          )}
          {(lesson || (resolved && "lesson_pending" in resolved && resolved.lesson_pending)) && (
            <section className="lesson-banner">
              <h4>Memory written</h4>
              {lesson ? (
                <>
                  <p>
                    <strong>{lesson.id.replace("lesson:", "")}</strong>: {lesson.text}
                  </p>
                  {detector?.id && (
                    <p className="muted">
                      Detector {String(detector.id).replace("det:", "")} ({detector.template}) · backtest{" "}
                      {detector.backtest_hits}/{detector.backtest_total} past changes
                    </p>
                  )}
                </>
              ) : (
                <p className="muted">Incident closed; the memory core isn't available, so no lesson was written.</p>
              )}
            </section>
          )}
        </aside>
      </div>
    </div>
  );
}
