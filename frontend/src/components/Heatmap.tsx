/** Zone × window heatmap (EXTENSIONS B5).
 *
 * One row per zone, one cell per time window, colored on the theme's
 * sequential ramp (--heat-0 → --heat-1 via CSS color-mix, so it re-themes
 * without JS). Cells are scaled per row (min → max within the zone): the
 * heatmap's job is showing WHEN each zone runs hot, not comparing absolute
 * magnitudes across zones — the trend chart above does that. Raw values stay
 * available on hover and in the table below the charts.
 */

import { useMemo } from "react";
import { ZoneChip } from "./shared";

export interface HeatmapRow {
  zone: string;
  window_start: string;
  value: number | null;
}

export default function Heatmap({ rows, zones, valueUnit = "" }: { rows: HeatmapRow[]; zones: string[]; valueUnit?: string }) {
  const { windows, byZone } = useMemo(() => {
    const wins = Array.from(new Set(rows.map((r) => r.window_start))).sort();
    const m = new Map<string, Map<string, number | null>>();
    for (const r of rows) {
      if (!m.has(r.zone)) m.set(r.zone, new Map());
      m.get(r.zone)!.set(r.window_start, r.value);
    }
    return { windows: wins, byZone: m };
  }, [rows]);

  if (!windows.length) return <p className="help">No data.</p>;

  const label = (w: string) => w;
  const tickEvery = Math.max(1, Math.ceil(windows.length / 8));

  return (
    <div style={{ overflowX: "auto" }}>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: `max-content repeat(${windows.length}, minmax(7px, 1fr))`,
          gap: 2,
          alignItems: "center",
          minWidth: windows.length * 9 + 160,
        }}
      >
        {zones.map((z) => {
          const vals = windows.map((w) => byZone.get(z)?.get(w) ?? null);
          const finite = vals.filter((v): v is number => v !== null && Number.isFinite(v));
          const lo = finite.length ? Math.min(...finite) : 0;
          const hi = finite.length ? Math.max(...finite) : 1;
          const span = hi - lo || 1;
          return (
            <div key={z} style={{ display: "contents" }}>
              <div style={{ paddingRight: 10 }}>
                <ZoneChip zone={z} />
              </div>
              {vals.map((v, i) => {
                const missing = v === null || !Number.isFinite(v);
                const pct = missing ? 0 : Math.round(((v - lo) / span) * 100);
                return (
                  <div
                    key={windows[i]}
                    title={
                      missing
                        ? `${z} · ${label(windows[i])} — no value`
                        : `${z} · ${label(windows[i])} — ${v.toLocaleString(undefined, { maximumFractionDigits: 2 })} ${valueUnit}`
                    }
                    style={{
                      height: 24,
                      borderRadius: 3,
                      background: missing
                        ? "transparent"
                        : `color-mix(in oklab, var(--heat-1) ${pct}%, var(--heat-0))`,
                      border: missing ? "1px dashed var(--grid)" : "1px solid transparent",
                    }}
                  />
                );
              })}
            </div>
          );
        })}
        {/* time axis: sparse date ticks under the grid */}
        <div />
        {windows.map((w, i) => (
          <div
            key={w}
            className="help"
            style={{
              fontSize: 10,
              whiteSpace: "nowrap",
              overflow: "visible",
              visibility: i % tickEvery === 0 ? "visible" : "hidden",
            }}
          >
            {label(w).slice(5)}
          </div>
        ))}
      </div>
      <div className="row" style={{ marginTop: 8, gap: 8 }}>
        <span className="help">low</span>
        <div
          aria-hidden="true"
          style={{
            width: 140,
            height: 10,
            borderRadius: 5,
            background:
              "linear-gradient(90deg, var(--heat-0), color-mix(in oklab, var(--heat-1) 50%, var(--heat-0)), var(--heat-1))",
          }}
        />
        <span className="help">high — scaled per zone (row min → row max); hover for values</span>
      </div>
    </div>
  );
}
