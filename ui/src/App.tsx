import { useEffect, useState } from "react";
import { api } from "./api/client";
import { BrainPage } from "./pages/Brain";
import { IncidentPage } from "./pages/Incident";
import { MemoryPage } from "./pages/Memory";
import { PRGuardPage } from "./pages/PRGuard";
import { ReplayPage } from "./pages/Replay";

// Every tab is wired here up front so feature PRs only touch their own page file.
const TABS = {
  incident: { label: "Incident", Page: IncidentPage },
  guard: { label: "PR Guard", Page: PRGuardPage },
  memory: { label: "Memory", Page: MemoryPage },
  brain: { label: "Brain", Page: BrainPage },
  replay: { label: "Replay", Page: ReplayPage },
} as const;
type Tab = keyof typeof TABS;

export function App() {
  const [tab, setTab] = useState<Tab>("incident");
  const [db, setDb] = useState<string>("…");

  useEffect(() => {
    api
      .health()
      .then((h) => setDb(`${h.graph} · FalkorDB ${h.falkordb}`))
      .catch(() => setDb("API offline"));
  }, []);

  const { Page } = TABS[tab];
  return (
    <div className="app">
      <nav className="topbar">
        <strong className="brand">Why-Graph</strong>
        {(Object.keys(TABS) as Tab[]).map((t) => (
          <button key={t} className={t === tab ? "tab active" : "tab"} onClick={() => setTab(t)}>
            {TABS[t].label}
          </button>
        ))}
        <span className="status muted">{db}</span>
      </nav>
      <main>
        <Page />
      </main>
    </div>
  );
}
