import { useState } from "react";
import { api, type MetricCatalog, type TrendSelectionRequest, type ZoneMetricPair } from "../api";
import { useAppState } from "../state";
import { useResult } from "../lib/useResult";
import { metricUnit } from "../lib/metricPresentation";
import { Plot, resolveColor, themedLayout } from "../lib/plot";
import { DataTable, ZoneChip } from "./shared";
import TrendChart, { pairKey, type BandRow, type TrendSeries } from "./TrendChart";
import Heatmap from "./Heatmap";
import Disclosure from "./Disclosure";
import { downloadCsv } from "../lib/download";

export interface TrendPlotConfig {
  id: string;
  title: string;
  pairs: ZoneMetricPair[];
  normalize: boolean;
  observations: boolean;
  local: boolean;
  overall: boolean;
  strictness: number;
}
const sameTime = (a: string, b: string) => Date.parse(a.replace(" ", "T")) === Date.parse(b.replace(" ", "T"));

export default function ConfiguredTrendPlot({ config, catalog, onChange, onRemove }: {
  config: TrendPlotConfig; catalog: MetricCatalog; onChange: (next: TrendPlotConfig) => void; onRemove: () => void;
}) {
  const { analysisId, zoneColor } = useAppState();
  const [zone, setZone] = useState(catalog.zones[0] ?? "");
  const [metric, setMetric] = useState("token_present_end");
  const [chosenTime, setChosenTime] = useState("");
  const [expanded, setExpanded] = useState(false);
  const [sections, setSections] = useState<Record<string, boolean>>({});
  const disclosure = (name: string) => ({ expanded: sections[name] ?? false,
    onExpandedChange: (open: boolean) => setSections(previous => ({ ...previous, [name]: open })) });
  const patch = (update: Partial<TrendPlotConfig>) => onChange({ ...config, ...update });
  const request: TrendSelectionRequest = { pairs: config.pairs, normalize: config.normalize,
    local_enabled: config.local, overall_enabled: config.overall, cp_strictness: config.strictness };
  const key = config.pairs.length ? JSON.stringify([analysisId, config.id, request]) : null;
  const response = useResult(key, () => api.selectedTrends(analysisId!, request), 200);
  const data = response.status === "success" ? response.data : null;
  const duplicate = config.pairs.some((p) => p.zone === zone && p.metric === metric);
  const metadata = (name: string) => catalog.metrics.find((m) => m.name === name);
  const choices = config.pairs.map((p): TrendSeries => ({ ...p, label: `${p.zone} · ${metadata(p.metric)?.label ?? p.metric}`,
    unit: metricUnit(metadata(p.metric), config.normalize) }));
  const groups = new Map<string, TrendSeries[]>();
  for (const series of choices) groups.set(series.unit, [...(groups.get(series.unit) ?? []), series]);
  const rawMixed = !config.normalize && groups.size > 1;
  const local = config.local ? data?.local_changepoints ?? [] : [];
  const overall = config.overall ? data?.overall : null;
  const changes = overall?.changepoints ?? [];
  const selectedTime = changes.some((cp) => cp.timestamp === chosenTime) ? chosenTime : changes[0]?.timestamp ?? "";
  const contributions = overall?.contributions.filter((c) => c.timestamp === selectedTime) ?? [];
  const positive = contributions.filter((c) => Number.isFinite(c.contribution_pct) && c.contribution_pct > 0 && c.jump_score > 0)
    .sort((a, b) => b.contribution_pct - a.contribution_pct).slice(0, 10);
  const coverage = overall?.contribution_details.find((d) => sameTime(d.timestamp, selectedTime));
  const wantsCi = !config.normalize && config.pairs.some((p) => p.metric === "case_avg_duration_completed");
  const ci = useResult(wantsCi ? `ci:${analysisId}` : null, () => api.trendCi(analysisId!));
  const bands: BandRow[] | undefined = ci.status === "success" ? ci.data.rows.map((b) => ({ ...b,
    metric: "case_avg_duration_completed", lo: b.lo_s, hi: b.hi_s })) : undefined;
  const detectedRows: Record<string, unknown>[] = [
    ...local.map((cp) => ({ type: "Local", timestamp: cp.timestamp, zone: cp.zone, metric: cp.metric_label,
      selection: "Individual series", order: cp.cp_order })),
    ...changes.map((cp) => ({ type: "Overall", timestamp: cp.timestamp, zone: "Selected collection", metric: `${cp.n_series} standardized components`,
      selection: cp.selection_label, order: cp.cp_order })),
  ].sort((a, b) => String(a.timestamp).localeCompare(String(b.timestamp)));

  return <section className="panel" data-testid="configured-plot" data-plot-id={config.id} aria-label={config.title || "Untitled trend plot"}>
    <div className="row" style={{ justifyContent: "space-between", gap: 12 }}>
      {expanded ? <label>Plot title <input value={config.title} onChange={(e) => patch({ title: e.target.value })} style={{ minWidth: 200, fontWeight: 600 }} /></label> : <h2>{config.title || "Untitled trend plot"}</h2>}
      <div className="row">
        <button aria-expanded={expanded} aria-controls={`${config.id}-controls`} onClick={() => setExpanded(!expanded)}>
          {expanded ? "Hide plot settings" : "Edit plot settings"}
        </button>
        {expanded && <button onClick={onRemove}>Remove plot</button>}
      </div>
    </div>
    <p className="help">{config.pairs.length} selected series across {new Set(config.pairs.map(p => p.zone)).size} zones · {config.normalize ? "Normalized" : "Original units"}</p>
    <div id={`${config.id}-controls`} hidden={!expanded}>
    <div className="row" style={{ marginTop: 14, gap: 12 }}>
      <label>Zone <select value={zone} onChange={(e) => setZone(e.target.value)}>{catalog.zones.map((z) => <option key={z}>{z}</option>)}</select></label>
      <label>Metric <select value={metric} onChange={(e) => setMetric(e.target.value)}>{catalog.metrics.map((m) => <option key={m.name} value={m.name}>{m.label} · {m.unit_label}</option>)}</select></label>
      <button disabled={duplicate || !zone || !metadata(metric)} onClick={() => patch({ pairs: [...config.pairs, { zone, metric }] })}>Add series</button>
      {duplicate && <span className="help">This zone–metric pair is already selected.</span>}
    </div>
    <p className="help">{metadata(metric)?.description} <code>{metric}</code> · {metadata(metric)?.unit_label}</p>
    <h3>Selected series · {config.pairs.length}</h3>
    <div data-testid="selected-pairs" className="series-selection">
      {config.pairs.map((p) => <div key={pairKey(p.zone, p.metric)} className="series-selection-card">
        <ZoneChip zone={p.zone} />
        <span className="series-metric">{metadata(p.metric)?.label ?? p.metric}<small>{metadata(p.metric)?.unit_label}</small></span>
        <button title="Remove series" aria-label={`Remove ${p.zone} ${p.metric}`} onClick={() => patch({ pairs: config.pairs.filter((q) => pairKey(q.zone, q.metric) !== pairKey(p.zone, p.metric)) })}>×</button>
      </div>)}
    </div>
    <div className="row" style={{ gap: 16 }}>
      <label><input type="checkbox" checked={config.normalize} onChange={(e) => patch({ normalize: e.target.checked })} /> Normalize display</label>
      <label><input type="checkbox" checked={config.observations} onChange={(e) => patch({ observations: e.target.checked })} /> Show observations</label>
      <label><input type="checkbox" checked={config.local} onChange={(e) => patch({ local: e.target.checked })} /> Show Local Change Points</label>
      <label><input type="checkbox" checked={config.overall} onChange={(e) => patch({ overall: e.target.checked })} /> Show Overall Change Points</label>
      <label>Change-point strictness (0–100) <input type="number" min={0} max={100} value={config.strictness} style={{ width: 65 }}
        onChange={(e) => patch({ strictness: Math.max(0, Math.min(100, Math.round(Number(e.target.value)))) })} /></label>
    </div>
    <p className="help">Higher strictness requests fewer PELT candidates; marker locations need not form nested sets. Display normalization does not change detection.
      Overall detection always averages individually standardized usable components. Results are retrospective changes in reconstructed metrics, not causal explanations.</p>
    {rawMixed && <p className="notice" data-testid="mixed-units">Mixed units: raw series are separated by unit below. Enable normalization to overlay all selected series.</p>}
    {config.pairs.some((p) => p.metric.startsWith("alignment_")) && <p className="help">Global conformance is repeated across zones. Selecting it for multiple zones repeats that signal's weight in the aggregate.</p>}
    </div>
    {!key && <p role="status">No selected series. Add a zone–metric pair.</p>}
    {response.status === "loading" && <p role="status">Loading plot analysis…</p>}
    {response.status === "error" && <div role="alert" className="notice error">Plot analysis unavailable: {response.error}</div>}
    {data && <>
      <div className="row" style={{ justifyContent: "flex-end" }}><button onClick={() => {
        const rows = data.rows.map((r) => ({ analysis_id: analysisId, ...r,
          unit: metricUnit(metadata(r.metric), config.normalize), normalized: config.normalize }));
        downloadCsv(rows, ["analysis_id", "zone", "metric", "window_start", "value", "unit", "normalized"], `${config.title || "trend"}-data`);
      }}>Download plot data (CSV)</button></div>
      <p className="help" data-testid="marker-legend" hidden={!expanded}>◆ Local: a diamond on the affected series. │ Overall: a solid vertical line for the selected collection. Line color identifies the zone; legend labels and hover identify the metric.</p>
      <div data-testid="trend-charts">{[...groups].map(([unit, definitions]) => {
        const keys = new Set(definitions.map((d) => pairKey(d.zone, d.metric)));
        const rows = data.rows.filter((r) => keys.has(pairKey(r.zone, r.metric)));
        return <div key={unit} data-unit={unit}>
          {rawMixed && <h3>Trends — {unit}</h3>}
          <TrendChart rows={rows} series={definitions} observations={config.observations} metricLabel={unit}
            changepoints={local} aggregateChangepoints={changes}
            bands={!config.normalize ? bands?.filter((b) => keys.has(pairKey(b.zone, "case_avg_duration_completed"))) : undefined} />
        </div>;
      })}</div>
      <div id={`${config.id}-details`}>
      {wantsCi && <p className="help">Completed case-stay mean: shaded 95% confidence intervals where supported (seconds).</p>}
      {ci.status === "error" && <p role="alert">Confidence intervals unavailable: {ci.error}</p>}
      {data.series.filter((s) => s.status !== "usable").map((s) => <p className="help" key={pairKey(s.zone, s.metric)}>
        {s.zone} · {metadata(s.metric)?.label}: {s.status === "constant" ? "Constant series" : "Insufficient observations"} ({s.n_observations} usable windows; at least 8 required). Excluded from overall detection.
      </p>)}
      {!config.local ? <p>Local change-point analysis disabled.</p> : local.length === 0 && <p>No local change points detected in eligible series with these settings.</p>}
      {!config.overall && <p>Overall change-point analysis disabled.</p>}
      {overall?.status === "insufficient_components" && <p>Overall analysis needs at least two usable components. A single component is redundant with local analysis; constant or insufficient series are excluded.</p>}
      {overall?.status === "insufficient_observations" && <p>Insufficient observations in the overall signal.</p>}
      {overall?.status === "constant" && <p>The overall signal is constant; component changes can cancel. No overall boundaries detected.</p>}
      {overall?.status === "no_changes" && <p>No overall change points detected with these settings.</p>}
      <Disclosure {...disclosure("detected-changes")} data-testid="detected-changes" summary={`Detected changes · ${detectedRows.length}`}>
        {detectedRows.length ? <div style={{ maxHeight: 360, overflowY: "auto" }}><DataTable rows={detectedRows} /></div>
          : <p>{!config.local && !config.overall ? "Change-point analysis disabled; trends only." : "No active change-point results."}</p>}
      </Disclosure>
      {overall && overall.signal.length > 0 && <Disclosure {...disclosure("overall-signal")} data-testid="overall-signal" summary="Inspect standardized overall signal">
        <p className="help">Mean of {overall.n_series} nonconstant standardized components (population SD). At missing windows, the mean uses available components without interpolation; the table reports coverage.</p>
        <TrendChart rows={overall.signal.map((r) => ({ ...r, zone: "Overall", metric: "aggregate" }))}
          series={[{ zone: "Overall", metric: "aggregate", label: "Mean standardized signal", unit: "z-score mean" }]}
          metricLabel="Mean standardized components" aggregateChangepoints={changes} observations={config.observations} />
        <DataTable rows={overall.signal} />
      </Disclosure>}
      {config.overall && changes.length > 0 && <Disclosure {...disclosure("overall-contributions")} data-testid="overall-contributions" summary="Contribution to an overall change">
        <label>Contribution change-point time <select value={selectedTime} onChange={(e) => setChosenTime(e.target.value)}>
          {changes.map((cp) => <option key={cp.timestamp} value={cp.timestamp}>{cp.timestamp}</option>)}
        </select></label>
        <p className="help">Absolute differences between adjacent detected segment means of each standardized component, divided by their total and expressed as percentages. Composition of the change, not its cause.</p>
        {positive.length > 0 ? <div data-testid="contribution-chart">
          <h4>Top Contributions</h4>
          <Plot data={[{ type: "bar", orientation: "h", x: positive.map((c) => c.contribution_pct),
            y: positive.map((c) => `${c.zone} · ${c.metric_label}`),
            marker: { color: positive.map((c) => resolveColor(zoneColor(c.zone))) },
            customdata: positive.map((c) => [c.timestamp, c.zone, c.metric_column, c.before_mean, c.after_mean, c.jump_score]),
            hovertemplate: "%{customdata[0]}<br>%{customdata[1]} · %{customdata[2]}<br>%{x:.2f}%<br>Before: %{customdata[3]:.4f} z<br>After: %{customdata[4]:.4f} z<br>Absolute jump: %{customdata[5]:.4f} z<extra></extra>",
          }]} layout={themedLayout({ hovermode: "closest", margin: { l: 270, r: 24, t: 8, b: 50 },
            xaxis: { ...(themedLayout().xaxis as object), range: [0, 100], ticksuffix: "%", title: { text: "Contribution (%)" } },
            yaxis: { ...(themedLayout().yaxis as object), autorange: "reversed", automargin: true },
          })} height={Math.max(240, positive.length * 36 + 90)} />
        </div> : <p>No measurable contribution for this boundary.</p>}
        {!!coverage?.omitted_components.length && <p className="help">{coverage.omitted_components.length} component(s) omitted from contributions because one adjacent segment has no observations.</p>}
        <div data-testid="contribution-table"><DataTable rows={contributions.map((c) => ({ zone: c.zone, metric: c.metric_label,
          timestamp: c.timestamp, "contribution (%)": c.contribution_pct, "before mean (z-score)": c.before_mean,
          "after mean (z-score)": c.after_mean, "absolute jump (z-score)": c.jump_score,
          "before start": c.before_start, "before end": c.before_end, "after start": c.after_start, "after end": c.after_end,
        }))} format={{ "contribution (%)": (v) => v == null || !Number.isFinite(Number(v)) ? "Unavailable" : `${Number(v).toFixed(2)}%` }} /></div>
      </Disclosure>}
      <Disclosure {...disclosure("plot-heatmaps")} data-testid="plot-heatmaps" style={{ marginTop: 12 }} summary="Zone × window heatmaps">
        {[...new Set(config.pairs.map((p) => p.metric))].map((m) => <div key={m}>
          <h3>{metadata(m)?.label} ({metricUnit(metadata(m), config.normalize)})</h3>
          <Heatmap rows={data.rows.filter((r) => r.metric === m)} zones={config.pairs.filter((p) => p.metric === m).map((p) => p.zone)} valueUnit={metricUnit(metadata(m), config.normalize)} />
        </div>)}
      </Disclosure>
      </div>
    </>}
  </section>;
}
