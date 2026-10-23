import { formatDuration } from "../lib/metricPresentation";
/** Flow patterns: per-zone views built from case-zone stays.
 *
 * Cumulative Flow Diagram (CFD): cumulative entries vs. cumulative exits over
 * time. The shaded area between the curves is work-in-progress; a widening
 * wedge is backlog building up, the horizontal gap approximates sojourn time.
 *
 * Fingerprint scatter: exit time vs. entry time per completed stay. Vertical
 * distance above the diagonal = sojourn; horizontal rows of points = batched
 * exits; a point lower than a point to its left = overtaking (a later-entering
 * case left earlier). Both patterns are visible without any detector.
 */

import { useEffect, useMemo, useState, type ReactNode } from "react";
import { api, type BottleneckState, type QueueingZoneProfile, type ZoneStay } from "../api";
import { useAppState } from "../state";
import HandoverSankey from "../components/HandoverSankey";
import { STATE_STYLE } from "../lib/states";
import { DataTable, NeedsAnalysis, SkeletonPanel, StatTile, ZoneChip } from "../components/shared";
import { Plot, resolveColor } from "../lib/plot";

/** Backend timestamps are naive "YYYY-MM-DD HH:MM:SS" strings — parse as UTC
 * so the display is timezone-independent (same convention as the replay). */
export function parseTs(s: string): number {
  return Date.parse(s.slice(0, 19).replace(" ", "T") + "Z");
}

interface CfdSeries {
  x: string[];
  entries: number[];
  exits: number[];
  wip: number[];
}

/** Cumulative entries/exits evaluated on the merged, sorted event timeline. */
function buildCfd(stays: ZoneStay[], maxPoints = 3000): CfdSeries {
  const events: { t: number; entry: boolean }[] = [];
  for (const s of stays) {
    events.push({ t: parseTs(s.entry_ts), entry: true });
    if (s.exit_ts) events.push({ t: parseTs(s.exit_ts), entry: false });
  }
  events.sort((a, b) => a.t - b.t);
  const x: number[] = [];
  const entries: number[] = [];
  const exits: number[] = [];
  let cumE = 0;
  let cumX = 0;
  for (let i = 0; i < events.length; i++) {
    if (events[i].entry) cumE++;
    else cumX++;
    // collapse simultaneous events into one point
    if (i + 1 < events.length && events[i + 1].t === events[i].t) continue;
    x.push(events[i].t);
    entries.push(cumE);
    exits.push(cumX);
  }
  // decimate long series, always keeping the final point
  const step = Math.ceil(x.length / maxPoints);
  const keep = (i: number) => i % step === 0 || i === x.length - 1;
  const iso = (t: number) => new Date(t).toISOString().slice(0, 19).replace("T", " ");
  return {
    x: x.filter((_, i) => keep(i)).map(iso),
    entries: entries.filter((_, i) => keep(i)),
    exits: exits.filter((_, i) => keep(i)),
    wip: entries.map((e, i) => e - exits[i]).filter((_, i) => keep(i)),
  };
}

function CfdPanel({ zone, stays }: { zone: string; stays: ZoneStay[] }) {
  const { zoneColor } = useAppState();
  const cfd = useMemo(() => buildCfd(stays), [stays]);
  const color = resolveColor(zoneColor(zone));
  const openCount = stays.filter((s) => s.is_open).length;
  const peakWip = cfd.wip.length ? Math.max(...cfd.wip) : 0;
  return (
    <div className="panel">
      <div className="row" style={{ justifyContent: "space-between", marginBottom: 4 }}>
        <ZoneChip zone={zone} />
        <span className="help">
          {stays.length.toLocaleString()} stays · {openCount.toLocaleString()} open · peak WIP{" "}
          {peakWip.toLocaleString()}
        </span>
      </div>
      <Plot
        height={250}
        data={[
          {
            x: cfd.x,
            y: cfd.entries,
            name: "Cumulative entries",
            mode: "lines",
            line: { color, width: 2, shape: "hv" },
            hovertemplate: "entered so far: %{y}<extra></extra>",
          },
          {
            x: cfd.x,
            y: cfd.exits,
            name: "Cumulative exits",
            mode: "lines",
            line: { color, width: 2, dash: "dot", shape: "hv" },
            fill: "tonexty",
            fillcolor: color + "2e",
            customdata: cfd.wip,
            hovertemplate: "left so far: %{y} · in zone: %{customdata}<extra></extra>",
          },
        ]}
      />
    </div>
  );
}

/** Share of adjacent-by-entry pairs where the later-entering case exited
 * first — a quick FIFO-ness cue shown in the panel header (the exact
 * windowed metrics live in the feature table). */
function quickOvertakeShare(stays: ZoneStay[]): number | null {
  const done = stays
    .filter((s) => !s.is_open && s.exit_ts)
    .map((s) => ({ e: parseTs(s.entry_ts), x: parseTs(s.exit_ts!) }))
    .sort((a, b) => a.e - b.e);
  if (done.length < 2) return null;
  let inversions = 0;
  for (let i = 1; i < done.length; i++) if (done[i].x < done[i - 1].x) inversions++;
  return inversions / (done.length - 1);
}

function FingerprintPanel({ zone, stays }: { zone: string; stays: ZoneStay[] }) {
  const { zoneColor } = useAppState();
  const color = resolveColor(zoneColor(zone));
  const grid = resolveColor("var(--grid)");
  const baseline = resolveColor("var(--baseline)");
  const done = useMemo(() => stays.filter((s) => !s.is_open && s.exit_ts), [stays]);
  const overtake = useMemo(() => quickOvertakeShare(stays), [stays]);
  if (!done.length) {
    return (
      <div className="panel">
        <ZoneChip zone={zone} />
        <p className="help">No completed stays.</p>
      </div>
    );
  }
  const x = done.map((s) => s.entry_ts.slice(0, 19));
  const y = done.map((s) => s.exit_ts!.slice(0, 19));
  const custom = done.map((s) => [s.case_id, ((s.duration_s ?? 0) / 3600).toFixed(1)]);
  const tMin = x.reduce((a, b) => (a < b ? a : b));
  const tMax = y.reduce((a, b) => (a > b ? a : b));
  const axis = { gridcolor: grid, linecolor: baseline, zeroline: false };
  return (
    <div className="panel">
      <div className="row" style={{ justifyContent: "space-between", marginBottom: 4 }}>
        <ZoneChip zone={zone} />
        <span className="help">
          {done.length.toLocaleString()} completed stays
          {overtake !== null && ` · ${(overtake * 100).toFixed(0)}% adjacent overtakes`}
        </span>
      </div>
      <Plot
        height={290}
        data={[
          {
            x: [tMin, tMax],
            y: [tMin, tMax],
            mode: "lines",
            name: "Instant pass-through",
            line: { color: baseline, width: 1, dash: "dash" },
            hoverinfo: "skip",
          },
          {
            x,
            y,
            mode: "markers",
            name: "Completed stays",
            marker: { color, size: 4.5, opacity: 0.45 },
            customdata: custom,
            hovertemplate:
              "case %{customdata[0]}<br>entered %{x}<br>left %{y}<br>%{customdata[1]} h in zone<extra></extra>",
          },
        ]}
        layout={{
          hovermode: "closest",
          showlegend: false,
          xaxis: { ...axis, title: { text: "entry time", font: { size: 11 } } },
          yaxis: { ...axis, title: { text: "exit time", font: { size: 11 } } },
          margin: { l: 90, r: 16, t: 8, b: 44 },
        }}
      />
    </div>
  );
}

/** RGB interpolation between two resolved hex colors (t in [0,1]). */
function lerpHex(a: string, b: string, t: number): string {
  const pa = [1, 3, 5].map((i) => parseInt(a.slice(i, i + 2), 16));
  const pb = [1, 3, 5].map((i) => parseInt(b.slice(i, i + 2), 16));
  const c = pa.map((v, i) => Math.round(v + (pb[i] - v) * t));
  return `#${c.map((v) => v.toString(16).padStart(2, "0")).join("")}`;
}

const QUARTILE_LABELS = ["fastest 25%", "25–50%", "50–75%", "slowest 25%"];

/** The classical performance spectrum (Denisov et al., BPM 2018), drawn per
 * zone: one band per zone, one line per completed stay from (entry, band top)
 * to (exit, band bottom), colored by duration quartile within its zone.
 * Crossing lines = overtaking; fans converging to a vertical = batching;
 * color regime shifts = drift. */
function SpectrumSection({ byZone }: { byZone: Map<string, ZoneStay[]> }) {
  const { zones } = useAppState();
  const spec = useMemo(() => {
    const heat0 = resolveColor("var(--heat-0)");
    const heat1 = resolveColor("var(--heat-1)");
    const colors = [0.25, 0.5, 0.75, 1].map((t) => lerpHex(heat0, heat1, t));
    const grid = resolveColor("var(--grid)");
    const baseline = resolveColor("var(--baseline)");

    // one trace per quartile, null-separated segments across all zones
    const xs: (string | null)[][] = [[], [], [], []];
    const ys: (number | null)[][] = [[], [], [], []];
    zones.forEach((zone, zi) => {
      const done = (byZone.get(zone) ?? []).filter((s) => !s.is_open && s.exit_ts);
      if (!done.length) return;
      const durs = done.map((s) => s.duration_s ?? 0).sort((a, b) => a - b);
      const q = (p: number) => durs[Math.min(durs.length - 1, Math.floor(p * durs.length))];
      const q25 = q(0.25);
      const q50 = q(0.5);
      const q75 = q(0.75);
      for (const s of done) {
        const d = s.duration_s ?? 0;
        const k = d <= q25 ? 0 : d <= q50 ? 1 : d <= q75 ? 2 : 3;
        xs[k].push(s.entry_ts.slice(0, 19), s.exit_ts!.slice(0, 19), null);
        ys[k].push(zi + 0.92, zi + 0.08, null);
      }
    });
    const data = xs.map((x, k) => ({
      x,
      y: ys[k],
      mode: "lines",
      name: QUARTILE_LABELS[k],
      line: { color: colors[k], width: 1 },
      opacity: 0.5,
      hoverinfo: "skip",
    }));
    const layout = {
      hovermode: false as const,
      xaxis: { gridcolor: grid, linecolor: baseline, zeroline: false },
      yaxis: {
        tickvals: zones.map((_, i) => i + 0.5),
        ticktext: zones,
        range: [0, zones.length],
        gridcolor: "rgba(0,0,0,0)",
        zeroline: false,
        fixedrange: true,
      },
      shapes: zones.slice(1).map((_, i) => ({
        type: "line",
        xref: "paper",
        x0: 0,
        x1: 1,
        y0: i + 1,
        y1: i + 1,
        line: { color: grid, width: 1 },
      })),
      legend: { orientation: "h" as const, y: -0.12 },
      margin: { l: 150, r: 16, t: 8, b: 40 },
    };
    return { data, layout };
  }, [byZone, zones]);

  return (
    <>
      <h2 style={{ margin: "12px 0 4px" }}>Zone performance spectrum</h2>
      <p className="help" style={{ marginBottom: 10 }}>
        The classical performance spectrum, drawn per zone: each line is one completed stay,
        falling from its <em>entry</em> (top of the band) to its <em>exit</em> (bottom), colored
        by duration quartile within the zone. Parallel lines can suggest orderly flow;{" "}
        <strong>crossing lines</strong> indicate overtaking; <strong>fans converging to a point</strong>{" "}
        suggest grouped releases. Color changes show shifts in completed-stay durations; they are not a statistical drift test.
      </p>
      <div className="panel">
        <Plot data={spec.data} layout={spec.layout} height={Math.max(340, zones.length * 105)} />
      </div>
    </>
  );
}

function HandoverSection() {
  const { analysisId, analysis } = useAppState();
  const [data, setData] = useState<Awaited<ReturnType<typeof api.handovers>> | null>(null);
  const [periodIdx, setPeriodIdx] = useState(-1); // -1 = whole timeline
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!analysisId || !analysis?.has_artifacts) return;
    setData(null);
    setPeriodIdx(-1);
    api
      .handovers(analysisId, 6)
      .then(setData)
      .catch((e) => setError(String(e)));
  }, [analysisId, analysis?.has_artifacts]);

  const pairs = data ? (periodIdx < 0 ? data.pairs : data.periods[periodIdx]?.pairs ?? []) : null;
  const periodLabel =
    data && periodIdx >= 0 && data.periods[periodIdx]
      ? `${data.periods[periodIdx].start.slice(0, 10)} → ${data.periods[periodIdx].end.slice(0, 10)}`
      : "whole timeline";

  const fmtDelay = formatDuration;

  return (
    <>
      <h2 style={{ margin: "20px 0 4px" }}>Zone handovers</h2>
      <p className="help" style={{ marginBottom: 10 }}>
        Where cases go when they leave a zone: ribbon width is handover volume, so drop-offs
        between stages (cases that never reach the next zone) are visible as narrowing flows. The
        handover delay is time spent in <em>no</em> zone — waiting in unassigned places between
        zones; with a zone system covering all intermediate places it is expected to be ~0.
      </p>
      {error && <div className="notice error">{error}</div>}
      {!pairs && !error && <SkeletonPanel rows={4} />}
      {data && data.periods.length > 1 && (
        <div className="row" style={{ marginBottom: 10 }}>
          <label className="help" style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
            Period{" "}
            <input
              type="range"
              min={-1}
              max={data.periods.length - 1}
              step={1}
              value={periodIdx}
              onChange={(e) => setPeriodIdx(Number(e.target.value))}
              style={{ width: 220 }}
            />
          </label>
          <span className="help">
            {periodLabel}
            {periodIdx >= 0 && ` · slide left for the whole timeline`}
          </span>
        </div>
      )}
      {pairs && pairs.length === 0 && <p className="help">No inter-zone handovers in this period.</p>}
      {pairs && pairs.length > 0 && (
        <div className="grid" style={{ gridTemplateColumns: "minmax(380px, 3fr) minmax(300px, 2fr)" }}>
          <div className="panel">
            <HandoverSankey pairs={pairs} />
          </div>
          <div className="panel">
            <DataTable
              rows={pairs.map((p) => ({
                from: p.src,
                to: p.tgt,
                handovers: p.count,
                "median delay": p.median_delay_s,
              }))}
              format={{
                from: (v) => <ZoneChip zone={String(v)} />,
                to: (v) => <ZoneChip zone={String(v)} />,
                "median delay": fmtDelay,
              }}
            />
          </div>
        </div>
      )}
    </>
  );
}

function QueueingSection() {
  const { analysisId, analysis, zones, zoneColor } = useAppState();
  const [profile, setProfile] = useState<QueueingZoneProfile[] | null>(null);
  const [note, setNote] = useState("");
  const [scatterZone, setScatterZone] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!analysisId || !analysis?.has_artifacts) return;
    setProfile(null);
    api
      .queueing(analysisId)
      .then((r) => {
        setProfile(r.zones);
        setNote(r.note);
        // default scatter: strongest load dependence — the most telling zone
        const best = [...r.zones].sort(
          (a, b) => Math.abs(b.load_dependence_r ?? 0) - Math.abs(a.load_dependence_r ?? 0),
        )[0];
        setScatterZone(best?.zone ?? null);
      })
      .catch((e) => setError(String(e)));
  }, [analysisId, analysis?.has_artifacts]);

  const fmtH = formatDuration;
  const rows = (profile ?? []).map((p) => ({
    zone: p.zone,
    "arrivals / day": p.arrival_rate_per_day.toFixed(1),
    "departures / day": p.departure_rate_per_day.toFixed(1),
    "mean sojourn": fmtH(p.sojourn_mean_s),
    "avg WIP": p.wip_time_avg.toFixed(1),
    "Little's ratio": p.littles_ratio,
    "arrival burstiness (CV)": p.cv_interarrival?.toFixed(2) ?? null,
    "sojourn variability (CV)": p.cv_sojourn?.toFixed(2) ?? null,
    "load-dependence r": p.load_dependence_r,
  }));

  const sel = profile?.find((p) => p.zone === scatterZone);
  return (
    <>
      <h2 style={{ margin: "20px 0 4px" }}>Queueing profile</h2>
      <p className="help" style={{ marginBottom: 10 }}>
        Treating each zone as an aggregate queue: arrival and departure rates, time-averaged work-in-progress, and two
        diagnostics. <strong>Little's ratio</strong> compares measured WIP against arrival rate ×
        sojourn (λ·W) on the middle 80% of the timeline — near 1 is compatible with flow balance but does not prove stationarity. <strong>Load-dependence r</strong> correlates a case's sojourn with how many cases
        were already in the zone when it arrived: positive values indicate longer stays coinciding with greater entry occupancy. Near-zero values indicate little linear association. Neither identifies the cause of delay. {note}
      </p>
      {error && <div className="notice error">{error}</div>}
      {!profile && !error && <SkeletonPanel rows={4} />}
      {profile && (
        <div className="panel">
          <DataTable
            rows={rows}
            format={{
              zone: (v) => <ZoneChip zone={String(v)} />,
              "Little's ratio": (v) =>
                v === null ? (
                  <span className="help">–</span>
                ) : (
                  <span>
                    {Number(v).toFixed(2)}{" "}
                    {Math.abs(Number(v) - 1) <= 0.2 ? "✓" : "⚠"}
                  </span>
                ),
              "load-dependence r": (v) =>
                v === null ? (
                  <span className="help">–</span>
                ) : (
                  <strong style={{ fontWeight: Math.abs(Number(v)) >= 0.3 ? 700 : 400 }}>
                    {Number(v).toFixed(2)}
                  </strong>
                ),
            }}
          />
        </div>
      )}
      {profile && profile.some((p) => p.queue_model) && (
        <div className="panel">
          <h3 style={{ marginTop: 0 }}>Queue-model lens (experimental)</h3>
          <p className="help">
            Each zone fitted as an aggregated-server G/G/1 queue with mined parameters (service
            time from low-load arrivals, service rate from peak sustained throughput, Kingman's
            formula for the stationary mean wait). These are approximations of reconstructed stays,
            not observed resource service or waiting times. Fit labels summarize diagnostic rules:
            a plausible fit does not establish stationarity, and a poor fit does not identify a cause.
          </p>
          <DataTable
            rows={profile
              .filter((p) => p.queue_model)
              .map((p) => ({
                zone: p.zone,
                "service time": fmtH(p.queue_model!.service_time_s),
                "utilization ρ": p.queue_model!.utilization?.toFixed(2) ?? "–",
                "model wait (Kingman)": fmtH(p.queue_model!.kingman_wait_s),
                "measured wait": fmtH(p.queue_model!.measured_wait_s),
                verdict: p.queue_model!.fit,
              }))}
            format={{
              zone: (v) => <ZoneChip zone={String(v)} />,
              verdict: (v) => {
                const s = String(v);
                const cls = s === "plausible" ? "ok" : s === "regime-shift" || s === "overloaded" ? "crit" : "warn";
                return <span className={`badge ${cls}`}>{s}</span>;
              },
            }}
          />
        </div>
      )}

      {sel && (
        <div className="panel">
          <div className="row" style={{ justifyContent: "space-between", marginBottom: 4 }}>
            <h3 style={{ margin: 0 }}>Sojourn vs. load at arrival</h3>
            <span className="row" style={{ gap: 6 }}>
              {zones.map((z) => (
                <button
                  key={z}
                  className={z === scatterZone ? "primary" : ""}
                  onClick={() => setScatterZone(z)}
                >
                  {z}
                </button>
              ))}
            </span>
          </div>
          <p className="help">
            One dot per completed stay in <ZoneChip zone={sel.zone} />: how many cases were already
            in the zone when it arrived (x) vs. how long it stayed (y). An upward drift is the
            "slow because busy" signature (r = {sel.load_dependence_r?.toFixed(2) ?? "–"},
            association not causation).
          </p>
          <Plot
            height={300}
            data={[
              {
                x: sel.scatter.occupancy_at_entry,
                y: sel.scatter.sojourn_s.map((s) => s / 3600),
                mode: "markers",
                name: sel.zone,
                marker: { color: resolveColor(zoneColor(sel.zone)), size: 5, opacity: 0.4 },
                hovertemplate: "%{x} in zone at arrival<br>stayed %{y:.1f} h<extra></extra>",
              },
            ]}
            layout={{
              hovermode: "closest",
              showlegend: false,
              xaxis: {
                gridcolor: resolveColor("var(--grid)"),
                linecolor: resolveColor("var(--baseline)"),
                zeroline: false,
                title: { text: "cases in zone at arrival", font: { size: 11 } },
              },
              yaxis: {
                gridcolor: resolveColor("var(--grid)"),
                linecolor: resolveColor("var(--baseline)"),
                zeroline: false,
                rangemode: "tozero",
                title: { text: "sojourn (hours)", font: { size: 11 } },
              },
              margin: { l: 64, r: 16, t: 8, b: 44 },
            }}
          />
        </div>
      )}
    </>
  );
}

function BottleneckSection() {
  const { analysisId, analysis } = useAppState();
  const [data, setData] = useState<Awaited<ReturnType<typeof api.bottlenecks>> | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!analysisId || !analysis?.has_artifacts) return;
    setData(null);
    api.bottlenecks(analysisId).then(setData).catch((e) => setError(String(e)));
  }, [analysisId, analysis?.has_artifacts]);

  const tickEvery = data ? Math.max(1, Math.ceil(data.windows.length / 8)) : 1;
  return (
    <>
      <h2 style={{ margin: "20px 0 4px" }}>Bottleneck states</h2>
      <p className="help" style={{ marginBottom: 10 }}>
        Each zone-window classified by a quantile heuristic over the zone's own history and the
        handover graph — <em>indications to investigate, not ground truth</em>. "Queueing", "blocked" and "starving" are heuristic labels based on occupancy,
        flow and neighboring zones. They suggest where to inspect the reconstructed series;
        they do not verify a physical queue, resource state or the cause of a delay.
      </p>
      {error && <div className="notice error">{error}</div>}
      {!data && !error && <SkeletonPanel rows={4} />}
      {data && (
        <div className="panel">
          <div style={{ overflowX: "auto" }}>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: `max-content repeat(${data.windows.length}, minmax(7px, 1fr))`,
                gap: 2,
                alignItems: "center",
                minWidth: data.windows.length * 9 + 160,
              }}
            >
              {data.zones.map((z) => (
                <div key={z.zone} style={{ display: "contents" }}>
                  <div style={{ paddingRight: 10 }}>
                    <ZoneChip zone={z.zone} />
                  </div>
                  {z.states.map((s, i) => (
                    <div
                      key={data.windows[i]}
                      title={`${z.zone} · ${data.windows[i].slice(0, 10)} — ${STATE_STYLE[s].label}`}
                      style={{
                        height: 24,
                        borderRadius: 3,
                        background: STATE_STYLE[s].color,
                        border: "1px solid transparent",
                      }}
                    />
                  ))}
                </div>
              ))}
              <div />
              {data.windows.map((w, i) => (
                <div
                  key={w}
                  className="help"
                  style={{
                    fontSize: 10,
                    whiteSpace: "nowrap",
                    visibility: i % tickEvery === 0 ? "visible" : "hidden",
                  }}
                >
                  {w.slice(5, 10)}
                </div>
              ))}
            </div>
          </div>
          <div className="row" style={{ marginTop: 10, gap: 14 }}>
            {(Object.keys(STATE_STYLE) as BottleneckState[]).map((s) => (
              <span key={s} className="help row" style={{ gap: 5 }}>
                <span
                  style={{
                    width: 14,
                    height: 14,
                    borderRadius: 3,
                    background: STATE_STYLE[s].color,
                    display: "inline-block",
                  }}
                />
                {STATE_STYLE[s].label}
              </span>
            ))}
          </div>
        </div>
      )}
    </>
  );
}

function WhatIfSection() {
  const { analysisId, analysis, zones, zoneColor } = useAppState();
  const [zone, setZone] = useState<string | null>(null);
  const [mult, setMult] = useState(1.5);
  const [data, setData] = useState<Awaited<ReturnType<typeof api.whatif>> | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (zones.length && !zone) setZone(zones[0]);
  }, [zones, zone]);

  useEffect(() => {
    if (!analysisId || !analysis?.has_artifacts || !zone) return;
    let cancelled = false;
    const handle = window.setTimeout(() => {
      setBusy(true);
      setError(null);
      api
        .whatif(analysisId, zone, mult)
        .then((d) => !cancelled && setData(d))
        .catch((e) => {
          if (!cancelled) {
            setData(null);
            setError(String(e));
          }
        })
        .finally(() => !cancelled && setBusy(false));
    }, 350); // debounce slider scrubbing
    return () => {
      cancelled = true;
      window.clearTimeout(handle);
    };
  }, [analysisId, analysis?.has_artifacts, zone, mult]);

  const fmtW = formatDuration;

  const cal = data?.calibration;

  return (
    <>
      <h2 style={{ margin: "20px 0 4px" }}>What-if capacity (experimental)</h2>
      <p className="help" style={{ marginBottom: 10 }}>
        The zone's <em>actual arrivals</em> and mined service demands, replayed through a
        c-server queue: c is first calibrated to reproduce the measured behavior, then you scale
        it. Arrivals are held fixed — upstream would react in reality — so this builds intuition,
        not guarantees. The baseline-vs-measured overlay is the validity check; zones whose
        waiting comes from regime shifts or external constraints refuse to calibrate on purpose.
      </p>
      <div className="panel">
        <div className="row" style={{ marginBottom: 8 }}>
          {zones.map((z) => (
            <button key={z} className={z === zone ? "primary" : ""} onClick={() => setZone(z)}>
              {z}
            </button>
          ))}
          <label className="help" style={{ display: "inline-flex", alignItems: "center", gap: 8, marginLeft: 12 }}>
            Capacity ×{" "}
            <input
              type="range"
              min={0.5}
              max={2}
              step={0.25}
              value={mult}
              onChange={(e) => setMult(Number(e.target.value))}
              style={{ width: 160 }}
            />
            <strong>{mult.toFixed(2)}</strong>
          </label>
          {busy && <span className="help">computing…</span>}
        </div>
        {error && <div className="notice error">{error}</div>}
        {data && cal && !cal.calibrated && (
          <div className="notice">
            No constant capacity reproduces <strong>{data.zone}</strong>'s measured sojourns
            (calibration error {(cal.relative_error * 100).toFixed(0)}%) — its waiting is driven
            by regime shifts or constraints outside the zone, so a capacity what-if here would be
            fiction. See the queue-model verdicts and drift scores instead.
          </div>
        )}
        {data && cal && cal.calibrated && (
          <>
            <div className="grid tiles" style={{ marginBottom: 10 }}>
              <StatTile label="Calibrated capacity" value={cal.fitted_capacity} hint={`fit error ${(cal.relative_error * 100).toFixed(0)}%`} />
              <StatTile label="What-if capacity" value={data.whatif_capacity} hint={`× ${data.capacity_multiplier.toFixed(2)}`} />
              <StatTile label="Mean wait" value={`${fmtW(data.baseline.mean_wait_s)} → ${fmtW(data.whatif.mean_wait_s)}`} />
              <StatTile label="Peak backlog" value={`${data.baseline.peak_backlog} → ${data.whatif.peak_backlog}`} />
            </div>
            <Plot
              height={280}
              data={[
                {
                  x: data.curves.t,
                  y: data.curves.measured_occ,
                  name: "measured",
                  mode: "lines",
                  line: { color: resolveColor(zoneColor(data.zone)), width: 2 },
                },
                {
                  x: data.curves.t,
                  y: data.curves.baseline_occ,
                  name: "simulated (calibrated c)",
                  mode: "lines",
                  line: { color: resolveColor("var(--baseline)"), width: 1.5, dash: "dot" },
                },
                {
                  x: data.curves.t,
                  y: data.curves.whatif_occ,
                  name: `what-if (c = ${data.whatif_capacity})`,
                  mode: "lines",
                  line: { color: resolveColor("var(--accent)"), width: 2, dash: "dash" },
                },
              ]}
              layout={{
                yaxis: {
                  gridcolor: resolveColor("var(--grid)"),
                  zeroline: false,
                  rangemode: "tozero",
                  title: { text: "cases in zone", font: { size: 11 } },
                },
              }}
            />
            <p className="help">
              Solid: the reconstructed historical baseline. Dotted: the calibrated simulation (should track the
              solid line — that is the validity check). Dashed: the same arrivals under the
              scaled capacity.
            </p>
          </>
        )}
      </div>
    </>
  );
}

/** Load each view on first use, preserving its controls on subsequent visits. */
function FlowView({ index, active, children }: { index: number; active: boolean; children: ReactNode }) {
  const [visited, setVisited] = useState(active);
  useEffect(() => { if (active) setVisited(true); }, [active]);
  useEffect(() => {
    if (!active || !visited) return;
    // Responsive Plotly charts need remeasurement when a hidden view reopens.
    const frame = requestAnimationFrame(() => window.dispatchEvent(new Event("resize")));
    return () => cancelAnimationFrame(frame);
  }, [active, visited]);
  return <section id={`flow-view-${index}`} role="tabpanel" aria-labelledby={`flow-tab-${index}`} hidden={!active}>
    {visited && children}
  </section>;
}

export default function FlowPatterns() {
  const { analysisId, analysis, zones } = useAppState();
  const views = ["Flow & occupancy", "Handovers & ordering", "Queueing diagnostics", "Capacity scenarios"];
  const [view, setView] = useState(0);
  const [stays, setStays] = useState<ZoneStay[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!analysisId || !analysis?.has_artifacts) return;
    let cancelled = false;
    setStays(null);
    setError(null);
    api
      .zoneStays(analysisId)
      .then((r) => !cancelled && setStays(r.rows))
      .catch((e) => !cancelled && setError(String(e)));
    return () => { cancelled = true; };
  }, [analysisId, analysis?.has_artifacts]);

  const byZone = useMemo(() => {
    const m = new Map<string, ZoneStay[]>();
    for (const s of stays ?? []) {
      if (!m.has(s.zone)) m.set(s.zone, []);
      m.get(s.zone)!.push(s);
    }
    return m;
  }, [stays]);

  return (
    <NeedsAnalysis>
      <h1>Flow patterns</h1>
      <p className="help">
        Built from <strong>case-zone stays</strong>: each case's maximal intervals inside a zone
        (movement between places of the same zone is not an exit).
      </p>

      <div className="row flow-tabs" role="tablist" aria-label="Flow pattern views">
        {views.map((label, i) => <button key={label} id={`flow-tab-${i}`} role="tab"
          aria-selected={view === i} aria-controls={`flow-view-${i}`} tabIndex={view === i ? 0 : -1}
          className={view === i ? "primary" : ""} onClick={() => setView(i)}
          onKeyDown={(e) => {
            const n = e.key === "Home" ? 0 : e.key === "End" ? views.length - 1 :
              e.key === "ArrowRight" ? (i + 1) % views.length : e.key === "ArrowLeft" ? (i + views.length - 1) % views.length : null;
            if (n !== null) { e.preventDefault(); setView(n); document.getElementById(`flow-tab-${n}`)?.focus(); }
          }}>{label}{i === 3 ? " · experimental" : ""}</button>)}
      </div>
      {error && <div className="notice error">{error}</div>}
      <FlowView key={`${analysisId}:0`} index={0} active={view === 0}>
      {stays && <SpectrumSection byZone={byZone} />}

      <h2 style={{ margin: "20px 0 4px" }}>Cumulative flow diagrams</h2>
      <p className="help" style={{ marginBottom: 10 }}>
        Solid line: cumulative stay entries. Dotted line: cumulative stay exits. Their difference
        is the number of open case-zone stays. A widening band means more stays are opening than
        closing. Repeated visits can count the same case more than once; curve separation alone
        does not establish a capacity problem or an individual case duration.
      </p>
      {!stays && !error && <SkeletonPanel rows={4} />}
      {stays && (
        <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 430px), 1fr))" }}>
          {zones.map((z) => (
            <CfdPanel key={z} zone={z} stays={byZone.get(z) ?? []} />
          ))}
        </div>
      )}

      </FlowView>
      <FlowView key={`${analysisId}:1`} index={1} active={view === 1}>
      <h2 style={{ margin: "20px 0 4px" }}>Batch &amp; overtaking fingerprint</h2>
      <p className="help" style={{ marginBottom: 10 }}>
        One dot per completed stay: when the case <em>entered</em> the zone (x) vs. when it{" "}
        <em>left</em> (y). Height above the dashed diagonal is time spent in the zone.{" "}
        <strong>Horizontal rows</strong> show stays ending at the same recorded time, a possible batching pattern.{" "}
        <strong>A dot lower than dots to its left</strong> is overtaking — a case that entered
        later but left earlier (non-FIFO service).
      </p>
      {stays && (
        <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 430px), 1fr))" }}>
          {zones.map((z) => (
            <FingerprintPanel key={z} zone={z} stays={byZone.get(z) ?? []} />
          ))}
        </div>
      )}

      <HandoverSection />
      </FlowView>
      <FlowView key={`${analysisId}:2`} index={2} active={view === 2}>
      <QueueingSection />
      <BottleneckSection />
      </FlowView>
      <FlowView key={`${analysisId}:3`} index={3} active={view === 3}>
      <WhatIfSection />
      </FlowView>
    </NeedsAnalysis>
  );
}
