/** Zone-graph abstraction: the process collapsed to one node
 * per zone. Node size = tokens currently in the zone, node color = the zone's
 * identity color, halo = current bottleneck state (labeled in the legend and
 * tooltip — color is never the sole encoding). Edges = handover volume.
 * Layout is a simple left-to-right layering of the handover digraph
 * (cycle-safe), hand-drawn SVG like the Sankey.
 */

import { useMemo } from "react";
import type { BottleneckState, HandoverPair } from "../api";
import { useAppState } from "../state";
import { resolveColor } from "../lib/plot";
import { STATE_STYLE } from "../lib/states";

const W = 860;
const H = 320;
const PAD_X = 90;
const PAD_Y = 46;

function layerZones(zones: string[], pairs: HandoverPair[]): Map<string, number> {
  const indeg = new Map<string, number>(zones.map((z) => [z, 0]));
  const out = new Map<string, string[]>();
  for (const p of pairs) {
    if (!indeg.has(p.src) || !indeg.has(p.tgt)) continue;
    indeg.set(p.tgt, (indeg.get(p.tgt) ?? 0) + 1);
    out.set(p.src, [...(out.get(p.src) ?? []), p.tgt]);
  }
  const layer = new Map<string, number>();
  let frontier = zones.filter((z) => (indeg.get(z) ?? 0) === 0);
  let depth = 0;
  const remaining = new Set(zones);
  while (remaining.size) {
    if (!frontier.length) {
      // cycle: place everything left on the next layer
      frontier = Array.from(remaining);
    }
    for (const z of frontier) {
      layer.set(z, depth);
      remaining.delete(z);
    }
    const next = new Set<string>();
    for (const z of frontier) {
      for (const t of out.get(z) ?? []) {
        if (remaining.has(t)) next.add(t);
      }
    }
    frontier = Array.from(next);
    depth++;
  }
  return layer;
}

export default function ZoneGraph({
  loads,
  pairs,
  states,
}: {
  loads: Map<string, { tokens: number; cases: number }>;
  pairs: HandoverPair[];
  states: Map<string, BottleneckState>;
}) {
  const { zones, zoneColor } = useAppState();

  const { nodes, edges } = useMemo(() => {
    const layers = layerZones(zones, pairs);
    const maxLayer = Math.max(0, ...layers.values());
    const byLayer = new Map<number, string[]>();
    for (const z of zones) {
      const l = layers.get(z) ?? 0;
      byLayer.set(l, [...(byLayer.get(l) ?? []), z]);
    }
    const maxLoad = Math.max(1, ...zones.map((z) => loads.get(z)?.tokens ?? 0));
    const nodes = new Map<string, { x: number; y: number; r: number; tokens: number }>();
    for (const [l, zs] of byLayer) {
      const x = maxLayer === 0 ? W / 2 : PAD_X + (l * (W - 2 * PAD_X)) / maxLayer;
      zs.sort().forEach((z, i) => {
        const y = PAD_Y + ((i + 1) * (H - 2 * PAD_Y)) / (zs.length + 1);
        const tokens = loads.get(z)?.tokens ?? 0;
        const r = 13 + 24 * Math.sqrt(tokens / maxLoad);
        nodes.set(z, { x, y, r, tokens });
      });
    }
    const maxCount = Math.max(1, ...pairs.map((p) => p.count));
    const edges = pairs
      .filter((p) => nodes.has(p.src) && nodes.has(p.tgt))
      .map((p) => {
        const s = nodes.get(p.src)!;
        const t = nodes.get(p.tgt)!;
        const midX = (s.x + t.x) / 2;
        return {
          pair: p,
          d: `M ${s.x + s.r} ${s.y} C ${midX} ${s.y}, ${midX} ${t.y}, ${t.x - t.r - 4} ${t.y}`,
          width: 1.5 + 8 * (p.count / maxCount),
        };
      });
    return { nodes, edges };
  }, [zones, pairs, loads]);

  return (
    <div>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        style={{ width: "100%", maxWidth: 980, height: "auto", display: "block" }}
        role="img"
        aria-label="Zone flow map"
      >
        <defs>
          <marker
            id="zg-arrow"
            viewBox="0 0 8 8"
            refX="7"
            refY="4"
            markerWidth="9"
            markerHeight="9"
            markerUnits="userSpaceOnUse"
            orient="auto"
          >
            <path d="M 0 0 L 8 4 L 0 8 z" fill="var(--muted)" />
          </marker>
        </defs>
        {edges.map(({ pair, d, width }) => (
          <path
            key={`${pair.src}->${pair.tgt}`}
            d={d}
            fill="none"
            stroke={resolveColor(zoneColor(pair.src))}
            strokeWidth={width}
            opacity={0.4}
            markerEnd="url(#zg-arrow)"
          >
            <title>{`${pair.src} → ${pair.tgt}: ${pair.count.toLocaleString()} handovers`}</title>
          </path>
        ))}
        {Array.from(nodes.entries()).map(([z, n]) => {
          const state = states.get(z) ?? "flowing";
          return (
            <g key={z}>
              <circle
                cx={n.x}
                cy={n.y}
                r={n.r + 4}
                fill="none"
                stroke={state === "flowing" ? "transparent" : STATE_STYLE[state].color}
                strokeWidth={4}
              />
              <circle cx={n.x} cy={n.y} r={n.r} fill={resolveColor(zoneColor(z))} opacity={0.9}>
                <title>{`${z}: ${n.tokens.toLocaleString()} tokens now — ${STATE_STYLE[state].label}`}</title>
              </circle>
              <text
                x={n.x}
                y={n.y + n.r + 16}
                textAnchor="middle"
                style={{ fontSize: 12, fill: "var(--text-2)" }}
              >
                {z}
              </text>
              <text
                x={n.x}
                y={n.y + 4}
                textAnchor="middle"
                style={{ fontSize: 11, fontWeight: 700, fill: "var(--accent-ink)" }}
              >
                {n.tokens.toLocaleString()}
              </text>
            </g>
          );
        })}
      </svg>
      <div className="row" style={{ marginTop: 6, gap: 14, flexWrap: "wrap" }}>
        <span className="help">node size = tokens in zone now · edge width = handover volume · halo = state:</span>
        {(Object.keys(STATE_STYLE) as BottleneckState[])
          .filter((s) => s !== "flowing")
          .map((s) => (
            <span key={s} className="help row" style={{ gap: 5 }}>
              <span
                style={{
                  width: 12,
                  height: 12,
                  borderRadius: "50%",
                  border: `3px solid ${STATE_STYLE[s].color}`,
                  display: "inline-block",
                }}
              />
              {STATE_STYLE[s].label}
            </span>
          ))}
      </div>
    </div>
  );
}
