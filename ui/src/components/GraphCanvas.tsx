import { useEffect, useMemo, useRef } from "react";
import "@falkordb/canvas";
import type FalkorDBCanvas from "@falkordb/canvas";
import { mergeGraphs } from "../api/client";
import type { Subgraph } from "../types/events";

export const LABEL_COLORS: Record<string, string> = {
  Service: "#3b82f6",
  Alert: "#ef4444",
  Incident: "#ec4899",
  Commit: "#f59e0b",
  PR: "#a855f7",
  Engineer: "#22c55e",
  ConfigKey: "#eab308",
  Deploy: "#14b8a6",
  Topic: "#06b6d4",
  Team: "#84cc16",
  Feature: "#94a3b8",
  Lesson: "#f97316",
  Decision: "#8b5cf6",
  Detector: "#0ea5e9",
  Runbook: "#64748b",
  FailurePattern: "#d946ef",
};

interface Props {
  graph: Subgraph;
  highlight?: Subgraph | null;
  height?: number;
}

const cssVar = (name: string, fallback: string) =>
  getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;

/** FalkorDB's own <falkordb-canvas>. The highlighted subgraph is drawn selected; everything else is dimmed. */
export function GraphCanvas({ graph, highlight, height = 460 }: Props) {
  const host = useRef<HTMLDivElement | null>(null);
  const canvas = useRef<FalkorDBCanvas | null>(null);
  const all = useMemo(() => mergeGraphs(graph, highlight), [graph, highlight]);
  const numeric = useMemo(() => new Map(all.nodes.map((n, i) => [n.id, i + 1])), [all]);
  const hiNodes = useMemo(() => new Set(highlight?.nodes.map((n) => n.id) ?? []), [highlight]);
  const hiRels = useMemo(() => new Set(highlight?.rels.map((r) => r.id) ?? []), [highlight]);

  useEffect(() => {
    if (!host.current || canvas.current) return;
    const el = document.createElement("falkordb-canvas") as FalkorDBCanvas;
    el.style.display = "block";
    el.style.width = "100%";
    el.style.height = "100%";
    host.current.appendChild(el);
    // base config before any data: captions are computed when data arrives
    el.setConfig({
      captionsKeys: ["name"],
      layoutMode: "force",
      backgroundColor: cssVar("--surface", "#ffffff"),
      foregroundColor: cssVar("--text", "#1d1d1b"),
      simulation: { chargeStrength: -260 },
      interaction: { zoomToFitMaxZoom: 4 },
      largeGraph: { enabled: false }, // our graphs are small; keep labels at every zoom level
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any);
    canvas.current = el;
    return () => {
      el.remove();
      canvas.current = null;
    };
  }, []);

  useEffect(() => {
    const el = canvas.current;
    if (!el) return;
    const nodes = all.nodes.map((n) => ({
      id: numeric.get(n.id)!,
      labels: [n.label],
      color: LABEL_COLORS[n.label] ?? "#9ca3af",
      size: n.label === "Service" ? 24 : 20, // labels are drawn inside the circle, so it must be big enough
      visible: true,
      data: { name: n.name ?? n.id.split(":").slice(1).join(":"), sid: n.id, ...n.props },
    }));
    const links = all.rels
      .filter((r) => numeric.has(r.src) && numeric.has(r.dst))
      .map((r, i) => ({
        id: i + 1,
        relationship: r.type,
        source: numeric.get(r.src)!,
        target: numeric.get(r.dst)!,
        color: "#9ca3af",
        visible: true,
        data: { sid: r.id, ...r.props },
      }));
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    el.setData({ nodes, links } as any);
    // fit once the force layout has spread out, then again when it has settled
    const timers = [700, 2200].map((ms) => setTimeout(() => el.zoomToFit?.(0.9), ms));
    return () => timers.forEach(clearTimeout);
  }, [all, numeric]);

  useEffect(() => {
    const el = canvas.current;
    if (!el) return;
    const on = hiNodes.size > 0;
    el.setConfig({
      dimmed: on,
      dimOpacity: 0.12,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      isNodeSelected: (n: any) => hiNodes.has(n.data?.sid),
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      isLinkSelected: (l: any) => hiRels.has(l.data?.sid),
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      isNodeDimmed: (n: any) => on && !hiNodes.has(n.data?.sid),
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      isLinkDimmed: (l: any) => on && !hiRels.has(l.data?.sid),
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any);
    // zoom onto the highlighted path so its labels are readable; back out to everything when cleared
    const t = setTimeout(
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      () => (on ? el.zoomToFit?.(0.8, (n: any) => hiNodes.has(n.data?.sid)) : el.zoomToFit?.(0.9)),
      150,
    );
    return () => clearTimeout(t);
  }, [hiNodes, hiRels]);

  const labels = [...new Set(all.nodes.map((n) => n.label))];
  return (
    <div className="canvas">
      <div className="canvas-meta">
        {all.nodes.length} nodes · {all.rels.length} edges
        {highlight && highlight.nodes.length > 0 ? ` · highlighting ${highlight.nodes.length} nodes` : ""}
      </div>
      <div ref={host} className="canvas-host" style={{ height }} />
      <div className="legend">
        {labels.map((l) => (
          <span key={l}>
            <i style={{ background: LABEL_COLORS[l] ?? "#9ca3af" }} /> {l}
          </span>
        ))}
      </div>
    </div>
  );
}
