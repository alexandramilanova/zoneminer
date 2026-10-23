import { useEffect, useState } from "react";
import { api, type MetricCatalog, type MetricInfo } from "../api";
import { useAppState } from "../state";
import { NeedsAnalysis } from "../components/shared";

const GROUPS = [
  ["token_place", "Token-place metrics", "Place-level productions, consumptions and occupancy, aggregated over the zone's places. Internal movements count; these are not merged token-zone boundary stays."],
  ["case_zone", "Case-zone metrics", "Presence merges overlapping or touching intervals for each case. Entry/exit counts deduplicate cases per window; duration, revisit, batching and order statistics use stays."],
  ["process_window", "Global conformance · process/window", "Whole-trace alignments assigned by last recorded event. Repeated on every zone row: never sum across zones."],
  ["zone_conformance", "Zone-attributed conformance", "Alignment moves assigned by transition adjacency and replayed move time. Counts may duplicate boundary moves; weighted mass splits them among adjacent zones."],
] as const;

function MetricRow({ metric: m }: { metric: MetricInfo }) {
  return <tr data-testid={`metric-${m.name}`}>
    <th scope="row" style={{ width: "29%", verticalAlign: "top", textTransform: "none", letterSpacing: "normal", fontSize: 14, fontWeight: 400, whiteSpace: "normal", color: "var(--text)", overflowWrap: "anywhere" }}>
      <strong>{m.label}</strong><div><code>{m.name}</code></div>
      <p className="help">{m.unit_label}<br />Scope: {m.scope.replaceAll("_", " ")}</p>
      {!m.non_null_count && <span className="badge">Unavailable in this analysis</span>}
    </th>
    <td style={{ verticalAlign: "top" }}>
      <p>{m.description}</p>
      <p><strong>Calculation / population:</strong> {m.formula}</p>
      <p className="help"><strong>Empty values:</strong> {m.unavailable}</p>
    </td>
  </tr>;
}

export default function Metrics() {
  const { analysisId, analysis } = useAppState();
  const ready = Boolean(analysisId && analysis?.id === analysisId && analysis.has_artifacts);
  const [result, setResult] = useState<{ id: string; catalog?: MetricCatalog; error?: string } | null>(null);
  const [search, setSearch] = useState("");
  const [scope, setScope] = useState("all");
  useEffect(() => {
    if (!ready || !analysisId) return;
    let current = true;
    api.metricCatalog(analysisId).then(
      (catalog) => { if (current) setResult({ id: analysisId, catalog }); },
      (error) => { if (current) setResult({ id: analysisId, error: String(error) }); },
    );
    return () => { current = false; };
  }, [analysisId, ready]);
  const catalog = ready && result?.id === analysisId ? result.catalog : undefined;
  const error = ready && result?.id === analysisId ? result.error : undefined;
  const matches = (m: MetricInfo) => (scope === "all" || m.scope === scope) &&
    `${m.name} ${m.label} ${m.description} ${m.formula} ${m.unit_label}`.toLowerCase().includes(search.trim().toLowerCase());

  return <NeedsAnalysis>
    <h1>Metrics reference</h1>
    <p className="help">Definitions of the implemented retrospective calculations. Technical identifiers and canonical values are preserved in API responses and raw exports.</p>
    {error && <div className="notice error" role="alert">Metric reference unavailable: {error}</div>}
    {ready && !catalog && !error && <p role="status">Loading metric reference…</p>}
    {catalog && <>
      <div className="panel">
        <h2>Reading {catalog.timeframe_label.toLowerCase()} windows</h2>
        <p>{catalog.window_rule}</p>
        <p><strong>Units:</strong> Metric charts and series tables use seconds for durations and fractions for ratios (0.25 means 25%). Ratios are not automatically probabilities and some exceed 1. Compact duration summaries explicitly show s, min, h or d. Normalized trends use dimensionless z-scores.</p>
      </div>
      <div className="row" style={{ marginBottom: 16, gap: 16 }}>
        <label>Find a metric <input type="search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Name, identifier, unit…" /></label>
        <label>Metric scope <select value={scope} onChange={(e) => setScope(e.target.value)}><option value="all">All scopes</option>{GROUPS.map(([key, title]) => <option key={key} value={key}>{title}</option>)}</select></label>
        <span className="help" role="status">{catalog.metrics.filter(matches).length} of {catalog.metrics.length} metrics</span>
      </div>
      {!catalog.metrics.length && <p>No metric columns are available for this analysis.</p>}
      {!!catalog.metrics.length && !catalog.metrics.some(matches) && <p>No metrics match this search and scope.</p>}
      {GROUPS.map(([key, title, blurb]) => {
        const metrics = catalog.metrics.filter((m) => m.scope === key && matches(m));
        return metrics.length ? <section className="panel" key={key} aria-label={title}>
          <h2>{title}</h2><p className="help">{blurb}</p>
          <div style={{ overflowX: "auto" }}><table className="data"><thead><tr><th>Metric · unit · scope</th><th>Definition and interpretation</th></tr></thead>
            <tbody>{metrics.map((m) => <MetricRow key={m.name} metric={m} />)}</tbody></table></div>
        </section> : null;
      })}
    </>}
  </NeedsAnalysis>;
}
