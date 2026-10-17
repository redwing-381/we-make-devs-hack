import type { AgentEvent, AgentName, StepPayload } from "../types/events";

const LANES: AgentName[] = ["triage", "cause", "memory", "comms"];

/** One column per agent showing its tool calls as they stream in. F-C1 owns the styling/animation. */
export function AgentLanes({ events }: { events: AgentEvent[] }) {
  return (
    <div className="lanes">
      {LANES.map((agent) => {
        const mine = events.filter((e) => e.agent === agent);
        const done = mine.some((e) => e.type === "agent.done");
        return (
          <section key={agent} className="lane">
            <h3>
              <span className={`agent agent-${agent}`}>{agent}</span> {done ? "✓" : mine.length ? "…" : ""}
            </h3>
            {mine
              .filter((e) => e.type === "agent.step")
              .map((e) => {
                const p = e.payload as unknown as StepPayload;
                return (
                  <div key={e.seq} className="step">
                    <code>{p.tool}</code> <span className="ms">{p.ms}ms</span>
                    <div>{p.summary}</div>
                  </div>
                );
              })}
          </section>
        );
      })}
    </div>
  );
}
