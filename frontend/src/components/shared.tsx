/** Small shared presentational components. */

import type { ReactNode } from "react";
import HeaderHint from "./HeaderHint";
import { Link, useLocation } from "react-router-dom";
import { useAppState } from "../state";
import type { JobEvent } from "../api";
import { downloadCsv } from "../lib/download";

export function ZoneChip({ zone }: { zone: string }) {
  const { zoneColor } = useAppState();
  return (
    <span className="zone-chip">
      <span className="dot" style={{ background: zoneColor(zone) }} />
      {zone}
    </span>
  );
}

export function Sparkline({
  values,
  color = "var(--accent)",
  width = 140,
  height = 30,
}: {
  values: number[];
  color?: string;
  width?: number;
  height?: number;
}) {
  if (values.length < 2) return null;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const pts = values.map((v, i) => {
    const x = (i / (values.length - 1)) * (width - 2) + 1;
    const y = height - 3 - ((v - min) / span) * (height - 6);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const last = pts[pts.length - 1].split(",");
  return (
    <svg className="spark" width={width} height={height} aria-hidden="true">
      <polyline
        points={pts.join(" ")}
        fill="none"
        stroke={color}
        strokeWidth="1.8"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
      <circle cx={last[0]} cy={last[1]} r="2.4" fill={color} />
    </svg>
  );
}

export function StatTile({
  label,
  value,
  hint,
  delta,
  deltaGoodWhenDown = true,
  spark,
  sparkColor,
}: {
  label: string;
  value: ReactNode;
  hint?: string;
  delta?: number | null;
  deltaGoodWhenDown?: boolean;
  spark?: number[];
  sparkColor?: string;
}) {
  const showDelta = delta !== undefined && delta !== null && Number.isFinite(delta) && delta !== 0;
  const up = (delta ?? 0) > 0;
  const cls = deltaGoodWhenDown ? (up ? "up" : "down") : up ? "down" : "up";
  return (
    <div className="tile">
      <div className="label">{label}</div>
      <div className="value">
        {value}
        {showDelta && (
          <span className={`delta ${cls}`}>
            {up ? "▲" : "▼"} {Math.abs(delta!).toLocaleString(undefined, { maximumFractionDigits: 1 })}
          </span>
        )}
      </div>
      {hint && <div className="hint">{hint}</div>}
      {spark && spark.length > 1 && <Sparkline values={spark} color={sparkColor} />}
    </div>
  );
}

export function SkeletonPanel({ rows = 3 }: { rows?: number }) {
  return (
    <div className="panel">
      <div className="skeleton" style={{ height: 16, width: "34%", marginBottom: 14 }} />
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="skeleton" style={{ height: 12, width: `${88 - i * 9}%`, marginBottom: 9 }} />
      ))}
    </div>
  );
}

const STAGE_LABELS: Record<string, string> = {
  load: "Parse event log & model",
  queue: "Compute slot",
  align: "Compute alignments",
  replay: "Reconstruct tokens",
  conformance: "Build conformance tables",
  features: "Build zone-feature table",
  persist: "Persist artifacts",
};

export function StageProgress({ events }: { events: JobEvent[] }) {
  const stages = ["queue", "load", "align", "replay", "conformance", "features", "persist"];
  const state: Record<string, JobEvent | undefined> = {};
  for (const ev of events) state[ev.stage] = ev;
  return (
    <div className="stage-list">
      {stages.map((s) => {
        const ev = state[s];
        const cls = ev ? ev.status : "pending";
        return (
          <div key={s} className={`stage ${cls}`}>
            <span className="indicator" />
            <span>{STAGE_LABELS[s] ?? s}</span>
            {ev?.detail && <span className="detail">{ev.detail}</span>}
          </div>
        );
      })}
    </div>
  );
}

export function DataTable({
  rows,
  columns,
  format,
  labels,
  headerHelp,
  downloadName = "zone-analytics-table",
}: {
  rows: Record<string, unknown>[];
  columns?: string[];
  labels?: Record<string, string>;
  headerHelp?: Record<string, string>;
  format?: Record<string, (v: unknown, row: Record<string, unknown>) => ReactNode>;
  downloadName?: string;
}) {
  if (!rows.length) return <p className="help">No rows.</p>;
  const cols = columns ?? Object.keys(rows[0]);
  return (
    <div className="table-scroll">
      <div className="row" style={{ justifyContent: "flex-end", marginBottom: 8 }}>
        <button onClick={() => downloadCsv(rows, cols, downloadName, labels)}
          title="Exports the rows shown in this table, with underlying numeric precision.">Download displayed rows (CSV)</button>
      </div>
      <table className="data">
        <thead>
          <tr>
            {cols.map((c) => (
              <th key={c}>
                {labels?.[c] ?? c.replaceAll("_", " ")}
                {headerHelp?.[c] && <HeaderHint label={labels?.[c] ?? c.replaceAll("_", " ")} text={headerHelp[c]} />}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              {cols.map((c) => (
                <td key={c}>{format?.[c] ? format[c](r[c], r) : fmtCell(r[c])}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function fmtCell(v: unknown): ReactNode {
  if (v === null || v === undefined) return <span className="help">–</span>;
  if (typeof v === "number") {
    if (Number.isInteger(v)) return v.toLocaleString();
    return v.toLocaleString(undefined, { maximumFractionDigits: 3 });
  }
  return String(v);
}

export function NeedsAnalysis({ children }: { children: ReactNode }) {
  const { analysis, analysisId, analysisError } = useAppState();
  const { pathname } = useLocation();
  const preview: Record<string, [string, string]> = {
    "/overview": ["Overview & alerts", "See how much work is in each zone, recent alerts, and a map of flow between zones."],
    "/replay": ["Token replay", "Play reconstructed token movement, inspect a historical moment, and follow a selected case through its zones."],
    "/trends": ["Trends & change points", "Choose zone metrics to plot, inspect detected changes, and compare behavior across periods."],
    "/flow": ["Flow patterns", "Explore waiting times, repeated visits, batching, overtaking, and handovers between zones."],
    "/dependencies": ["Dependencies", "Find zone metrics that move together or in opposite directions, possibly with a delay. Inspect how many windows support each association."],
    "/prediction": ["Prediction", "Compare models for a future-window condition using reconstructed history and inspect their retrospective evaluation."],
  };
  const introduction = preview[pathname];
  if (analysisId && !analysis) {
    return <p role={analysisError ? "alert" : "status"}>{analysisError ? `Unable to load analysis: ${analysisError}. Reload to try again.` : "Loading analysis…"}</p>;
  }
  if (!analysis?.has_artifacts) {
    return (
      <div className="panel">
        {introduction && <><h1>{introduction[0]}</h1><p>{introduction[1]}</p></>}
        <h2>No analysis yet</h2>
        <p className="help">
          Upload an event log; a Petri net is optional because ZoneMiner can discover a model. Define and validate zones, then run an analysis. You can also load an example scenario, or use the Tour to explore the tool before you start.
        </p>
        <Link to="/" className="btn">
          Go to Data, Model &amp; Zones
        </Link>
      </div>
    );
  }
  return <>{children}</>;
}
