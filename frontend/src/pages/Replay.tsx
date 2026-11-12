/** Animated token-flow replay: tokens moving through the net over replayed
 * time, with a synchronized zone-occupancy timeline below. Built entirely
 * from the token-place intervals the alignment replay already computes. */

import { useEffect, useMemo, useRef, useState } from "react";
import { api, type BottleneckState, type ModelGraph, type ZoneStay } from "../api";
import { STATE_STYLE } from "../lib/states";
import { useAppState } from "../state";
import PetriNetView from "../components/PetriNetView";
import TrendChart, { type TrendRow } from "../components/TrendChart";
import { NeedsAnalysis, ZoneChip } from "../components/shared";
import { resolveColor } from "../lib/plotTheme";
import { indexReplayPlaces, indexedTokenCounts, indexedCasesAtPlace, upperBound, type ReplayInterval as Interval } from "../lib/replayIndex";

const STEPS = 240;

/** Parse backend timestamps ("2024-01-01 08:09:00[+01:00]") robustly:
 * normalize to ISO-8601 and treat the log's wall-clock time as the timeline
 * (offsets stripped), so replay math and display are engine- and
 * viewer-timezone-independent. */
function parseWallClock(s: string): number {
  return Date.parse(s.slice(0, 19).replace(" ", "T") + "Z");
}

/** One case's journey through the zones: a lane per visited
 * zone, a bar per case-zone stay, cursor at the current replay moment. */
function CaseJourney({
  caseId,
  stays,
  t0,
  t1,
  now,
}: {
  caseId: string;
  stays: ZoneStay[];
  t0: number;
  t1: number;
  now: number;
}) {
  const { zones, zoneColor } = useAppState();
  const W = 900;
  const LANE_H = 26;
  const LABEL_W = 150;
  const span = Math.max(1, t1 - t0);
  const x = (t: number) => LABEL_W + ((t - t0) / span) * (W - LABEL_W - 10);
  const visited = zones.filter((z) => stays.some((s) => s.zone === z));
  const H = visited.length * LANE_H + 26;
  const fmt = (ms: number) => new Date(ms).toISOString().slice(0, 16).replace("T", " ");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto", display: "block" }} role="img" aria-label={`Journey of case ${caseId}`}>
      {visited.map((z, i) => (
        <g key={z}>
          <text x={LABEL_W - 8} y={i * LANE_H + LANE_H / 2 + 4} textAnchor="end" style={{ fontSize: 11, fill: "var(--text-2)" }}>
            {z}
          </text>
          <line x1={LABEL_W} y1={i * LANE_H + LANE_H / 2} x2={W - 10} y2={i * LANE_H + LANE_H / 2} stroke="var(--grid)" strokeWidth={1} />
          {stays
            .filter((s) => s.zone === z)
            .map((s, j) => {
              const a = parseWallClock(s.entry_ts);
              const b = s.exit_ts ? parseWallClock(s.exit_ts) : t1;
              return (
                <rect
                  key={j}
                  x={x(a)}
                  y={i * LANE_H + 5}
                  width={Math.max(2, x(b) - x(a))}
                  height={LANE_H - 10}
                  rx={4}
                  fill={resolveColor(zoneColor(z))}
                  opacity={0.85}
                >
                  <title>{`${z}: ${fmt(a)} → ${s.exit_ts ? fmt(b) : "open"}`}</title>
                </rect>
              );
            })}
        </g>
      ))}
      <line x1={x(now)} y1={0} x2={x(now)} y2={visited.length * LANE_H} stroke="var(--accent)" strokeWidth={1.5} strokeDasharray="4 3" />
      <text x={LABEL_W} y={H - 6} style={{ fontSize: 10, fill: "var(--muted)" }}>
        {fmt(t0)}
      </text>
      <text x={W - 10} y={H - 6} textAnchor="end" style={{ fontSize: 10, fill: "var(--muted)" }}>
        {fmt(t1)}
      </text>
    </svg>
  );
}

export default function Replay() {
  const { analysisId, analysis, zones, zoneColor } = useAppState();
  const [graph, setGraph] = useState<ModelGraph | null>(null);
  const [intervals, setIntervals] = useState<Interval[]>([]);
  const [step, setStep] = useState(() => {
    // deep-linkable replay moment: ?step=<0..240> (also used for screenshots)
    const s = Number(new URLSearchParams(window.location.search).get("step"));
    return Number.isFinite(s) && s > 0 && s <= STEPS ? Math.floor(s) : 0;
  });
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [progress, setProgress] = useState<{ loaded: number; total: number } | null>(null);
  const [journeyError, setJourneyError] = useState<string | null>(null);
  // deep-linkable: ?place=<name> preselects the case inspector (demo/video)
  const [selectedPlace, setSelectedPlace] = useState<string | null>(
    () => new URLSearchParams(window.location.search).get("place"),
  );
  const [selectedCase, setSelectedCase] = useState<string | null>(null);
  const [stays, setStays] = useState<ZoneStay[] | null>(null);
  const [bottlenecks, setBottlenecks] = useState<{
    windows: number[];
    byZone: Record<string, BottleneckState[]>;
  } | null>(null);
  const timer = useRef<number | null>(null);

  // bottleneck states drive the zone halos while the replay runs (B6)
  useEffect(() => {
    if (!analysisId || !analysis?.has_artifacts) return;
    let active = true;
    setBottlenecks(null);
    api
      .bottlenecks(analysisId)
      .then((b) => {
        if (!active) return;
        const byZone: Record<string, BottleneckState[]> = {};
        for (const z of b.zones) byZone[z.zone] = z.states;
        setBottlenecks({ windows: b.windows.map(parseWallClock), byZone });
      })
      .catch(() => { if (active) setBottlenecks(null); });
    return () => { active = false; };
  }, [analysisId, analysis?.has_artifacts]);

  // Read only the inspected case, with cancellation on selection changes.
  useEffect(() => {
    setStays(null);
    if (!analysisId || !selectedCase) return;
    const controller = new AbortController();
    setJourneyError(null);
    api
      .caseStays(analysisId, selectedCase, controller.signal)
      .then((r) => { if (!controller.signal.aborted) setStays(r.rows); })
      .catch((e) => { if (!controller.signal.aborted) setJourneyError(String(e)); });
    return () => controller.abort();
  }, [analysisId, selectedCase]);

  useEffect(() => {
    const controller = new AbortController();
    setIntervals([]);
    setGraph(null);
    setStays(null);
    setSelectedCase(null);
    setJourneyError(null);
    setPlaying(false);
    setError(null);
    setLoading(true);
    setProgress(null);
    if (!analysisId || !analysis?.has_artifacts) return;
    Promise.all([api.modelGraph(analysis.dataset_id), api.tokenIntervals(analysisId, controller.signal, (loaded, total) => {
      if (!controller.signal.aborted) setProgress({ loaded, total });
    })])
      .then(([modelGraph, r]) => {
        if (controller.signal.aborted) return;
        setGraph(modelGraph);
        setIntervals(
          r.rows.map((row) => ({
            case_id: String(row.case_id),
            place: String(row.place),
            zone: row.zone ? String(row.zone) : null,
            produced: parseWallClock(String(row.produced_ts)),
            consumed: row.consumed_ts ? parseWallClock(String(row.consumed_ts)) : null,
          })),
        );
      })
      .catch((e) => { if (!controller.signal.aborted) setError(String(e)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [analysisId, analysis?.has_artifacts, analysis?.dataset_id]);

  const { t0, times } = useMemo(() => {
    if (!intervals.length) return { t0: 0, times: [] as number[] };
    let lo = Infinity;
    let hi = -Infinity;
    for (const iv of intervals) {
      lo = Math.min(lo, iv.produced);
      hi = Math.max(hi, iv.consumed ?? iv.produced);
    }
    const times = Array.from({ length: STEPS + 1 }, (_, i) => lo + ((hi - lo) * i) / STEPS);
    return { t0: lo, times };
  }, [intervals]);

  const now = times[step] ?? t0;

  const placeIndex = useMemo(() => indexReplayPlaces(intervals), [intervals]);
  const tokenCounts = useMemo(() => indexedTokenCounts(placeIndex, now), [placeIndex, now]);

  // O((n + zones·steps)·log n) event sweep: per zone, sorted produced/consumed
  // timestamp arrays once, then occupancy(t) = #produced≤t − #consumed≤t.
  const occupancyRows: TrendRow[] = useMemo(() => {
    const produced: Record<string, number[]> = {};
    const consumed: Record<string, number[]> = {};
    for (const iv of intervals) {
      if (!iv.zone) continue;
      (produced[iv.zone] ??= []).push(iv.produced);
      if (iv.consumed !== null) (consumed[iv.zone] ??= []).push(iv.consumed);
    }
    for (const z of Object.keys(produced)) produced[z].sort((a, b) => a - b);
    for (const z of Object.keys(consumed)) consumed[z].sort((a, b) => a - b);

    const rows: TrendRow[] = [];
    for (const zone of zones) {
      const p = produced[zone] ?? [];
      const c = consumed[zone] ?? [];
      for (const t of times) {
        rows.push({
          zone,
          window_start: new Date(t).toISOString(),
          value: upperBound(p, t) - upperBound(c, t),
        });
      }
    }
    return rows;
  }, [intervals, times, zones]);

  const zoneOf = useMemo(() => {
    const rec: Record<string, string> = {};
    if (analysis) {
      for (const [zone, places] of Object.entries(analysis.zone_places))
        for (const p of places) rec[p] = zone;
    }
    return rec;
  }, [analysis]);

  const zoneStatesNow = useMemo(() => {
    if (!bottlenecks || !bottlenecks.windows.length) return undefined;
    const idx = Math.max(0, upperBound(bottlenecks.windows, now) - 1);
    const out: Record<string, BottleneckState> = {};
    for (const [zone, states] of Object.entries(bottlenecks.byZone)) {
      if (states[idx]) out[zone] = states[idx];
    }
    return out;
  }, [bottlenecks, now]);

  const casesAtPlace = useMemo(() => indexedCasesAtPlace(placeIndex, selectedPlace, now), [placeIndex, selectedPlace, now]);

  const caseStays = useMemo(
    () => (selectedCase && stays ? stays.filter((s) => s.case_id === selectedCase) : []),
    [selectedCase, stays],
  );

  const zoneTotals = useMemo(() => {
    const totals: Record<string, number> = {};
    for (const [place, c] of Object.entries(tokenCounts)) {
      const zone = zoneOf[place];
      if (zone) totals[zone] = (totals[zone] ?? 0) + c;
    }
    return totals;
  }, [tokenCounts, zoneOf]);

  useEffect(() => {
    if (!playing) {
      if (timer.current) window.clearInterval(timer.current);
      return;
    }
    timer.current = window.setInterval(() => {
      setStep((s) => Math.min(s + speed, STEPS));
    }, 80);
    return () => {
      if (timer.current) window.clearInterval(timer.current);
    };
  }, [playing, speed]);

  useEffect(() => {
    if (step >= STEPS && playing) setPlaying(false);
  }, [step, playing]);

  return (
    <NeedsAnalysis>
      <h1>Token replay</h1>
      <p className="help">
        Every token's stay in every place, reconstructed by alignment replay, animated over time.
        Node size = reconstructed open tokens in that place at the selected historical moment. The timeline below shows per-zone
        occupancy; the blue cursor is the current moment.
      </p>
      {error && <div className="notice error">{error}</div>}
      {graph && intervals.length > 0 && (
        <>
          <p className="help" role="status">Complete history: {intervals.length.toLocaleString()} token-place intervals.</p>
          <div className="panel">
            <div className="row" data-tour-target="replay-controls" style={{ marginBottom: 10 }}>
              <button className="primary" onClick={() => setPlaying(!playing)}>
                {playing ? "⏸ Pause" : "▶ Play"}
              </button>
              <button onClick={() => { setStep(0); setPlaying(false); }}>⏮ Reset</button>
              <label className="help">
                Speed{" "}
                <select value={speed} onChange={(e) => setSpeed(Number(e.target.value))}>
                  <option value={1}>1×</option>
                  <option value={2}>2×</option>
                  <option value={4}>4×</option>
                </select>
              </label>
              <input
                type="range"
                min={0}
                max={STEPS}
                value={step}
                onChange={(e) => { setStep(Number(e.target.value)); setPlaying(false); }}
                style={{ flex: 1, minWidth: 200 }}
              />
              <strong style={{ fontVariantNumeric: "tabular-nums" }}>
                {new Date(now).toISOString().slice(0, 16).replace("T", " ")}
              </strong>
            </div>
            <div className="row" style={{ marginBottom: 8 }}>
              {zones.map((z) => {
                const st = zoneStatesNow?.[z];
                return (
                  <span key={z} className="help">
                    <ZoneChip zone={z} /> <strong>{zoneTotals[z] ?? 0}</strong>
                    {st && st !== "flowing" && (
                      <span
                        title={STATE_STYLE[st].label}
                        style={{ color: STATE_STYLE[st].color, fontWeight: 700, marginLeft: 4 }}
                      >
                        · {st}
                      </span>
                    )}
                  </span>
                );
              })}
            </div>
            <PetriNetView
              graph={graph}
              zoneOf={zoneOf}
              zoneColorOf={zoneColor}
              tokenCounts={tokenCounts}
              zoneStates={zoneStatesNow}
              onPlaceClick={(p) => {
                setSelectedPlace(p);
                setSelectedCase(null);
              }}
              height={400}
            />
            <p className="help" style={{ margin: "6px 0 0" }}>
              Click a place to see which cases are sitting there right now, then click a case to
              follow its whole journey.
            </p>
          </div>

          {selectedPlace && (
            <div className="panel">
              <div className="row" style={{ justifyContent: "space-between" }}>
                <h2 style={{ margin: 0 }}>
                  Cases in <code>{selectedPlace}</code> at{" "}
                  {new Date(now).toISOString().slice(0, 16).replace("T", " ")}
                </h2>
                <button onClick={() => { setSelectedPlace(null); setSelectedCase(null); }}>✕ Close</button>
              </div>
              {casesAtPlace.length === 0 ? (
                <p className="help">No tokens here at this moment — scrub the timeline or pick another place.</p>
              ) : (
                <div className="row" style={{ marginTop: 8, flexWrap: "wrap", gap: 6 }}>
                  {casesAtPlace.slice(0, 30).map((c) => (
                    <button
                      key={c}
                      className={c === selectedCase ? "primary" : ""}
                      onClick={() => setSelectedCase(c)}
                    >
                      {c}
                    </button>
                  ))}
                  {casesAtPlace.length > 30 && (
                    <span className="help">+{casesAtPlace.length - 30} more</span>
                  )}
                </div>
              )}
              {selectedCase && journeyError && <p role="alert">Journey unavailable: {journeyError}</p>}
              {selectedCase && stays === null && !journeyError && <p className="help">Loading journey…</p>}
              {selectedCase && stays !== null && caseStays.length > 0 && (
                <div style={{ marginTop: 12 }}>
                  <h3 style={{ marginBottom: 6 }}>Journey of case {selectedCase}</h3>
                  <CaseJourney
                    caseId={selectedCase}
                    stays={caseStays}
                    t0={times[0] ?? t0}
                    t1={times[times.length - 1] ?? t0}
                    now={now}
                  />
                  <p className="help">
                    One lane per zone the case visited; the dashed line is the current replay
                    moment. Long bars in one zone are exactly the waiting the flow-pattern views
                    aggregate.
                  </p>
                </div>
              )}
            </div>
          )}
          <div className="panel">
            <h2>Zone occupancy over time</h2>
            <TrendChart
              rows={occupancyRows}
              metricLabel="open tokens"
              cursorTime={new Date(now).toISOString()}
            />
          </div>
        </>
      )}
      {loading && !error && <p role="status" className="help">Loading complete token history…{progress && ` ${progress.loaded.toLocaleString()} / ${progress.total.toLocaleString()} intervals (${progress.total ? Math.round(100 * progress.loaded / progress.total) : 100}%).`}</p>}
      {!loading && intervals.length === 0 && !error && <p className="help">No token intervals in this analysis.</p>}
    </NeedsAnalysis>
  );
}
