import type { AgentEvent, CatalogQuery, ChangeRiskResponse, ConfigChange, Finding, QueryRunResult, Subgraph } from "../types/events";

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(`${res.status}: ${(await res.text()).slice(0, 300)}`);
  return res.json() as Promise<T>;
}
const get = <T,>(url: string) => fetch(url).then(json<T>);
const post = <T,>(url: string, body: unknown) =>
  fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).then(json<T>);
const q = (graph?: string) => (graph ? `?graph=${encodeURIComponent(graph)}` : "");

export interface IncidentSummary {
  id: string;
  title: string;
  status: string;
  severity: string;
  started_at: number | null;
}

export interface Lesson {
  id: string;
  text: string;
  confidence: number | null;
  uses: number | null;
  prevented: number | null;
  status: string | null;
  source: string | null;
  incident: string | null;
  pattern: string | null;
  detectors: string[];
  outcomes: { pr: number; outcome: string }[];
}

export interface Detector {
  id: string;
  template: string;
  status: string | null;
  source: string | null;
  backtest_hits: number | null;
  backtest_total: number | null;
  pattern: string | null;
  cypher: string | null;
}

export interface MemoryState {
  types: Record<"episodic" | "semantic" | "procedural", Record<string, number>>;
  lessons: Lesson[];
  detectors: Detector[];
}

export interface GuardPR {
  number: number;
  title: string | null;
  url: string | null;
  state: string | null;
  author: string | null;
  author_kind: string | null;
  outcomes: { lesson: string; outcome: string }[];
}

export interface BrainAnswer {
  answer: string;
  sources: string[];
  evidence: Subgraph;
  findings: Finding[];
  steps: { tool: string; query_id: string; ms: number; summary: string }[];
  graph_only: boolean;
}

export interface ResolveResult {
  root_cause_finding_id: string;
  caused_by: string | null;
  lesson: { lesson?: { id: string; text: string; confidence: number }; detector?: Record<string, unknown> } | null;
  lesson_pending: boolean;
}

export const api = {
  health: () => get<{ status: string; falkordb: string; graph: string; graph_only: boolean }>("/api/health"),
  queries: () => get<CatalogQuery[]>("/api/queries"),
  runQuery: (query_id: string, params: Record<string, unknown>, graph?: string) =>
    post<QueryRunResult>("/api/query/run", { query_id, params, graph }),
  recordings: () => get<string[]>("/api/replay"),
  incidents: () => get<IncidentSummary[]>("/api/incidents"),
  investigate: (id: string) => post<{ started: boolean }>(`/api/incidents/${encodeURIComponent(id)}/investigate`, {}),
  resolve: (id: string, fix: string, resolved_by?: string) =>
    post<ResolveResult>(`/api/incidents/${encodeURIComponent(id)}/resolve`, { fix, resolved_by }),
  guardCheck: (changes: ConfigChange[], graph?: string, title?: string) =>
    post<ChangeRiskResponse>(`/api/guard/check${q(graph)}`, { changes, title }),
  guardPrs: (graph?: string) => get<GuardPR[]>(`/api/guard/prs${q(graph)}`),
  memory: (graph?: string) => get<MemoryState>(`/api/memory${q(graph)}`),
  ask: (question: string, graph_only: boolean) => post<BrainAnswer>("/api/brain/ask", { question, graph_only }),
};

const path = (name: string) => name.split("/").map(encodeURIComponent).join("/");

/** SSE URL for a live incident or a recorded replay — both emit the same AgentEvent stream. */
export const streamUrl = {
  incident: (id: string) => `/api/incidents/${encodeURIComponent(id)}/stream`,
  replay: (name: string, speed = 2) => `/api/replay/${path(name)}/stream?speed=${speed}`,
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

/** Union of subgraphs, de-duplicated by id. */
export function mergeGraphs(...graphs: (Subgraph | null | undefined)[]): Subgraph {
  const nodes = new Map<string, Subgraph["nodes"][number]>();
  const rels = new Map<string, Subgraph["rels"][number]>();
  for (const g of graphs) {
    g?.nodes.forEach((n) => nodes.set(n.id, n));
    g?.rels.forEach((r) => rels.set(r.id, r));
  }
  return { nodes: [...nodes.values()], rels: [...rels.values()] };
}
