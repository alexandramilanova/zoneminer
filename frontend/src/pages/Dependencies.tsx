import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { useAppState } from "../state";
import { DataTable, NeedsAnalysis, SkeletonPanel, ZoneChip } from "../components/shared";

export default function Dependencies() {
  const { analysisId, analysis } = useAppState();
  const [rows, setRows] = useState<Record<string, unknown>[]>([]);
  const [metricLabels, setMetricLabels] = useState<Record<string, string>>({});
  const [note, setNote] = useState("");
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
    setNote("");
    setMetricOptions([]);
    setError(null);
    if (!analysisId || !analysis?.has_artifacts) return;
    setLoading(true);
    Promise.all([api.dependencies(analysisId), api.metricCatalog(analysisId).catch(() => null)])
      .then(([r, catalog]) => {
        if (cancelled) return;
        setMetricLabels(Object.fromEntries((catalog?.metrics ?? []).map(m => [m.name, m.label])));
        setRows(r.rows);
        setNote(r.note);
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

  const labels = { from_zone: "Source zone", to_zone: "Target zone", src_metric: "Source metric", tgt_metric: "Target metric",
    best_lag_windows: "Best lag (windows)", best_corr: "Pearson correlation", overlap_points: "Paired windows", significant: "Significance", p_value: "Adjusted-for-lag p", q_value: "FDR q" };
  const metricCell = (v: unknown) => <span title={String(v)}>{metricLabels[String(v)] ?? String(v)}</span>;
  return (
    <NeedsAnalysis>
      <h1>Dependencies</h1>
      <div className="notice muted">
        {note ||
          "Values are time-lagged Pearson correlations — association, not causation."}{" "}
        A strong association means two zone metrics move together with a delay; it does not prove
        one causes the other.
      </div>
      {error && <div className="notice error">{error}</div>}
      {loading && <SkeletonPanel rows={5} />}
      <div className="panel">
        <h2>Strongest cross-zone associations</h2>
        {loading ? <p className="help">Loading associations…</p> : error ? <p className="help">Association results are unavailable.</p> : rows.length === 0 ? (
          <p className="help">No eligible associations. Correlation requires enough overlapping windows and variation in both series.</p>
        ) : (
          <DataTable
            rows={rows}
            labels={labels}
            columns={[
              "from_zone",
              "src_metric",
              "to_zone",
              "tgt_metric",
              "best_lag_windows",
              "best_corr",
              "overlap_points",
              "significant",
            ].filter((c) => rows[0] && c in rows[0])}
            format={{
              src_metric: metricCell,
              tgt_metric: metricCell,
              from_zone: (v) => <ZoneChip zone={String(v)} />,
              to_zone: (v) => <ZoneChip zone={String(v)} />,
              best_corr: (v) => (v == null ? "–" : Number(v).toFixed(3)),
              significant: (v) =>
                v === true ? (
                  <span className="badge ok">FDR-adjusted p &lt; 0.05</span>
                ) : (
                  <span className="help">–</span>
                ),
            }}
          />
        )}
      </div>

      <div className="panel">
        <h2>Pair explorer (advanced)</h2>
        <p className="help">
          Positive lag compares the source with the target that many windows later. Positive correlation means they move in the same direction; negative correlation means opposite directions. Neither establishes causality. For each zone pair, find the strongest correlation for the selected source and target metrics across the tested lags. A lag is measured in analysis windows, not necessarily days.
        </p>
        <div className="row">
          <label>
            Source{" "}
            <select value={srcMetric} onChange={(e) => setSrcMetric(e.target.value)}>
              {metricOptions.map((m) => (
                <option key={m} value={m}>{metricLabels[m] ?? m} ({m})</option>
              ))}
            </select>
          </label>
          <label>
            Target{" "}
            <select value={tgtMetric} onChange={(e) => setTgtMetric(e.target.value)}>
              {metricOptions.map((m) => (
                <option key={m} value={m}>{metricLabels[m] ?? m} ({m})</option>
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
            <p className="help">Results: {srcMetric} → {tgtMetric}; maximum lag {maxLag} windows.</p>
            {pairRows.length === 0 ? (
              <p className="help">No zone pairs with enough data for this metric pair.</p>
            ) : (
              <DataTable
                rows={pairRows}
                labels={labels}
                format={{
                  src_metric: metricCell,
              tgt_metric: metricCell,
              from_zone: (v) => <ZoneChip zone={String(v)} />,
                  to_zone: (v) => <ZoneChip zone={String(v)} />,
                  best_corr: (v) => (v == null ? "–" : Number(v).toFixed(3)),
                  p_value: (v) => (v == null ? "–" : Number(v).toExponential(1)),
                  q_value: (v) => (v == null ? "–" : Number(v).toExponential(1)),
                  significant: (v) =>
                    v === true ? (
                      <span className="badge ok">FDR-adjusted p &lt; 0.05</span>
                    ) : (
                      <span className="help">–</span>
                    ),
                }}
              />
            )}
          </div>
        )}
      </div>
    </NeedsAnalysis>
  );
}
