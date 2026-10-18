import type { AgentEvent, AgentName, StepPayload } from "../types/events";

const LANES: AgentName[] = ["triage", "cause", "memory", "comms"];

/** One column per agent: its tool calls as they stream in, then its summary. */
export function AgentLanes({ events }: { events: AgentEvent[] }) {
  return (
    <div className="lanes">
      {LANES.map((agent) => {
        const mine = events.filter((e) => e.agent === agent);
        const done = [...mine].reverse().find((e) => e.type === "agent.done");
        const running = mine.length > 0 && !done;
        return (
          <section key={agent} className={`lane ${running ? "running" : ""}`}>
            <h3>
              <span className={`agent agent-${agent}`}>{agent}</span>
              <span className="lane-state">{done ? "done" : running ? "working…" : "waiting"}</span>
            </h3>
            {mine
              .filter((e) => e.type === "agent.step")
              .map((e) => {
                const p = e.payload as unknown as StepPayload;
                return (
                  <div key={e.seq} className="step">
                    <code>{p.tool}</code> <span className="ms">{p.ms} ms</span>
                    <div>{p.summary}</div>
                  </div>
                );
              })}
            {done && <div className="lane-summary">{String(done.payload.summary ?? "")}</div>}
          </section>
        );
      })}
    </div>
  );
}
