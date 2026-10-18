import { useEffect, useMemo, useRef } from "react";
import "@falkordb/canvas";
import type FalkorDBCanvas from "@falkordb/canvas";
import { mergeGraphs } from "../api/client";
import type { Subgraph } from "../types/events";

/** Five families instead of a colour per label: what a reader needs to tell apart at a glance. */
type Group = "service" | "signal" | "change" | "people" | "memory";
const GROUP_OF: Record<string, Group> = {
  Service: "service",
  Topic: "service",
  Alert: "signal",
  Incident: "signal",
  Commit: "change",
  PR: "change",
  ConfigKey: "change",
  Deploy: "change",
  File: "change",
  Engineer: "people",
  Team: "people",
  Lesson: "memory",
  Decision: "memory",
  Detector: "memory",
  FailurePattern: "memory",
  Feature: "memory",
  Runbook: "memory",
  Finding: "memory",
  Investigation: "memory",
};
export const GROUPS: { key: Group; label: string }[] = [
  { key: "service", label: "Services" },
  { key: "signal", label: "Alerts and incidents" },
  { key: "change", label: "Changes" },
  { key: "people", label: "People" },
  { key: "memory", label: "Memory" },
];
const groupOf = (label: string): Group => GROUP_OF[label] ?? "memory";

interface Props {
  graph: Subgraph;
  highlight?: Subgraph | null;
  height?: number;
}

type Tokens = Record<"sunk" | "ink" | "ink3" | "mark" | "onMark" | "edge" | Group, string>;
const readTokens = (): Tokens => {
  const css = getComputedStyle(document.documentElement);
  const v = (n: string, f: string) => css.getPropertyValue(n).trim() || f;
  return {
    sunk: v("--sunk", "#0b0d0c"),
    ink: v("--ink", "#e8ece9"),
    ink3: v("--ink-3", "#6f7974"),
    mark: v("--mark", "#e6d34e"),
    onMark: v("--on-mark", "#121410"),
    edge: v("--edge", "#59625d"),
    service: v("--ink-2", "#a5aea9"),
    signal: v("--danger", "#ec7363"),
    change: v("--warn", "#e2a64f"),
    people: v("--ok", "#7fbf8d"),
    memory: v("--memory", "#79aadd"),
  };
};

const FONT = '"Geist", ui-sans-serif, system-ui, sans-serif';
const MONO = '"Geist Mono", ui-monospace, monospace';
const short = (s: string, n = 24) => (s.length > n ? `${s.slice(0, n - 1)}…` : s);

/* eslint-disable @typescript-eslint/no-explicit-any */
/** FalkorDB's own <falkordb-canvas>, drawn in the console's style: a shape per family, labels set beside the
 *  node, and the evidence path marked like a highlighter stroke while everything else steps back. */
export function GraphCanvas({ graph, highlight, height = 460 }: Props) {
  const host = useRef<HTMLDivElement | null>(null);
  const canvas = useRef<FalkorDBCanvas | null>(null);
  const all = useMemo(() => mergeGraphs(graph, highlight), [graph, highlight]);
  const numeric = useMemo(() => new Map(all.nodes.map((n, i) => [n.id, i + 1])), [all]);
  const hiNodes = useMemo(() => new Set(highlight?.nodes.map((n) => n.id) ?? []), [highlight]);
  const hiRels = useMemo(() => new Set(highlight?.rels.map((r) => r.id) ?? []), [highlight]);
  // the draw callbacks are installed once; they read the current selection and theme through refs
  const sel = useRef({ nodes: hiNodes, rels: hiRels });
  sel.current = { nodes: hiNodes, rels: hiRels };
  const tokens = useRef<Tokens>(readTokens());

  useEffect(() => {
    if (!host.current || canvas.current) return;
    const el = document.createElement("falkordb-canvas") as FalkorDBCanvas;
    el.style.display = "block";
    el.style.width = "100%";
    el.style.height = "100%";
    host.current.appendChild(el);
    const t = tokens.current;

    const radius = (n: any) => (groupOf(n.labels?.[0]) === "service" ? 9 : 7);
    const lit = (n: any) => sel.current.nodes.has(n.data?.sid);
    const focus = () => sel.current.nodes.size > 0;

    const drawNode = (n: any, ctx: CanvasRenderingContext2D) => {
      const T = tokens.current;
      const g = groupOf(n.labels?.[0]);
      const r = radius(n);
      const on = lit(n);
      ctx.save();
      ctx.globalAlpha = focus() && !on ? 0.16 : 1;
      if (on) {
        ctx.beginPath();
        ctx.arc(n.x, n.y, r + 3.6, 0, 2 * Math.PI);
        ctx.fillStyle = T.mark;
        ctx.fill();
      }
      ctx.beginPath();
      if (g === "change") {
        ctx.rect(n.x - r * 0.85, n.y - r * 0.85, r * 1.7, r * 1.7);
      } else if (g === "signal") {
        ctx.moveTo(n.x, n.y - r * 1.15);
        ctx.lineTo(n.x + r * 1.15, n.y);
        ctx.lineTo(n.x, n.y + r * 1.15);
        ctx.lineTo(n.x - r * 1.15, n.y);
        ctx.closePath();
      } else if (g === "memory") {
        ctx.rect(n.x - r * 0.7, n.y - r * 0.7, r * 1.4, r * 1.4);
      } else {
        ctx.arc(n.x, n.y, r, 0, 2 * Math.PI);
      }
      if (g === "people" || g === "memory") {
        ctx.fillStyle = T.sunk;
        ctx.fill();
        ctx.lineWidth = 2.4;
        ctx.strokeStyle = T[g];
        ctx.stroke();
      } else {
        ctx.fillStyle = T[g];
        ctx.fill();
      }
      // label beside the node: the name, and its kind underneath in the quiet ink
      const name = short(String(n.data?.name ?? ""));
      const x = n.x + r + 5;
      ctx.textBaseline = "middle";
      ctx.textAlign = "left";
      ctx.font = `${on ? 600 : 500} 7.5px ${FONT}`;
      if (on) {
        ctx.fillStyle = T.mark;
        ctx.fillRect(x - 2, n.y - 6, ctx.measureText(name).width + 4, 9.2);
      }
      ctx.fillStyle = on ? T.onMark : T.ink;
      ctx.fillText(name, x, n.y - 1.4);
      ctx.font = `400 5.2px ${FONT}`;
      ctx.fillStyle = T.ink3;
      ctx.fillText(n.labels?.[0] ?? "", x, n.y + 7.4);
      ctx.restore();
    };

    const paintNodeArea = (n: any, color: string, ctx: CanvasRenderingContext2D) => {
      const r = radius(n) + 2;
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.arc(n.x, n.y, r, 0, 2 * Math.PI);
      ctx.fill();
      ctx.fillRect(n.x, n.y - 7, r + 5 + short(String(n.data?.name ?? "")).length * 4, 15);
    };

    const drawLink = (l: any, ctx: CanvasRenderingContext2D, scale: number) => {
      const T = tokens.current;
      const s = l.source;
      const d = l.target;
      if (s?.x == null || d?.x == null) return;
      const on = sel.current.rels.has(l.data?.sid);
      const dx = d.x - s.x;
      const dy = d.y - s.y;
      const len = Math.hypot(dx, dy) || 1;
      const ux = dx / len;
      const uy = dy / len;
      const end = radius(d) + (lit(d) ? 5 : 2.4);
      const tx = d.x - ux * end;
      const ty = d.y - uy * end;
      ctx.save();
      ctx.globalAlpha = focus() && !on ? 0.12 : 1;
      ctx.strokeStyle = on ? T.mark : T.edge;
      ctx.lineWidth = on ? 3.4 : Math.max(0.8, 1.2 / scale);
      ctx.beginPath();
      ctx.moveTo(s.x + ux * radius(s), s.y + uy * radius(s));
      ctx.lineTo(tx, ty);
      ctx.stroke();
      const a = on ? 6 : 4.2;
      ctx.fillStyle = on ? T.mark : T.edge;
      ctx.beginPath();
      ctx.moveTo(tx, ty);
      ctx.lineTo(tx - ux * a - uy * a * 0.55, ty - uy * a + ux * a * 0.55);
      ctx.lineTo(tx - ux * a + uy * a * 0.55, ty - uy * a - ux * a * 0.55);
      ctx.closePath();
      ctx.fill();
      if (on) {
        // the relationship name sits on the stroke, so the path reads as a sentence
        const mx = (s.x + d.x) / 2;
        const my = (s.y + d.y) / 2;
        const text = String(l.relationship ?? "");
        ctx.font = `500 5px ${MONO}`;
        const w = ctx.measureText(text).width;
        ctx.fillStyle = T.sunk;
        ctx.fillRect(mx - w / 2 - 2, my - 4, w + 4, 8);
        ctx.fillStyle = T.ink;
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(text, mx, my + 0.1);
      }
      ctx.restore();
    };

    const paintLinkArea = (l: any, color: string, ctx: CanvasRenderingContext2D) => {
      if (l.source?.x == null || l.target?.x == null) return;
      ctx.strokeStyle = color;
      ctx.lineWidth = 6;
      ctx.beginPath();
      ctx.moveTo(l.source.x, l.source.y);
      ctx.lineTo(l.target.x, l.target.y);
      ctx.stroke();
    };

    // base config before any data: the custom drawing replaces the default circles and labels
    el.setConfig({
      captionsKeys: ["name"],
      layoutMode: "force",
      layoutOptions: { force: { linkDistance: 46, collisionPadding: 34 } },
      backgroundColor: t.sunk,
      foregroundColor: t.ink,
      simulation: { chargeStrength: -180, centerStrength: 0.08 },
      interaction: { zoomToFitMaxZoom: 4.5, zoomToFitPadding: 0.08 },
      largeGraph: { enabled: false }, // our graphs are small; keep labels at every zoom level
      node: { nodeCanvasObject: drawNode, nodePointerAreaPaint: paintNodeArea },
      link: { linkCanvasObject: drawLink, linkPointerAreaPaint: paintLinkArea },
    } as any);
    canvas.current = el;

    // follow the app between light and dark
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const retheme = () => {
      tokens.current = readTokens();
      el.setConfig({ backgroundColor: tokens.current.sunk, foregroundColor: tokens.current.ink } as any);
    };
    mq.addEventListener("change", retheme);
    return () => {
      mq.removeEventListener("change", retheme);
      el.remove();
      canvas.current = null;
    };
  }, []);

  const shape = useRef("");
  useEffect(() => {
    const el = canvas.current;
    if (!el) return;
    // selecting a finding only re-highlights; reloading the same nodes would restart the layout
    const key = `${all.nodes.map((n) => n.id).join("|")}#${all.rels.map((r) => r.id).join("|")}`;
    if (key === shape.current) return;
    shape.current = key;
    const nodes = all.nodes.map((n) => ({
      id: numeric.get(n.id)!,
      labels: [n.label],
      color: tokens.current[groupOf(n.label)],
      size: groupOf(n.label) === "service" ? 10 : 8,
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
        color: tokens.current.edge,
        visible: true,
        data: { sid: r.id, ...r.props },
      }));
    el.setData({ nodes, links } as any);
    // fit once the force layout has spread out, then again when it has settled
    const fit = () =>
      sel.current.nodes.size > 0
        ? el.zoomToFit?.(0.8, (n: any) => sel.current.nodes.has(n.data?.sid))
        : el.zoomToFit?.(0.9);
    const timers = [700, 2200].map((ms) => setTimeout(fit, ms));
    return () => timers.forEach(clearTimeout);
  }, [all, numeric]);

  useEffect(() => {
    const el = canvas.current;
    if (!el) return;
    const on = hiNodes.size > 0;
    // the predicates also make the canvas repaint, so the custom drawing picks up the new selection
    el.setConfig({
      isNodeSelected: (n: any) => hiNodes.has(n.data?.sid),
      isLinkSelected: (l: any) => hiRels.has(l.data?.sid),
    } as any);
    // zoom onto the highlighted path so its labels are readable; back out to everything when cleared
    const t = setTimeout(
      () => (on ? el.zoomToFit?.(0.8, (n: any) => hiNodes.has(n.data?.sid)) : el.zoomToFit?.(0.9)),
      150,
    );
    return () => clearTimeout(t);
  }, [hiNodes, hiRels]);

  const groups = new Set(all.nodes.map((n) => groupOf(n.label)));
  const byId = new Map(all.nodes.map((n) => [n.id, n]));
  const nameOf = (id: string) => byId.get(id)?.name ?? id.split(":").slice(1).join(":");
  const path = highlight?.rels.filter((r) => byId.has(r.src) && byId.has(r.dst)) ?? [];

  return (
    <div className="canvas">
      <div className="canvas-meta">
        <span className="num">
          {all.nodes.length} nodes · {all.rels.length} edges
        </span>
        {highlight && highlight.nodes.length > 0 ? (
          <span className="hi">Evidence path: {highlight.nodes.length} nodes</span>
        ) : (
          <span>Pick a finding or a source to light up its path</span>
        )}
      </div>
      <div ref={host} className="canvas-host" style={{ height }} />
      {path.length > 0 ? (
        <ol className="path-strip" aria-label="Evidence path">
          {path.map((r) => (
            <li key={r.id}>
              <span className="n">{short(nameOf(r.src), 28)}</span>
              <span className="r">{r.type}</span>
              <span className="n">{short(nameOf(r.dst), 28)}</span>
            </li>
          ))}
        </ol>
      ) : (
        <div className="legend">
          {GROUPS.filter((g) => groups.has(g.key)).map((g) => (
            <span key={g.key} className={`lg lg-${g.key}`}>
              <i aria-hidden="true" /> {g.label}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
