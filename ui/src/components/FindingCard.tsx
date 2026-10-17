import type { Finding } from "../types/events";

interface Props {
  finding: Finding;
  selected: boolean;
  onSelect: (f: Finding) => void;
}

export function FindingCard({ finding, selected, onSelect }: Props) {
  return (
    <button className={`finding ${selected ? "selected" : ""}`} onClick={() => onSelect(finding)}>
      <div className="finding-head">
        <span className={`agent agent-${finding.agent}`}>{finding.agent}</span>
        <span className="confidence">{Math.round(finding.confidence * 100)}%</span>
      </div>
      <p>{finding.claim}</p>
      <div className="finding-foot">
        <code>{finding.query_id}</code> · {finding.evidence.nodes.length} nodes in path
      </div>
    </button>
  );
}
