import type { DecisionTreeView } from "../api";

/** Render exact fitted nodes, with an accessible table retaining full thresholds. */
export default function DecisionTree({ tree, weighted = false }: { tree: DecisionTreeView; weighted?: boolean }) {
  const nodes = new Map(tree.nodes.map(n => [n.id, n]));
  const positions = new Map<number, { x: number; y: number }>();
  let leaves = 0, depth = 0;
  function place(id: number, level: number): number {
    const node = nodes.get(id)!;
    depth = Math.max(depth, level);
    const x = node.left === null || node.right === null ? (leaves++ * 300 + 150)
      : (place(node.left, level + 1) + place(node.right, level + 1)) / 2;
    positions.set(id, { x, y: level * 170 + 65 });
    return x;
  }
  if (!nodes.has(0)) return <p>Decision tree unavailable.</p>;
  place(0, 0);
  const width = Math.max(600, leaves * 300), height = depth * 170 + 140;
  const shareLabel = weighted ? 'Weighted class 1 share' : 'Class 1 share';
  const label = (n: DecisionTreeView['nodes'][number]) => n.feature === null
    ? `Threshold ${n.predicted_class === 1 ? "met" : "not met"} (${n.predicted_class})`
    : `${n.feature} ≤ ${n.threshold!.toPrecision(5)}`;
  return <div data-testid="decision-tree">
    <h3>Fitted decision tree</h3>
    <p className="help">Final fitted model, not a cross-validation fold. Follow Yes for ≤ and No for &gt;. Leaf classes refer to the chosen target condition. Node shares describe training samples, not calibrated future probabilities. Missing inputs use the fitted median imputer.</p>
    {weighted && <p className="help">Class shares use balanced training weights; sample counts are unweighted observations. A weighted share is not the observed frequency of the condition.</p>}
    <div role="region" aria-label="Decision tree diagram, scroll horizontally if needed" tabIndex={0} style={{ overflowX: "auto" }}>
      <svg role="img" aria-label="Fitted decision tree with Yes and No branches" width={width} height={height} style={{ display: "block", margin: "auto" }}>
        {tree.nodes.flatMap(n => [n.left, n.right].map((child, side) => {
          if (child === null) return null;
          const a = positions.get(n.id)!, b = positions.get(child)!;
          return <g key={`${n.id}-${child}`}><line x1={a.x} y1={a.y + 52} x2={b.x} y2={b.y - 52} stroke="var(--muted)" />
            <text x={(a.x + b.x) / 2} y={(a.y + b.y) / 2} textAnchor="middle" fill="var(--text)" fontSize={12}>{side === 0 ? "Yes" : "No"}</text></g>;
        }))}
        {tree.nodes.map(n => {
          const p = positions.get(n.id)!;
          const lines = n.feature === null ? [label(n)] : [
            ...(n.feature.match(/.{1,38}/g) ?? []).slice(0, 2),
            `≤ ${Number(n.threshold!.toPrecision(5))}`,
          ];
          return <g key={n.id}><title>{label(n)}; {n.samples} training samples; {shareLabel} {(n.positive_share * 100).toFixed(1)}%</title>
            <rect x={p.x - 142} y={p.y - 52} width={284} height={104} rx={8} fill="var(--surface)" stroke="var(--accent)" />
            <text x={p.x} y={p.y - 27} textAnchor="middle" fill="var(--text)" fontSize={11}>
              {lines.slice(0, 3).map((line, i) => <tspan key={i} x={p.x} dy={i ? 14 : 0}>{line}</tspan>)}
              <tspan x={p.x} y={p.y + 25}>{n.samples} samples · {weighted ? 'weighted class 1' : 'class 1'}: {(n.positive_share * 100).toFixed(1)}%</tspan>
            </text></g>;
        })}
      </svg>
    </div>
    <details><summary>Accessible tree rules and exact thresholds</summary><table>
      <thead><tr>{['Node', 'Condition', 'Yes → node', 'No → node', 'Samples', shareLabel].map(h => <th key={h}>{h}</th>)}</tr></thead>
      <tbody>{tree.nodes.map(n => <tr key={n.id}><td>{n.id}</td><td>{n.feature === null ? label(n) : `${n.feature} ≤ ${n.threshold}`}</td><td>{n.left ?? '—'}</td><td>{n.right ?? '—'}</td><td>{n.samples}</td><td>{(n.positive_share * 100).toFixed(1)}%</td></tr>)}</tbody>
    </table></details>
  </div>;
}
