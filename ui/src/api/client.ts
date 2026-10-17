import type { AgentEvent, CatalogQuery, QueryRunResult } from "../types/events";

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}: ${await res.text()}`);
  return res.json() as Promise<T>;
}

export const api = {
  health: () => fetch("/api/health").then(json<{ status: string; falkordb: string; graph: string }>),
  queries: () => fetch("/api/queries").then(json<CatalogQuery[]>),
  runQuery: (query_id: string, params: Record<string, unknown>, graph?: string) =>
    fetch("/api/query/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query_id, params, graph }),
    }).then(json<QueryRunResult>),
  recordings: () => fetch("/api/replay").then(json<string[]>),
};

/** SSE URL for a live incident or a recorded replay — both emit the same AgentEvent stream. */
export const streamUrl = {
  incident: (id: string) => `/api/incidents/${encodeURIComponent(id)}/stream`,
  replay: (name: string, speed = 2) => `/api/replay/${encodeURIComponent(name)}/stream?speed=${speed}`,
};

export function subscribe(url: string, onEvent: (e: AgentEvent) => void, onEnd?: () => void): () => void {
  const es = new EventSource(url);
  es.onmessage = (m) => onEvent(JSON.parse(m.data) as AgentEvent);
  es.addEventListener("end", () => {
    es.close();
    onEnd?.();
  });
  es.onerror = () => {
    es.close();
    onEnd?.();
  };
  return () => es.close();
}
