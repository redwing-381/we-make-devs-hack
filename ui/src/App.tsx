import { useEffect, useState } from "react";
import { api } from "./api/client";
import { BrainPage } from "./pages/Brain";
import { DocsPage } from "./pages/Docs";
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
  docs: { label: "Adopt it", Page: DocsPage },
} as const;
type Tab = keyof typeof TABS;

// the tab lives in the URL hash (#docs, #memory, #docs/mcp), so any view can be linked to
const fromHash = (): Tab => {
  const t = window.location.hash.slice(1).split("/")[0];
  return t in TABS ? (t as Tab) : "incident";
};

export function App() {
  const [tab, setTab] = useState<Tab>(fromHash);
  const [db, setDb] = useState<{ text: string; up: boolean }>({ text: "Connecting…", up: true });

  useEffect(() => {
    const onHash = () => setTab(fromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => {
    api
      .health()
      .then((h) => setDb({ text: `${h.graph} · FalkorDB ${h.falkordb}`, up: h.falkordb === "up" }))
      .catch(() => setDb({ text: "API offline", up: false }));
  }, []);

  const go = (t: Tab) => {
    window.location.hash = t === "incident" ? "" : t;
    setTab(t);
    window.scrollTo({ top: 0 });
  };

  const { Page } = TABS[tab];
  return (
    <div className="app">
      <a className="skip" href="#content">
        Skip to content
      </a>
      <header className="topbar">
        <a className="brand" href="#" onClick={() => go("incident")} aria-label="Why-Graph home">
          <mark>Why</mark>-Graph
        </a>
        <nav className="nav" aria-label="Sections">
          {(Object.keys(TABS) as Tab[]).map((t) => (
            <button
              key={t}
              className={t === tab ? "tab active" : "tab"}
              aria-current={t === tab ? "page" : undefined}
              onClick={() => go(t)}
            >
              {TABS[t].label}
            </button>
          ))}
        </nav>
        <span className={db.up ? "status" : "status down"}>
          <i aria-hidden="true" />
          {db.text}
        </span>
      </header>
      <main id="content">
        <Page />
      </main>
    </div>
  );
}
