import { useRef, useState } from "react";
import { api, type MetricCatalog } from "../api";
import { formatMetricValue } from "../lib/metricPresentation";
import { useResult } from "../lib/useResult";
import { useAppState } from "../state";
import { DataTable, NeedsAnalysis, ZoneChip } from "../components/shared";
import TrendChart from "../components/TrendChart";
import ConfiguredTrendPlot, { type TrendPlotConfig } from "../components/ConfiguredTrendPlot";

function ComparePanel({ catalog }: { catalog: MetricCatalog }) {
  const { windows } = catalog;
  const { analysisId } = useAppState();
  const half = Math.floor(windows.length / 2);
  const [aFrom, setAFrom] = useState(0);
  const [aTo, setATo] = useState(Math.max(0, half - 1));
  const [bFrom, setBFrom] = useState(half);
  const [bTo, setBTo] = useState(windows.length - 1);
  const [requested, setRequested] = useState<{ key: string; attempt: number } | null>(null);
  const periodKey = JSON.stringify([analysisId, windows[aFrom], windows[aTo], windows[bFrom], windows[bTo]]);
  const response = useResult(requested?.key === periodKey ? JSON.stringify(requested) : null,
    () => api.comparePeriods(analysisId!, windows[aFrom], windows[aTo], windows[bFrom], windows[bTo]));
  const result = response.status === "success" ? response.data : null;
  const busy = response.status === "loading";
  const error = response.status === "error" ? response.error : null;

  const sel = (value: number, set: (v: number) => void) => (
    <select value={value} onChange={(e) => set(Number(e.target.value))}>
      {windows.map((w, i) => (
        <option key={w} value={i}>
          {w.slice(0, 10)}
        </option>
      ))}
    </select>
  );

  const run = () => {
    if (analysisId) setRequested((previous) => ({ key: periodKey, attempt: (previous?.attempt ?? 0) + 1 }));
  };

  const fmtPct = (r: number | null) =>
    r === null ? "large" : `${r > 0 ? "+" : ""}${(r * 100).toFixed(0)}%`;

  return (
    <div className="panel">
      <h2>Compare two periods</h2>
      <p className="help">
        Slice the timeline into "before" and "after" (e.g. around a change point) and compare
        every zone metric between the slices. The statistical check allows for testing many
        comparisons at once. Passing it suggests evidence of a difference; it does not
        measure practical importance or explain a cause. This comparison covers all zones and metrics, independently of the selection above.
      </p>
      <div className="row" style={{ marginBottom: 8 }}>
        <span className="help">Period A</span>
        {sel(aFrom, setAFrom)} <span className="help">→</span> {sel(aTo, setATo)}
        <span className="help" style={{ marginLeft: 12 }}>
          Period B
        </span>
        {sel(bFrom, setBFrom)} <span className="help">→</span> {sel(bTo, setBTo)}
        <button className="primary" onClick={run} disabled={busy}>
          {busy ? "Comparing…" : "Compare"}
        </button>
      </div>
      {error && <div className="notice error">{error}</div>}
      {result && (
        <>
          {result.rows.length === 0 ? (
            <p className="help">Not enough windows in one of the slices.</p>
          ) : (
            <DataTable
              rows={result.rows.slice(0, 30).map((r) => ({
                zone: r.zone,
                metric: r.metric_label,
                "A mean": formatMetricValue(r.mean_a, catalog.metrics.find((m) => m.name === r.metric)),
                "B mean": formatMetricValue(r.mean_b, catalog.metrics.find((m) => m.name === r.metric)),
                change: r,
                significant: r,
              }))}
              format={{
                zone: (v) => <ZoneChip zone={String(v)} />,
                change: (v) => {
                  const r = v as (typeof result.rows)[number];
                  return (
                    <span style={{ fontWeight: Math.abs(r.rel_delta ?? 1) >= 0.5 ? 700 : 400 }}>
                      {fmtPct(r.rel_delta)}
                    </span>
                  );
                },
                significant: (v) => {
                  const r = v as (typeof result.rows)[number];
                  return r.significant ? (
                    <span className="badge warn">Passes statistical check</span>
                  ) : (
                    <span className="help">–</span>
                  );
                },
              }}
            />
          )}
          <p className="help" style={{ marginTop: 6 }}>
            Top 30 of {result.rows.length} comparisons, most significant first.
          </p>
        </>
      )}
    </div>
  );
}

function TrendsWorkspace({ catalog }: { catalog: MetricCatalog }) {
  const { analysisId, zones } = useAppState();
  const nextId = useRef(2);
  const [plots, setPlots] = useState<TrendPlotConfig[]>([{
    id: "plot-1", title: "Zone occupancy over time", pairs: catalog.zones.map((zone) => ({ zone, metric: "token_present_end" })),
    normalize: false, observations: false, local: true, overall: false, strictness: 50,
  }]);
  const drift = useResult(`drift:${analysisId}`, () => api.drift(analysisId!));
  return <>
    <div className="row" style={{ justifyContent: "space-between", marginBottom: 16 }}>
      <p className="help">Each plot analyzes exactly its selected zone–metric pairs. Configure local and overall changes independently.</p>
      <button className="primary" onClick={() => {
        const id = nextId.current++;
        setPlots((previous) => [...previous, { id: `plot-${id}`, title: `Plot ${id}`, pairs: [],
          normalize: false, observations: false, local: true, overall: false, strictness: 50 }]);
      }}>Add Plot</button>
    </div>
    {!plots.length && <p>No plots. Use Add Plot to create one.</p>}
    {plots.map((plot) => <ConfiguredTrendPlot key={plot.id} config={plot} catalog={catalog}
      onChange={(next) => setPlots((previous) => previous.map((p) => p.id === next.id ? next : p))}
      onRemove={() => setPlots((previous) => previous.filter((p) => p.id !== plot.id))} />)}
    <section className="panel" aria-label="Zone drift scores">
      <h2>Zone drift scores</h2>
      <p className="help">How different is a zone’s behavior on either side of a window? Each score compares the {drift.status === "success" ? drift.data.half_window : 5} preceding analysis windows with {drift.status === "success" ? drift.data.half_window : 5} windows starting at the plotted window, using energy distance across the zone’s numeric metrics.</p>
      <ul className="help">
        <li>Higher scores indicate larger differences between the two groups of windows; scores near zero indicate similar feature distributions. Scores are dimensionless, not percentages, probabilities, or significance tests.</li>
        <li>Peaks suggest periods worth inspecting in the metric plots above. They do not identify a cause or automatically define a PELT change point.</li>
        <li>Gaps at timeline edges mean there are too few preceding or following windows. A zone with no varying metrics has no score; missing scores do not mean zero drift.</li>
      </ul>
      <details><summary>How drift scores are calculated</summary>
        <p className="help">This separate analysis uses all zones and eligible numeric zone metrics, independently of plot selections, normalization, and change-point strictness. Global alignment metrics are excluded. Within each zone, missing feature values are filled with that metric’s whole-history mean, constant metrics are dropped, and remaining metrics are standardized using whole-history population standard deviations. Feature vectors are divided by the square root of the number of retained metrics before computing energy distance.</p>
        <p className="help">This is retrospective: the score uses later windows and whole-history preprocessing. It is not an online alert or forecast. Metric coverage and correlations affect the scores, so cross-zone differences require inspection rather than an absolute ranking.</p>
      </details>
      {drift.status === "loading" && <p role="status">Loading drift scores…</p>}
      {drift.status === "error" && <div role="alert" className="notice error">Drift scores unavailable: {drift.error}</div>}
      {drift.status === "success" && <TrendChart rows={drift.data.rows.filter((r) => zones.includes(r.zone)).map((r) => ({ zone: r.zone, window_start: r.window_start, value: r.drift_score }))} metricLabel="Drift score" />}
    </section>
    {catalog.windows.length >= 6 && <ComparePanel key={analysisId} catalog={catalog} />}
  </>;
}

export default function Trends() {
  const { analysisId, analysis } = useAppState();
  const ready = Boolean(analysisId && analysis?.id === analysisId && analysis.has_artifacts);
  const response = useResult(ready ? `catalog:${analysisId}` : null, () => api.metricCatalog(analysisId!));
  return <NeedsAnalysis>
    <h1>Trends &amp; Change points</h1>
    <p className="help">Explore reconstructed metrics over {analysis?.timeframe_label.toLowerCase()} windows. PELT uses squared-error cost and the existing 0–100 strictness search.
      Change times identify the first window of a new segment in retrospective analysis, not an online detection time.</p>
    {response.status === "loading" && <p role="status">Loading metric catalog…</p>}
    {response.status === "error" && <div role="alert" className="notice error">Metric catalog unavailable: {response.error}</div>}
    {response.status === "success" && <TrendsWorkspace key={analysisId} catalog={response.data} />}
  </NeedsAnalysis>;
}
