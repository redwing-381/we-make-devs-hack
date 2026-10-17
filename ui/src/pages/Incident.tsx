import { useMemo, useState } from "react";
import { streamUrl } from "../api/client";
import { AgentLanes } from "../components/AgentLanes";
import { FindingCard } from "../components/FindingCard";
import { GraphCanvas } from "../components/GraphCanvas";
import { useEventStream } from "../lib/useEventStream";
import type { Finding, Subgraph } from "../types/events";

/** Incident view. Until F-B1 lands, it replays the Act 1 fixture through the same SSE format. */
export function IncidentPage() {
  const [run, setRun] = useState(0);
  const { events, done } = useEventStream(`${streamUrl.replay("act1-fixture", 4)}&run=${run}`);
  const [selected, setSelected] = useState<Finding | null>(null);

  const findings = useMemo(
    () => events.filter((e) => e.type === "agent.finding").map((e) => e.payload.finding as Finding),
    [events],
  );
  const graph = useMemo<Subgraph>(() => {
    const nodes = new Map<string, Subgraph["nodes"][number]>();
    const rels = new Map<string, Subgraph["rels"][number]>();
    findings.forEach((f) => {
      f.evidence.nodes.forEach((n) => nodes.set(n.id, n));
      f.evidence.rels.forEach((r) => rels.set(r.id, r));
    });
    return { nodes: [...nodes.values()], rels: [...rels.values()] };
  }, [findings]);
  const opened = events.find((e) => e.type === "incident.opened");
  const title = (opened?.payload.incident as { title?: string } | undefined)?.title;

  return (
    <div className="incident">
      <header className="incident-head">
        <h2>{opened ? `${opened.incident_id} · ${title}` : "Waiting for incident…"}</h2>
        <span className="muted">{done ? "investigation complete" : `${events.length} events`}</span>
        <button
          onClick={() => {
            setSelected(null);
            setRun((n) => n + 1);
          }}
        >
          Replay
        </button>
      </header>
      <AgentLanes events={events} />
      <div className="incident-body">
        <GraphCanvas graph={graph} highlight={selected?.evidence ?? null} />
        <aside className="findings">
          {findings.map((f) => (
            <FindingCard key={f.id} finding={f} selected={selected?.id === f.id} onSelect={setSelected} />
          ))}
        </aside>
      </div>
    </div>
  );
}
