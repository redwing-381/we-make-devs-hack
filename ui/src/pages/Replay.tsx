import { useEffect, useState } from "react";
import { api, streamUrl } from "../api/client";
import { IncidentView } from "../components/IncidentView";

export function ReplayPage() {
  const [names, setNames] = useState<string[]>([]);
  const [name, setName] = useState("act1-fixture");
  const [speed, setSpeed] = useState(2);
  const [playing, setPlaying] = useState(false);

  useEffect(() => {
    api
      .recordings()
      .then((n) => setNames(n.length ? n : ["act1-fixture"]))
      .catch(() => setNames(["act1-fixture"]));
  }, []);

  return (
    <div>
      <div className="picker">
        <label>
          Recording{" "}
          <select value={name} onChange={(e) => (setName(e.target.value), setPlaying(false))}>
            {names.map((n) => (
              <option key={n}>{n}</option>
            ))}
          </select>
        </label>
        <label>
          Speed{" "}
          <select value={speed} onChange={(e) => (setSpeed(Number(e.target.value)), setPlaying(false))}>
            {[1, 2, 4].map((s) => (
              <option key={s} value={s}>
                {s}×
              </option>
            ))}
          </select>
        </label>
        <button className="primary" onClick={() => setPlaying(true)}>
          Play
        </button>
      </div>
      {playing && <IncidentView key={`${name}-${speed}`} url={streamUrl.replay(name, speed)} />}
    </div>
  );
}
