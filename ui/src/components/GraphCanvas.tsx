import type { Subgraph } from "../types/events";

interface Props {
  graph: Subgraph;
  highlight?: Subgraph | null;
}

/**
 * Placeholder graph view: renders the highlighted evidence as an ordered list of hops.
 * F-C1 (feat/ui-incident) replaces this with <falkordb-canvas> (`@falkordb/canvas`, tree layout) —
 * keep the same props so pages don't change.
 */
export function GraphCanvas({ graph, highlight }: Props) {
  const shown = highlight ?? graph;
  const name = (id: string) => shown.nodes.find((n) => n.id === id)?.name ?? id;
  return (
    <div className="canvas">
      <div className="canvas-meta">
        {graph.nodes.length} nodes · {graph.rels.length} edges in this investigation
        {highlight ? ` · highlighting ${highlight.nodes.length} nodes` : ""}
      </div>
      <ol className="hops">
        {shown.rels.map((r) => (
          <li key={r.id}>
            <code>{name(r.src)}</code> <span className="rel">-[{r.type}]→</span> <code>{name(r.dst)}</code>
            {Object.keys(r.props).length > 0 && <span className="props"> {JSON.stringify(r.props)}</span>}
          </li>
        ))}
      </ol>
    </div>
  );
}
