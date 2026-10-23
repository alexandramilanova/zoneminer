import { formatDuration } from "../lib/metricPresentation";
/** Two-column Sankey of inter-zone handovers (EXTENSIONS B3), hand-drawn SVG.
 *
 * Left = source zones, right = target zones; ribbon width is handover volume,
 * ribbon color follows the source zone (identity stays consistent with every
 * other view). Plotly's basic bundle has no sankey trace, and with at most
 * eight zones a purpose-built SVG stays small, theme-aware, and dependency-
 * free. Ribbons carry native tooltips; the table next to it is the
 * accessible view of the same numbers.
 */

import { useMemo } from "react";
import type { HandoverPair } from "../api";
import { useAppState } from "../state";
import { resolveColor } from "../lib/plot";

const W = 640;
const H = 340;
const NODE_W = 12;
const GAP = 10;
const PAD_Y = 12;
const LABEL_W = 170;

interface NodeLayout {
  zone: string;
  y: number;
  h: number;
  used: number; // running ribbon offset
}

function layoutNodes(totals: Map<string, number>, scale: number): Map<string, NodeLayout> {
  const zones = Array.from(totals.keys()).sort();
  const out = new Map<string, NodeLayout>();
  let y = PAD_Y;
  for (const z of zones) {
    const h = Math.max(2, (totals.get(z) ?? 0) * scale);
    out.set(z, { zone: z, y, h, used: 0 });
    y += h + GAP;
  }
  return out;
}

export default function HandoverSankey({ pairs }: { pairs: HandoverPair[] }) {
  const { zoneColor } = useAppState();

  const { left, right, ribbons } = useMemo(() => {
    const outTotals = new Map<string, number>();
    const inTotals = new Map<string, number>();
    for (const p of pairs) {
      outTotals.set(p.src, (outTotals.get(p.src) ?? 0) + p.count);
      inTotals.set(p.tgt, (inTotals.get(p.tgt) ?? 0) + p.count);
    }
    const usable = H - 2 * PAD_Y - GAP * Math.max(outTotals.size, inTotals.size, 1);
    const maxTotal = Math.max(
      Array.from(outTotals.values()).reduce((a, b) => a + b, 0),
      Array.from(inTotals.values()).reduce((a, b) => a + b, 0),
      1,
    );
    const scale = usable / maxTotal;
    const left = layoutNodes(outTotals, scale);
    const right = layoutNodes(inTotals, scale);

    // stable ribbon order: by source, then target (sorted) — matches node stacking
    const sorted = [...pairs].sort(
      (a, b) => a.src.localeCompare(b.src) || a.tgt.localeCompare(b.tgt),
    );
    const x0 = LABEL_W + NODE_W;
    const x1 = W - LABEL_W - NODE_W;
    const mid = (x0 + x1) / 2;
    const ribbons = sorted.map((p) => {
      const s = left.get(p.src)!;
      const t = right.get(p.tgt)!;
      const h = Math.max(1.5, p.count * scale);
      const sy = s.y + s.used;
      const ty = t.y + t.used;
      s.used += h;
      t.used += h;
      const d =
        `M ${x0} ${sy} C ${mid} ${sy}, ${mid} ${ty}, ${x1} ${ty} ` +
        `L ${x1} ${ty + h} C ${mid} ${ty + h}, ${mid} ${sy + h}, ${x0} ${sy + h} Z`;
      return { pair: p, d };
    });
    return { left, right, ribbons };
  }, [pairs]);

  const fmtDelay = formatDuration;

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      style={{ width: "100%", maxWidth: 760, height: "auto", display: "block" }}
      role="img"
      aria-label="Inter-zone handover flows"
    >
      {ribbons.map(({ pair, d }) => (
        <path key={`${pair.src}->${pair.tgt}`} d={d} fill={resolveColor(zoneColor(pair.src))} opacity={0.45}>
          <title>
            {`${pair.src} → ${pair.tgt}: ${pair.count.toLocaleString()} handovers, median delay ${fmtDelay(pair.median_delay_s)}`}
          </title>
        </path>
      ))}
      {Array.from(left.values()).map((n) => (
        <g key={`l-${n.zone}`}>
          <rect x={LABEL_W} y={n.y} width={NODE_W} height={n.h} rx={2} fill={resolveColor(zoneColor(n.zone))} />
          <text
            x={LABEL_W - 8}
            y={n.y + n.h / 2}
            textAnchor="end"
            dominantBaseline="middle"
            style={{ fontSize: 12, fill: "var(--text-2)" }}
          >
            {n.zone}
          </text>
        </g>
      ))}
      {Array.from(right.values()).map((n) => (
        <g key={`r-${n.zone}`}>
          <rect x={W - LABEL_W - NODE_W} y={n.y} width={NODE_W} height={n.h} rx={2} fill={resolveColor(zoneColor(n.zone))} />
          <text
            x={W - LABEL_W + 8}
            y={n.y + n.h / 2}
            dominantBaseline="middle"
            style={{ fontSize: 12, fill: "var(--text-2)" }}
          >
            {n.zone}
          </text>
        </g>
      ))}
    </svg>
  );
}
