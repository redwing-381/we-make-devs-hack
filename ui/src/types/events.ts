// Mirror of whygraph/models/events.py (the source of truth) — see docs/events.md.
// Changing this is a contract change: call it out in the PR.

export type AgentName = "orchestrator" | "triage" | "cause" | "memory" | "comms" | "brain" | "guard";

export type EventType =
  | "incident.opened"
  | "agent.started"
  | "agent.step"
  | "agent.finding"
  | "agent.handoff"
  | "agent.done"
  | "incident.resolved"
  | "memory.lesson_written"
  | "guard.checked";

export type Severity = "sev1" | "sev2" | "sev3";

export interface GraphNode {
  id: string; // stable id, e.g. "svc:checkout"
  label: string;
  name: string | null;
  props: Record<string, unknown>;
}

export interface GraphRel {
  id: string; // "<src>|<TYPE>|<dst>"
  type: string;
  src: string;
  dst: string;
  props: Record<string, unknown>;
}

export interface Subgraph {
  nodes: GraphNode[];
  rels: GraphRel[];
}

export interface AlertIn {
  id: string | null;
  service: string;
  signal: "error_rate" | "latency_p99" | "saturation" | "custom";
  value: number;
  threshold: number;
  severity: Severity;
  ts: number;
  source: string;
}

export interface DeployIn {
  sha: string;
  repo: string;
  services: string[];
  ts: number;
  pr_number: number | null;
  author: string | null;
  message: string | null;
  config_changes: ConfigChange[];
}

export interface Finding {
  id: string;
  agent: AgentName;
  claim: string;
  confidence: number;
  query_id: string;
  params: Record<string, unknown>;
  cypher: string | null;
  builds_on: string[];
  evidence: Subgraph;
}

export interface AgentEvent {
  seq: number;
  ts: number;
  incident_id: string;
  type: EventType;
  agent: AgentName | null;
  payload: Record<string, unknown>;
}

export interface StepPayload {
  tool: string;
  query_id: string;
  params: Record<string, unknown>;
  ms: number;
  summary: string;
}

export interface ConfigChange {
  service: string;
  key: string;
  old: number | string | null;
  new: number | string;
}

export interface RiskWarning {
  detector_id: string;
  lesson_id: string | null;
  lesson_text: string | null;
  incident_id: string | null;
  service: string;
  key: string;
  proposed: number | string;
  safe_min: number | null;
  evidence: Subgraph;
}

export interface ChangeRiskResponse {
  risk: "none" | "low" | "medium" | "high";
  warnings: RiskWarning[];
  advice: string;
}

export interface CatalogQuery {
  id: string;
  code: string;
  title: string;
  explain: string;
  cypher: string;
  example_params: Record<string, unknown>;
}

export interface QueryRunResult {
  query_id: string;
  rows: Record<string, unknown>[];
  subgraph: Subgraph;
  ms: number;
}
