import { formatDuration } from "../lib/metricPresentation";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  api, req,
  type BottleneckState,
  type HandoverPair,
  type MetricCatalog,
  type Overview as OverviewData,
} from "../api";
import ZoneGraph from "../components/ZoneGraph";
import { useAppState } from "../state";
import {
  DataTable,
  NeedsAnalysis,
  SkeletonPanel,
  StatTile,
  ZoneChip,
  fmtCell,
} from "../components/shared";
import { resolveColor } from "../lib/plotTheme";

interface AlertRule {
  metric: string;
  op: string;
  threshold: number;
}

export default function Overview() {
  const { analysisId, analysis, zoneColor } = useAppState();
  const [data, setData] = useState<OverviewData | null>(null);
  const [catalog, setCatalog] = useState<MetricCatalog | null>(null);
  const [series, setSeries] = useState<Record<string, number[]>>({});
  const [alerts, setAlerts] = useState<{
    thresholds: Record<string, number>;
    period: { window_start: string | null; window_end: string | null; window_count: number };
    per_zone_summary: Record<string, unknown>[];
  } | null>(null);
  const [openAgeH, setOpenAgeH] = useState<string>("");
  const [backlog, setBacklog] = useState<string>("20");
  const [advRules, setAdvRules] = useState<AlertRule[]>([]);
  const [advCombine, setAdvCombine] = useState<"ANY" | "ALL">("ANY");
  const [advRows, setAdvRows] = useState<Record<string, unknown>[] | null>(null);
  const [diag, setDiag] = useState<Record<string, unknown>[] | null>(null);
  const [flowMap, setFlowMap] = useState<{
    pairs: HandoverPair[];
    states: Map<string, BottleneckState>;
  } | null>(null);
  const [hintZone, setHintZone] = useState<string | null>(null);
  const [hints, setHints] = useState<
    | {
        zone: string;
        src_metric: string | null;
        best_corr: number | null;
        lag: number | null;
        recent_drift_max: number | null;
      }[]
    | null
  >(null);
  const [error, setError] = useState<string | null>(null);

  const alertedZones = useMemo(
    () =>
      Array.from(
        new Set((alerts?.per_zone_summary ?? []).map((r) => String(r.zone))),
      ),
    [alerts],
  );

  useEffect(() => {
    if (alertedZones.length && !hintZone) setHintZone(alertedZones[0]);
  }, [alertedZones, hintZone]);

  useEffect(() => {
    if (!analysisId || !hintZone) return;
    let cancelled = false;
    setHints(null);
    req<{ hints: NonNullable<typeof hints> }>(`/api/analyses/${analysisId}/alerts/hints?zone=${encodeURIComponent(hintZone)}`)
      .then((d) => !cancelled && setHints(d.hints ?? []))
      .catch(() => !cancelled && setHints([]));
    return () => {
      cancelled = true;
    };
  }, [analysisId, hintZone]);

  const loadAlerts = useCallback(() => {
    if (!analysisId) return;
    const params = new URLSearchParams();
    if (openAgeH.trim()) params.set("open_age_threshold", String(Number(openAgeH) * 3600));
    if (backlog.trim()) params.set("backlog_threshold", backlog);
    req<NonNullable<typeof alerts>>(`/api/analyses/${analysisId}/alerts?${params}`)
      .then(setAlerts)
      .catch((e) => setError(String(e)));
  }, [analysisId, openAgeH, backlog]);

  useEffect(() => {
    if (!analysisId || !analysis?.has_artifacts) return;
    let cancelled = false;
    setData(null);
    setCatalog(null);
    setSeries({});
    setFlowMap(null);
    setError(null);
    // Render the snapshot immediately; optional controls and sparklines must
    // not block it while private workers process companion requests.
    api.overview(analysisId).then(o => { if (!cancelled) setData(o); })
      .catch(e => { if (!cancelled) setError(String(e)); });
    api.metricCatalog(analysisId).then(cat => { if (!cancelled) setCatalog(cat); })
      .catch(e => { if (!cancelled) setError(String(e)); });
    api.features(analysisId, { metrics: ["token_present_end"] }).then(feat => {
      if (cancelled) return;
      const byZone: Record<string, number[]> = {};
      for (const r of feat.rows) {
        const z = String(r.zone);
        (byZone[z] ??= []).push(Number(r.token_present_end ?? 0));
      }
      setSeries(byZone);
    }).catch(e => { if (!cancelled) setError(String(e)); });
    loadAlerts();
    // flow map: handover edges + latest bottleneck state per zone (best-effort)
    Promise.all([api.handovers(analysisId), api.bottlenecks(analysisId)])
      .then(([h, b]) => {
        if (cancelled) return;
        const states = new Map<string, BottleneckState>();
        for (const z of b.zones) {
          if (z.states.length) states.set(z.zone, z.states[z.states.length - 1]);
        }
        setFlowMap({ pairs: h.pairs, states });
      })
      .catch(() => { if (!cancelled) setFlowMap({ pairs: [], states: new Map() }); });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [analysisId, analysis?.has_artifacts]);

  const numericMetrics = useMemo(
    () => catalog?.metrics.filter((m) => m.group !== "conformance") ?? [],
    [catalog],
  );

  return (
    <NeedsAnalysis>
      <h1>Overview &amp; Alerts</h1>
      <p className="page-sub">
        Snapshot: end occupancy and open-token age for the latest {analysis?.timeframe_label.toLowerCase()} window.
        Alerts below scan a separate lookback period. Global conformance is attributed to the window
        in which each trace completes and repeated across zones; it is not zone-specific conformance.
      </p>
      {error && <div className="notice error">{error}</div>}
      {!data && <SkeletonPanel rows={4} />}
      {data && (
        <>
          <div className="grid tiles" style={{ marginBottom: 16 }}>
            <StatTile label="Zones" value={data.zones.length} />
            <StatTile label="Time windows" value={data.window_count} hint={analysis?.timeframe_label} />
            <StatTile
              label="Snapshot boundary"
              value={data.latest_window_end ? data.latest_window_end.slice(0, 16).replace("T", " ") : "–"}
              hint="Immediately before this boundary; boundary events belong to the next window"
            />
            <StatTile
              label="Window fitness (mean)"
              value={
                data.window_conformance.alignment_trace_fitness_mean != null
                  ? Number(data.window_conformance.alignment_trace_fitness_mean).toFixed(3)
                  : "–"
              }
              hint="fraction · global/window · repeated across zones"
            />
          </div>

          <p className="help" data-testid="snapshot-period">Snapshot window: [{data.latest_window}, {data.latest_window_end}). Occupancy is measured just before the end boundary; events at that boundary belong to the next window. Timestamps follow the analysis time basis.</p>
          <div className="grid tiles" style={{ marginBottom: 16 }}>
            {data.per_zone_latest.map((z) => {
              const s = series[z.zone] ?? [];
              const prev = s.length > 1 ? s[s.length - 2] : null;
              return (
                <StatTile
                  key={z.zone}
                  label={z.zone}
                  value={z.token_present_end.toLocaleString()}
                  hint={`tokens at snapshot · ${z.case_present_end.toLocaleString()} cases${
                    z.token_avg_age_open != null
                      ? ` · age ${formatDuration(z.token_avg_age_open)}`
                      : ""
                  }`}
                  delta={prev != null ? z.token_present_end - prev : null}
                  spark={s}
                  sparkColor={resolveColor(zoneColor(z.zone))}
                />
              );
            })}
          </div>

          {flowMap && flowMap.pairs.length > 0 && (
            <div className="panel">
              <h2>Zone flow map</h2>
              <p className="help">
                Node occupancy and heuristic halos refer to the snapshot window. Handover edges
                summarize reconstructed case-zone movements across the whole analysis, not just that window.
                A halo is an indication to investigate, not an observed resource bottleneck.
              </p>
              <ZoneGraph
                loads={
                  new Map(
                    data.per_zone_latest.map((z) => [
                      z.zone,
                      { tokens: z.token_present_end, cases: z.case_present_end },
                    ]),
                  )
                }
                pairs={flowMap.pairs}
                states={flowMap.states}
              />
            </div>
          )}

          <div className="panel">
            <h2>Zones at the latest window</h2>
            <DataTable
              rows={data.per_zone_latest as unknown as Record<string, unknown>[]}
              columns={["zone", "token_present_end", "case_present_end", "token_avg_age_open"]}
              labels={{ zone: "Zone", token_present_end: "Tokens at window end", case_present_end: "Cases at window end", token_avg_age_open: "Mean open-token age" }}
              format={{
                zone: (v) => <ZoneChip zone={String(v)} />,
                token_avg_age_open: (v) => formatDuration(v),
              }}
            />
            <p className="help">
              Tokens and cases can diverge in zones with parallel branches — one case can hold
              several tokens in the same zone at once. These counts describe the replay reconstruction, rather than directly observed token identities.
            </p>
          </div>
        </>
      )}

      {alerts && (
        <div className="panel">
          <h2>Alerts · recent windows</h2>
          <p className="help" data-testid="alert-period">Alert lookback: {alerts.period?.window_count ?? alerts.thresholds.lookback_windows} available windows (up to {alerts.thresholds.lookback_windows}), separate from the single snapshot above.
            {alerts.period?.window_start && <> Period: [{alerts.period.window_start}, {alerts.period.window_end}).</>}
            {" "}Each row identifies a zone’s latest flagged window in this period; it need not be the snapshot window. Severity adds 2 points for the age threshold and 1 for occupancy (maximum 3); it is not a probability.
          </p>
          <div className="row" style={{ marginBottom: 8 }}>
            <label className="help">
              Mean open-token age ≥{" "}
              <input
                value={openAgeH}
                onChange={(e) => setOpenAgeH(e.target.value)}
                placeholder={(alerts.thresholds.open_age_threshold / 3600).toFixed(0)}
                style={{ width: 64 }}
              />{" "}
              h
            </label>
            <label className="help">
              End token occupancy ≥{" "}
              <input value={backlog} onChange={(e) => setBacklog(e.target.value)} style={{ width: 64 }} />{" "}
              tokens
            </label>
            <button onClick={loadAlerts}>Apply thresholds</button>
          </div>
          {alerts.per_zone_summary.length === 0 ? (
            <p className="help">No zones exceed the thresholds in the last {alerts.thresholds.lookback_windows} windows.</p>
          ) : (
            <DataTable
              rows={alerts.per_zone_summary}
              columns={["zone", "window_start", "severity", "reasons"]}
              format={{
                zone: (v) => <ZoneChip zone={String(v)} />,
                severity: (v) => (
                  <span className={`badge ${Number(v) >= 3 ? "crit" : "warn"}`}>
                    {Number(v)} / 3
                  </span>
                ),
                window_start: (v) => String(v).slice(0, 16).replace("T", " "),
                reasons: (v) => fmtCell(String(Array.isArray(v) ? (v as string[]).join("; ") : v)
                  .replace(/token_avg_age_open=([-\d.]+)/g, "token_avg_age_open=$1 seconds")),
              }}
            />
          )}

          {alertedZones.length > 0 && (
            <div style={{ marginTop: 14 }}>
              <div className="row" style={{ marginBottom: 6 }}>
                <h3 style={{ margin: 0 }}>Associated upstream zones</h3>
                <select aria-label="Alerted zone for association context" value={hintZone ?? ""} onChange={(e) => setHintZone(e.target.value)}>
                  {alertedZones.map((z) => (
                    <option key={z}>{z}</option>
                  ))}
                </select>
              </div>
              <p className="help">
                Upstream zones ranked by lagged correlation with the alerted zone's backlog, with
                recent drift as context — <em>association, not causation</em>; a shortlist of
                where to look first.
              </p>
              {hints === null && <p className="help">Computing…</p>}
              {hints !== null && hints.length === 0 && (
                <p className="help">No upstream zones for this alert.</p>
              )}
              {hints !== null && hints.length > 0 && (
                <DataTable
                  rows={hints.map((h) => ({
                    "upstream zone": h.zone,
                    "association (best lag)": h,
                    "recent drift": h.recent_drift_max,
                  }))}
                  format={{
                    "upstream zone": (v) => <ZoneChip zone={String(v)} />,
                    "association (best lag)": (v) => {
                      const h = v as NonNullable<typeof hints>[number];
                      if (h.best_corr === null) return <span className="help">–</span>;
                      return (
                        <span style={{ fontWeight: Math.abs(h.best_corr) >= 0.5 ? 700 : 400 }}>
                          r = {h.best_corr.toFixed(2)} at lag {h.lag}
                          {h.src_metric ? ` (${h.src_metric.replaceAll("_", " ")})` : ""}
                        </span>
                      );
                    },
                    "recent drift": (v) =>
                      v === null || v === undefined ? (
                        <span className="help">–</span>
                      ) : (
                        Number(v).toFixed(2)
                      ),
                  }}
                />
              )}
            </div>
          )}

          <details style={{ marginTop: 12 }}>
            <summary className="help" style={{ cursor: "pointer" }}>
              Advanced rules (combine custom conditions with ANY / ALL)
            </summary>
            <div style={{ marginTop: 10 }}>
              <p className="help">Evaluate the last seven available windows. Enter thresholds in canonical metric units: seconds for durations and fractions for ratios. ANY matches at least one rule; ALL requires every rule.</p>
              {advRules.map((r, i) => (
                <div className="row" key={i} style={{ marginBottom: 6 }}>
                  <select
                    aria-label={`Rule ${i + 1} metric`}
                    value={r.metric}
                    onChange={(e) =>
                      setAdvRules((p) => p.map((x, j) => (j === i ? { ...x, metric: e.target.value } : x)))
                    }
                  >
                    {numericMetrics.map((m) => (
                      <option key={m.name} value={m.name}>
                        {m.label}
                      </option>
                    ))}
                  </select>
                  <select
                    aria-label={`Rule ${i + 1} comparison`}
                    value={r.op}
                    onChange={(e) =>
                      setAdvRules((p) => p.map((x, j) => (j === i ? { ...x, op: e.target.value } : x)))
                    }
                  >
                    <option>{">="}</option>
                    <option>{"<="}</option>
                  </select>
                  <input
                    type="number"
                    aria-label={`Rule ${i + 1} threshold`}
                    value={r.threshold}
                    onChange={(e) =>
                      setAdvRules((p) =>
                        p.map((x, j) => (j === i ? { ...x, threshold: Number(e.target.value) } : x)),
                      )
                    }
                    style={{ width: 100 }}
                  />
                  <button aria-label={`Remove rule ${i + 1}`} onClick={() => setAdvRules((p) => p.filter((_, j) => j !== i))}>✕</button>
                </div>
              ))}
              <div className="row">
                <button
                  onClick={() =>
                    setAdvRules((p) => [
                      ...p,
                      { metric: numericMetrics[0]?.name ?? "token_present_end", op: ">=", threshold: 0 },
                    ])
                  }
                >
                  + Add rule
                </button>
                <select value={advCombine} onChange={(e) => setAdvCombine(e.target.value as "ANY" | "ALL")}>
                  <option value="ANY">match ANY rule</option>
                  <option value="ALL">match ALL rules</option>
                </select>
                <button
                  className="primary"
                  disabled={!advRules.length || !analysisId}
                  onClick={async () => {
                    try {
                      setAdvRows((await api.advancedAlerts(analysisId!, advRules, advCombine, 7)).flagged_rows);
                    } catch (e) {
                      setError(String(e));
                    }
                  }}
                >
                  Evaluate
                </button>
              </div>
              {advRows && (
                <div style={{ marginTop: 8 }}>
                  {advRows.length === 0 ? (
                    <p className="help">No windows match these rules.</p>
                  ) : (
                    <DataTable
                      rows={advRows}
                      format={{
                        zone: (v) => <ZoneChip zone={String(v)} />,
                        window_start: (v) => String(v).slice(0, 16).replace("T", " "),
                      }}
                    />
                  )}
                </div>
              )}
            </div>
          </details>
        </div>
      )}

      <div className="panel">
        <details
          onToggle={(e) => {
            if ((e.target as HTMLDetailsElement).open && diag === null && analysisId) {
              api
                .diagnostics(analysisId)
                .then((d) => setDiag(d.zone_diagnostics))
                .catch(() => setDiag([]));
            }
          }}
        >
          <summary className="help" style={{ cursor: "pointer" }}>
            Leak / open-token diagnostics per zone
          </summary>
          {diag && diag.length > 0 && (
            <div style={{ marginTop: 10 }}>
              <DataTable rows={diag} format={{ zone: (v) => <ZoneChip zone={String(v)} /> }} />
              <p className="help">
                Open tokens at the end of the log are expected for running cases; a persistently
                leaking place can also indicate model–log mismatch.
              </p>
            </div>
          )}
          {diag && diag.length === 0 && <p className="help">No diagnostics available.</p>}
        </details>
      </div>
    </NeedsAnalysis>
  );
}
