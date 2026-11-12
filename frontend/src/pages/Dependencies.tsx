import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { useAppState } from "../state";
import { DataTable, NeedsAnalysis, SkeletonPanel, ZoneChip } from "../components/shared";
import Disclosure from "../components/Disclosure";

export default function Dependencies() {
  const { analysisId, analysis } = useAppState();
  const [rows, setRows] = useState<Record<string, unknown>[]>([]);
  const [metricLabels, setMetricLabels] = useState<Record<string, string>>({});
  const [totalWindows, setTotalWindows] = useState<number | null>(null);
  const [metricOptions, setMetricOptions] = useState<string[]>([]);
  const [srcMetric, setSrcMetric] = useState("token_netflow");
  const [tgtMetric, setTgtMetric] = useState("token_avg_age_open");
  const [maxLag, setMaxLag] = useState(3);
  const [pairRows, setPairRows] = useState<Record<string, unknown>[] | null>(null);
  const [pairBusy, setPairBusy] = useState(false);
  const [pairError, setPairError] = useState<string | null>(null);
  const pairRevision = useRef(0);
  const query = JSON.stringify([analysisId, srcMetric, tgtMetric, maxLag]);
  const activeQuery = useRef(query);
  activeQuery.current = query;
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setRows([]);
    setTotalWindows(null);
    setMetricOptions([]);
    setError(null);
    if (!analysisId || !analysis?.has_artifacts) return;
    setLoading(true);
    Promise.all([api.dependencies(analysisId), api.metricCatalog(analysisId).catch(() => null)])
      .then(([r, catalog]) => {
        if (cancelled) return;
        setMetricLabels(Object.fromEntries((catalog?.metrics ?? []).map(m => [m.name, m.label])));
        setRows(r.rows);
        setTotalWindows(catalog?.windows.length ?? null);
        setMetricOptions(r.metric_options);
        if (r.metric_options.length >= 2) {
          if (!r.metric_options.includes(srcMetric)) setSrcMetric(r.metric_options[0]);
          if (!r.metric_options.includes(tgtMetric)) setTgtMetric(r.metric_options[1]);
        }
      })
      .catch((e) => !cancelled && setError(String(e)))
      .finally(() => !cancelled && setLoading(false));
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [analysisId, analysis?.has_artifacts]);

  // Invalidate both displayed results and in-flight requests on every input change.
  useEffect(() => {
    pairRevision.current++;
    setPairRows(null);
    setPairError(null);
    setPairBusy(false);
    return () => { pairRevision.current++; };
  }, [analysisId, srcMetric, tgtMetric, maxLag]);

  const labels = { from_zone: "Source zone", to_zone: "Later zone", src_metric: "Source metric", tgt_metric: "Later metric",
    best_lag_windows: "Delay (windows)", best_corr: "Correlation (−1 to +1)", overlap_points: "Paired windows", significant: "Statistical check",
    p_value: "Chance-test value after checking delays (p)", q_value: "Value after checking multiple pairs (q)" };
  const headerHelp = { significant: "Checks whether the association remains statistically supported after allowing for the many pairs and delays tested. Passing does not imply cause and effect or practical importance." };
  const columns = ["from_zone", "src_metric", "to_zone", "tgt_metric", "best_lag_windows", "best_corr", "overlap_points", "significant"];
  const metricCell = (v: unknown) => <span title={String(v)}>{metricLabels[String(v)] ?? String(v)}</span>;
  const format = {
    src_metric: metricCell, tgt_metric: metricCell,
    from_zone: (v: unknown) => <ZoneChip zone={String(v)} />, to_zone: (v: unknown) => <ZoneChip zone={String(v)} />,
    best_corr: (v: unknown) => v == null ? "–" : Number(v).toFixed(3),
    overlap_points: (v: unknown) => v == null ? "Unavailable" : totalWindows === null ? `${v} paired (total unavailable)` : `${v} out of ${totalWindows}`,
    significant: (v: unknown) => v === true ? <span className="badge ok" style={{ textTransform: "none", letterSpacing: "normal" }}>Passes statistical check</span> : <span className="help">Not enough evidence</span>,
    p_value: (v: unknown) => v == null ? "–" : Number(v).toExponential(1),
    q_value: (v: unknown) => v == null ? "–" : Number(v).toExponential(1),
  };
  const statisticalDetails = (values: Record<string, unknown>[]) => <Disclosure summary="How statistical checks work · detailed values" style={{ marginTop: 12 }}>
    <p className="help">We check several delays and many zone–metric pairs. The test values are adjusted for these repeated checks so chance matches are less likely to be highlighted. “Passes statistical check” means the adjusted value is below 0.05; it does not measure the size or importance of the association, or prove a cause.</p>
    <p className="help">Technical method: a two-sided Pearson test, a Bonferroni correction for the tested delays (p), and Benjamini–Hochberg false discovery rate adjustment across the tested pairs (q). The first table uses the full scan; the selected-metric table uses its own pairs. These exploratory tests do not account for all temporal dependence within a series.</p>
    {!!values.length && <DataTable rows={values} columns={columns.concat(["p_value", "q_value"])} labels={labels} headerHelp={headerHelp} format={format} />}
  </Disclosure>;
  return (
    <NeedsAnalysis>
      <h1>Dependencies</h1>
      <div className="notice muted">
        Find metrics in different zones that move together, possibly with a delay. A positive correlation means the same direction; a negative correlation means opposite directions. Association does not establish cause and effect.
      </div>
      <p className="help">Paired windows shows how many matching source–target observations were used, out of {totalWindows ?? "all"} analysis windows in the full timeline. Delays and missing values can reduce the count. The statistical check allows for testing many pairs and delays. A delay of 1 compares the source with the target one analysis window later ({analysis?.timeframe_label.toLowerCase() || "the selected time interval"}).</p>
      {error && <div className="notice error">{error}</div>}
      {loading && <SkeletonPanel rows={5} />}
      <div className="panel">
        <h2>Strongest cross-zone associations</h2>
        {loading ? <p className="help">Loading associations…</p> : error ? <p className="help">Association results are unavailable.</p> : rows.length === 0 ? (
          <p className="help">No eligible associations. Correlation requires enough overlapping windows and variation in both series.</p>
        ) : (
          <DataTable rows={rows} labels={labels} headerHelp={headerHelp} columns={columns} format={format} />
        )}
        {statisticalDetails(rows)}
      </div>

      <Disclosure className="panel" summary="Explore a specific pair of metrics">
        <p className="help">
          Positive lag compares the source with the target that many windows later. Positive correlation means they move in the same direction; negative correlation means opposite directions. Neither establishes causality. For each zone pair, find the strongest correlation for the selected source and target metrics across the tested lags. A lag is measured in analysis windows, not necessarily days.
        </p>
        <div className="row">
          <label>
            Source{" "}
            <select value={srcMetric} onChange={(e) => setSrcMetric(e.target.value)}>
              {metricOptions.map((m) => (
                <option key={m} value={m}>{metricLabels[m] ?? m}</option>
              ))}
            </select>
          </label>
          <label>
            Target{" "}
            <select value={tgtMetric} onChange={(e) => setTgtMetric(e.target.value)}>
              {metricOptions.map((m) => (
                <option key={m} value={m}>{metricLabels[m] ?? m}</option>
              ))}
            </select>
          </label>
          <label>
            Maximum lag (windows){" "}
            <input
              type="number"
              min={1}
              max={10}
              value={maxLag}
              onChange={(e) => setMaxLag(Number(e.target.value))}
              style={{ width: 58 }}
            />
          </label>
          <button
            disabled={pairBusy || !analysisId || !metricOptions.length || !Number.isInteger(maxLag) || maxLag < 1 || maxLag > 10}
            onClick={async () => {
              const revision = ++pairRevision.current;
              setPairBusy(true);
              setPairRows(null);
              setPairError(null);
              try {
                const result = await api.dependencyPair(analysisId!, srcMetric, tgtMetric, maxLag);
                if (revision === pairRevision.current && query === activeQuery.current) setPairRows(result.rows);
              } catch (e) {
                if (revision === pairRevision.current && query === activeQuery.current) setPairError(String(e));
              } finally {
                if (revision === pairRevision.current && query === activeQuery.current) setPairBusy(false);
              }
            }}
          >
            {pairBusy ? "Computing…" : "Explore pair"}
          </button>
        </div>
        {pairError && <div className="notice error" role="alert">Pair analysis failed: {pairError}</div>}
        {!pairBusy && !pairError && pairRows === null && <p className="help" role="status">No results for the current settings. Choose metrics and a maximum lag, then select Explore pair.</p>}
        {pairBusy && <p role="status">Computing the selected metric pair…</p>}
        {pairRows && (
          <div style={{ marginTop: 10 }}>
            <p className="help">Results: {metricLabels[srcMetric] ?? srcMetric} → {metricLabels[tgtMetric] ?? tgtMetric}; maximum lag {maxLag} windows.</p>
            {pairRows.length === 0 ? (
              <p className="help">No zone pairs with enough data for this metric pair.</p>
            ) : (
              <>
                <DataTable rows={pairRows} labels={labels} headerHelp={headerHelp} columns={columns} format={format} />
                {statisticalDetails(pairRows)}
              </>
            )}
          </div>
        )}
      </Disclosure>
    </NeedsAnalysis>
  );
}
