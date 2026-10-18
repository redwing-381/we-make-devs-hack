import { useEffect, useState } from "react";
import { api, streamUrl, type IncidentSummary } from "../api/client";
import { IncidentView } from "../components/IncidentView";

const FIXTURE = "replay:act1-fixture";

/** Live incidents (newest first), or the recorded Act 1 fixture when the API has none. */
export function IncidentPage() {
  const [incidents, setIncidents] = useState<IncidentSummary[]>([]);
  const [choice, setChoice] = useState<string | null>(null);
  const [offline, setOffline] = useState(false);

  useEffect(() => {
    let alive = true;
    const load = () =>
      api
        .incidents()
        .then((list) => {
          if (!alive) return;
          setOffline(false);
          // only incidents the agents have touched (not the seeded history), newest first
          const live = list.filter((i) => i.status === "open" || Number(i.id.replace(/\D/g, "")) >= 1031);
          setIncidents(live);
          setChoice((c) => c ?? (live[0] ? live[0].id : FIXTURE));
        })
        .catch(() => {
          if (!alive) return;
          setOffline(true);
          setChoice((c) => c ?? FIXTURE);
        });
    load();
    const t = setInterval(load, 5000); // new incidents appear as alerts arrive
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  if (!choice) return <p className="muted">Loading…</p>;
  const isFixture = choice === FIXTURE;
  return (
    <div>
      <div className="picker">
        <label>
          Incident
          <select value={choice} onChange={(e) => setChoice(e.target.value)}>
            {incidents.map((i) => (
              <option key={i.id} value={i.id}>
                {i.id} · {i.title} · {i.status}
              </option>
            ))}
            <option value={FIXTURE}>Recorded run: Act 1 (fixture)</option>
          </select>
        </label>
        {offline && <span className="muted">The API is unreachable, so this is the recording</span>}
        {!offline && incidents.length === 0 && (
          <span className="muted">No live incident yet. Merge a change and alerts open one here.</span>
        )}
      </div>
      <IncidentView
        key={choice}
        url={isFixture ? streamUrl.replay("act1-fixture", 4) : streamUrl.incident(choice)}
        incidentId={isFixture ? undefined : choice}
      />
    </div>
  );
}
