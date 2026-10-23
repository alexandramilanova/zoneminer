/** Pair-aware trends. Raw mixed units are separated by the caller, never dual axes. */
import { useMemo } from "react";
import { Plot, resolveColor, themedLayout } from "../lib/plot";
import { useAppState } from "../state";
import type { AggregateChangePoint, ChangePointRecord } from "../api";

export interface TrendRow { zone: string; window_start: string; value: number | null; metric?: string }
export interface BandRow { zone: string; window_start: string; lo: number | null; hi: number | null; metric?: string }
export interface TrendSeries { zone: string; metric: string; label: string; unit: string }
export const pairKey = (zone: string, metric: string) => JSON.stringify([zone, metric]);
const timeKey = (time: string) => {
  const parsed = Date.parse(time.replace(" ", "T"));
  return Number.isFinite(parsed) ? String(parsed) : time;
};

export default function TrendChart({ rows, changepoints = [], aggregateChangepoints = [], metricLabel, valueUnit = "",
  cursorTime, bands, metricColumn, series, observations = false }: {
  rows: TrendRow[]; changepoints?: ChangePointRecord[]; aggregateChangepoints?: AggregateChangePoint[];
  metricLabel: string; valueUnit?: string; cursorTime?: string | null; bands?: BandRow[]; metricColumn?: string;
  series?: TrendSeries[]; observations?: boolean;
}) {
  const { zoneColor, zones } = useAppState();
  const spec = useMemo(() => {
    const definitions: TrendSeries[] = series ?? zones.filter((z) => rows.some((r) => r.zone === z))
      .map((zone) => ({ zone, metric: metricColumn ?? "", label: zone, unit: valueUnit }));
    const traces: Record<string, unknown>[] = [];
    for (const definition of definitions) {
      const { zone, metric, label, unit } = definition;
      const group = pairKey(zone, metric);
      const points = rows.filter((r) => r.zone === zone && (!series || r.metric === metric))
        .slice().sort((a, b) => a.window_start.localeCompare(b.window_start));
      const color = resolveColor(zoneColor(zone));
      const interval = (bands ?? []).filter((b) => b.zone === zone && (!b.metric || b.metric === metric) && b.lo != null && b.hi != null)
        .sort((a, b) => a.window_start.localeCompare(b.window_start));
      if (interval.length > 1) traces.push(
        { type: "scatter", mode: "lines", x: interval.map((b) => b.window_start), y: interval.map((b) => b.hi),
          line: { width: 0 }, hoverinfo: "skip", showlegend: false, legendgroup: group, meta: { kind: "confidence" } },
        { type: "scatter", mode: "lines", x: interval.map((b) => b.window_start), y: interval.map((b) => b.lo),
          line: { width: 0 }, fill: "tonexty", fillcolor: color + "26", hoverinfo: "skip", showlegend: false,
          legendgroup: group, meta: { kind: "confidence" } },
      );
      traces.push({ type: "scatter", mode: observations ? "lines+markers" : "lines", name: label, legendgroup: group,
        x: points.map((p) => p.window_start), y: points.map((p) => p.value), connectgaps: false,
        line: { color, width: 2, dash: "solid" }, marker: { color, size: 5 },
        customdata: points.map((p) => [p.window_start, zone, metric, unit]), meta: { kind: "series", zone, metric },
        hovertemplate: "%{customdata[0]}<br>%{customdata[1]} · %{customdata[2]}<br>%{y:.4~f} %{customdata[3]}<extra></extra>" });
      const seen = new Set<string>();
      const changes = changepoints.filter((cp) => cp.zone === zone && (!metric || cp.metric_column === metric)).filter((cp) => {
        const key = timeKey(cp.timestamp);
        if (seen.has(key)) return false;
        seen.add(key); return true;
      }).map((cp) => ({ cp, row: points.find((p) => timeKey(p.window_start) === timeKey(cp.timestamp)) }))
        .filter((point) => point.row?.value != null);
      if (changes.length) traces.push({ type: "scatter", mode: "markers", name: `${label} · local changes`, legendgroup: group, showlegend: false,
        x: changes.map(({ cp }) => cp.timestamp), y: changes.map(({ row }) => row!.value),
        customdata: changes.map(({ cp }) => [cp.timestamp, cp.zone, cp.metric_label]),
        meta: { kind: "local", zone, metric },
        marker: { symbol: "diamond", size: 11, color, line: { width: 1, color: resolveColor("var(--surface)") } },
        hovertemplate: `Local: %{customdata[0]}<br>%{customdata[1]} · %{customdata[2]}<br>%{y:.4~f} ${unit}<extra></extra>` });
    }
    const times = [...new Map(aggregateChangepoints.map((cp) => [timeKey(cp.timestamp), cp.timestamp])).values()];
    const shapes: Record<string, unknown>[] = times.map((timestamp) => ({ type: "line", xref: "x", x0: timestamp, x1: timestamp,
      yref: "paper", y0: 0, y1: 1, line: { color: resolveColor("var(--accent)"), width: 2, dash: "solid" } }));
    if (cursorTime) shapes.push({ type: "line", x0: cursorTime, x1: cursorTime, yref: "paper", y0: 0, y1: 1,
      line: { color: resolveColor("var(--accent)"), width: 2, dash: "solid" } });
    return { traces, shapes };
  }, [rows, changepoints, aggregateChangepoints, metricLabel, valueUnit, cursorTime, bands, metricColumn, series, observations, zones, zoneColor]);
  if (!rows.length) return <p className="help">No data for this selection.</p>;
  return <Plot data={spec.traces} layout={themedLayout({ shapes: spec.shapes,
    xaxis: { ...(themedLayout().xaxis as object), type: "date", title: { text: "Analysis window" } },
    yaxis: { ...(themedLayout().yaxis as object), title: { text: metricLabel, font: { size: 11 } } },
    legend: { ...(themedLayout().legend as object), groupclick: "togglegroup" },
  })} height={380} />;
}
