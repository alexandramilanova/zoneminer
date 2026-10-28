/** Typed client for the ZoneMiner API.
 *
 * Types mirror the FastAPI response shapes (backend/routers/). The dev server
 * proxies /api to uvicorn; in production the backend serves this app, so all
 * calls are same-origin either way.
 */

export interface ForecastMetric {
  name: string; label: string; unit_label: string; description: string;
  forecast_supported: boolean; forecast_reason: string | null;
}
export interface RetrospectiveOptions {
  protocol_version:string; interpretation:string; zones:string[]; windows:number;
  metrics:{name:string;label:string;family:string;unit_label:string;description:string;scope:string}[];
  availability:Record<string,Record<string,{observed:number;minimum:number|null;maximum:number|null;distinct_values:number;
    suggested_thresholds:Record<string,{value:number|null;reason:string;positive_windows:number;negative_windows:number}>}>>;
  defaults:Record<string,number>;
}
export interface RetrospectiveResult {
  balance_classes:boolean;
  protocol_version:string;experiment_id:string;cached:boolean;interpretation:string;warning:string|null;
  target:{zone:string;metric:string;threshold:number;operator:string};horizon:number;timeframe:string;
  training_windows:number;positive_windows:number;negative_windows:number;positive_rate:number;baseline_note:string;
  defaults:Record<string,number>;baselines:(Partial<ForecastScore>&{model:string;status?:string})[];
  reconstruction:{source:string;timing:string;limitations:string;aligned_cases?:number;log_only_moves?:number;visible_model_moves?:number;cases_with_visible_deviation?:number};
  models:{model_key:string;model_label:string;diagnostic:string|null;mean_f1:number;mean_precision:number;mean_recall:number;valid_folds:number;
    evaluation:ForecastScore;feature_importance:{feature:string;importance:number}[];
    decision_tree:DecisionTreeView|null;shap:ForecastShap;
    folds:{fold:number;status:string;n_train:number;n_test:number;first_evaluation_origin:string;latest_training_label_available:string|null;f1?:number}[];
    predictions:{origin:string;actual:number;predicted:number}[];
    estimate:{status:string;reason?:string;origin?:string;target_start?:string;target_end?:string;predicted_class?:number;probability?:number};
  }[];
}
export interface ForecastOptions {
  protocol_version: string; eligible: boolean; reasons: string[]; zones: string[];
  window_ends: string[]; metrics: ForecastMetric[]; assumptions: string[];
  calibration_required?: boolean; forecast_profile?: string;
  study?: { id: string; calibration_id: string; calibration_end: string; zone_places: Record<string,string[]> } | null;
}
export interface ForecastScore {
  n_rows: number; positive_rows: number; positive_rate: number; f1: number;
  precision: number; recall: number; confusion: { tp: number; fn: number; fp: number; tn: number };
}
export interface ForecastShap {
  status: string; reason?: string; scope?: string; scale?: string; n_background?: number; n_explained?: number;
  rows: { feature: string; mean_abs_shap: number; values: number[]; feature_values: number[] }[];
}
export interface ForecastResult {
  protocol_version: string; experiment_id: string; cached: boolean; selected_model: string; selection_basis: string;
  target: { zone: string; metric: string; operator: string; threshold: number };
  development_end: string; observed_through: string; forecast_context: string; evidence_warning: string | null; evaluation_note: string; holdout_warning: string | null;
  assumptions: string[]; baselines: (Partial<ForecastScore> & { model: string; status?: string })[];
  reconstruction?: { policy: string; cutoff: string; observed_events: number; inferred_silent_events: number | null;
    visible_events_inserted: number; visible_events_deleted: number; silent_transition_counts: Record<string, number>;
    inferred_event_preview: Record<string, unknown>[]; preview_limit: number;
    peak_markings?: number; cases_with_alternatives?: number; tied_timestamp_batches?: number; note?: string } | null;
  models: {
    model_key: string; model_label: string; horizon: number; n_training_rows: number; positive_training_rows: number;
    cv: { f1: number; precision: number; recall: number; valid_folds: number;
      folds: { fold: number; status: string; n_train: number; n_test: number; f1?: number; prediction_origin: string }[] };
    holdout: ForecastScore; feature_importance: { feature: string; importance: number }[];
    decision_tree: DecisionTreeView | null; shap: ForecastShap;
    forecast: { origin: string; target_start: string; target_end: string; predicted_class: number; probability: number;
      probability_calibrated: boolean; feature_origin: string; latest_training_origin: string; latest_training_label_available: string };
  }[];
}

export interface DecisionTreeView {
  nodes: { id: number; feature: string | null; threshold: number | null;
    left: number | null; right: number | null; samples: number; predicted_class: number; positive_share: number }[];
}

export interface Dataset {
  id: string;
  name: string;
  log_filename: string;
  pnml_filename: string | null;
  created_at: string;
  deduplicated?: boolean;
}

export interface ModelGraph {
  places: string[];
  transitions: { name: string; label: string | null }[];
  arcs: { source: string; target: string; weight: number }[];
  initial_marking: Record<string, number>;
  final_marking: Record<string, number>;
  activity_labels: string[];
  model_source: string;
  model_notice: string | null;
  process_tree_available?: boolean;
  bpmn_available?: boolean;
  process_tree_reason?: string | null;
  bpmn_reason?: string | null;
}

export interface ZoneValidation {
  valid: boolean;
  errors: string[];
  warnings: string[];
  zone_places: Record<string, string[]>;
}

export interface AnalysisCreated {
  analysis_id: string;
  job_id: string | null;
  cached: boolean;
}

export interface JobEvent {
  stage: string;
  status: string;
  detail: string;
  ts: number;
}

export interface JobInfo {
  id: string;
  kind: string;
  status: "queued" | "running" | "done" | "error";
  error: string | null;
  events: JobEvent[];
}

export interface AnalysisMeta {
  id: string;
  dataset_id: string;
  zone_places: Record<string, string[]>;
  timeframe: string;
  timeframe_label: string;
  backend: string;
  status: string;
  error: string | null;
  has_artifacts: boolean;
}

export interface MetricInfo {
  name: string;
  label: string;
  explanation: string | null;
  group: "token" | "case" | "conformance" | "other";
  canonical_unit: "count" | "seconds" | "ratio" | "cost_units" | "move_equivalents";
  unit_label: string;
  scope: "token_place" | "case_zone" | "process_window" | "zone_conformance";
  description: string;
  formula: string;
  unavailable: string;
  non_null_count: number;
  row_count: number;
}

export interface MetricCatalog {
  metrics: MetricInfo[];
  zones: string[];
  windows: string[];
  duration_unit_label: string;
  window_rule: string;
  replay_rule: string;
  timeframe_label: string;
}

export interface TrendRecord extends Record<string, unknown> {
  zone: string;
  window_start: string;
  metric: string;
  metric_label: string;
  value: number | null;
}

export interface ChangePointRecord extends Record<string, unknown> {
  timestamp: string;
  zone: string;
  metric_column: string;
  metric_label: string;
  series: string;
  cp_index: number;
  cp_order: number;
}

export interface AggregateChangePoint extends Record<string, unknown> {
  timestamp: string;
  selection_label: string;
  aggregate_method: string;
  n_series: number;
  cp_index: number;
  cp_order: number;
}

export interface ChangeContribution extends Record<string, unknown> {
  timestamp: string;
  selection_label: string;
  aggregate_method: string;
  zone: string;
  metric_column: string;
  metric_label: string;
  series: string;
  before_mean: number;
  after_mean: number;
  jump_score: number;
  contribution_pct: number;
  before_start?: string;
  before_end?: string;
  after_start?: string;
  after_end?: string;
  before_n?: number;
  after_n?: number;
}

export interface SelectionChanges {
  changepoints: AggregateChangePoint[];
  contributions: ChangeContribution[];
}

export interface ZoneMetricPair { zone: string; metric: string }
export interface TrendSelectionRequest {
  pairs: ZoneMetricPair[];
  normalize: boolean;
  local_enabled: boolean;
  overall_enabled: boolean;
  cp_strictness: number;
}
export interface TrendSelectionResult {
  rows: TrendRecord[];
  series: (ZoneMetricPair & { n_observations: number; n_windows: number;
    status: "usable" | "constant" | "insufficient_observations";
    local_status: "disabled" | "detected" | "no_changes" | "constant" | "insufficient_observations" })[];
  local_changepoints: ChangePointRecord[];
  overall: SelectionChanges & {
    status: "disabled" | "detected" | "no_changes" | "constant" | "insufficient_components" | "insufficient_observations";
    n_series: number;
    signal: { window_start: string; value: number; n_components: number }[];
    contribution_details: { timestamp: string; status: string; total_jump: number; included_components: number;
      omitted_components: (ZoneMetricPair & { reason: string })[] }[];
  };
  protocol: { contribution_context: string; min_points: number; min_size: number; missing_policy: string };
}

export interface Overview {
  zones: string[];
  window_count: number;
  latest_window: string;
  latest_window_end: string | null;
  window_conformance: Record<string, number | null>;
  per_zone_latest: {
    zone: string;
    token_present_end: number;
    case_present_end: number;
    token_avg_age_open: number | null;
  }[];
}

export interface ZoneStay {
  case_id: string;
  zone: string;
  stay_id: number;
  entry_ts: string;
  exit_ts: string | null;
  is_open: boolean;
  duration_s: number | null;
}

export interface QueueingZoneProfile {
  zone: string;
  stay_count: number;
  completed_count: number;
  arrival_rate_per_day: number;
  departure_rate_per_day: number;
  sojourn_mean_s: number | null;
  sojourn_p50_s: number | null;
  wip_time_avg: number;
  littles_ratio: number | null;
  cv_interarrival: number | null;
  cv_sojourn: number | null;
  load_dependence_r: number | null;
  queue_model: {
    service_time_s: number;
    service_rate_per_day: number;
    utilization: number | null;
    kingman_wait_s: number | null;
    measured_wait_s: number;
    fit: "plausible" | "regime-shift" | "degenerate" | "overloaded";
  } | null;
  scatter: { occupancy_at_entry: number[]; sojourn_s: number[] };
}

export type BottleneckState = "flowing" | "queueing" | "blocked" | "starving";

export interface HandoverPair {
  src: string;
  tgt: string;
  count: number;
  median_delay_s: number;
  mean_delay_s: number;
}

export interface DemoInfo {
  dataset_id: string;
  zones: Record<string, string[]>;
  timeframe: string;
}

export interface SessionInfo { mode: "local" | "anonymous"; expires_at: number | null; upload_mb: number | null; workspace_mb: number | null }
let session: Promise<SessionInfo> | undefined;
export function sessionInfo(): Promise<SessionInfo> {
  session ??= fetch("/api/session", { cache: "no-store" }).then(async (response) => {
    if (!response.ok) throw new Error("Your temporary session has expired or is unavailable. Start a new session.");
    const info = await response.json() as SessionInfo;
    if (info.mode === "anonymous") {
      const identity = String(info.expires_at);
      if (localStorage.getItem("zoneminer-session") !== identity) {
        localStorage.removeItem("zone-analytics-current");
        localStorage.setItem("zoneminer-session", identity);
      }
    }
    return info;
  });
  return session;
}

async function req<T>(url: string, init?: RequestInit): Promise<T> {
  await sessionInfo();
  // Retry admission bursts only for reads (including the read-only trend POST).
  // Never repeat uploads, analysis creation or other state-changing requests.
  const repeatable = !init?.method || init.method === "GET" ||
    (init.method === "POST" && /\/trends\/selection$/.test(url));
  let resp = await fetch(url, init);
  for (let attempt = 0; repeatable && resp.status === 429 && attempt < 2; attempt++) {
    await resp.body?.cancel();
    const seconds = Number(resp.headers.get("Retry-After") ?? 2 ** attempt);
    await new Promise<void>((resolve, reject) => {
      const signal = init?.signal;
      const abort = () => { clearTimeout(timer); reject(new DOMException("Aborted", "AbortError")); };
      const timer = window.setTimeout(() => {
        signal?.removeEventListener("abort", abort);
        resolve();
      }, Math.min(5, Math.max(0.1, Number.isFinite(seconds) ? seconds : 1)) * 1000);
      if (signal?.aborted) abort();
      else signal?.addEventListener("abort", abort, { once: true });
    });
    resp = await fetch(url, init);
  }
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      const body = await resp.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {
      /* keep statusText */
    }
    throw new Error(`${resp.status}: ${detail}`);
  }
  return resp.json() as Promise<T>;
}

export interface ExampleScenario {
  dataset_id: string;
  title: string;
  description: string;
  highlights: string[];
  zones: Record<string, string[]>;
  timeframe: string;
}

export type ZoneDraft = { name: string; places: string[] };

interface IntervalPage<T> {
  rows: T[]; row_count: number; total_count: number;
  offset: number; next_offset: number | null;
}

/** Never publish a partial replay/flow table as a complete analysis. */
async function allIntervalPages<T>(url: string, signal?: AbortSignal) {
  const rows: T[] = [];
  let offset = 0;
  let total: number | undefined;
  do {
    const page = await req<IntervalPage<T>>(`${url}?offset=${offset}`, { signal });
    if (!Number.isSafeInteger(page.total_count) || page.total_count < 0 ||
        page.offset !== offset || page.row_count !== page.rows.length ||
        (total !== undefined && page.total_count !== total) ||
        offset + page.rows.length > page.total_count ||
        (page.next_offset !== null &&
          (page.rows.length === 0 || page.next_offset !== offset + page.rows.length)) ||
        (page.next_offset === null && offset + page.rows.length !== page.total_count)) {
      throw new Error('Incomplete replay data: reload the analysis. No partial results are displayed.');
    }
    total = page.total_count;
    for (const row of page.rows) rows.push(row);
    if (page.next_offset === null) break;
    offset = page.next_offset;
  } while (true);
  return { rows, row_count: rows.length };
}

export const api = {
  selectedTrends: (id: string, selection: TrendSelectionRequest) => req<TrendSelectionResult>(`/api/analyses/${id}/trends/selection`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(selection),
  }),
  demo: () => req<DemoInfo>("/api/demo"),
  examples: () => req<{ examples: ExampleScenario[] }>("/api/examples"),
  datasets: () => req<Dataset[]>("/api/datasets"),
  uploadDataset: (log: File, pnml: File | null) => {
    const form = new FormData();
    form.append("log", log);
    if (pnml) form.append("pnml", pnml);
    return req<Dataset>("/api/datasets", { method: "POST", body: form });
  },
  modelGraph: (datasetId: string) => req<ModelGraph>(`/api/datasets/${datasetId}/model`),
  validateZones: (datasetId: string, zones: ZoneDraft[] | Record<string, string[]>) =>
    req<ZoneValidation>(`/api/datasets/${datasetId}/zones/validate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ zones }),
    }),
  suggestPlaces: (datasetId: string, activities: string[]) =>
    req<{ places: string[] }>(`/api/datasets/${datasetId}/zones/suggest`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ activities }),
    }),
  createAnalysis: (datasetId: string, zones: Record<string, string[]>, timeframe: string) =>
    req<AnalysisCreated>(`/api/datasets/${datasetId}/analyses`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ zones, timeframe }),
    }),
  job: (jobId: string) => req<JobInfo>(`/api/jobs/${jobId}`),
  analysis: (id: string) => req<AnalysisMeta>(`/api/analyses/${id}`),
  metricCatalog: (id: string) => req<MetricCatalog>(`/api/analyses/${id}/metrics`),
  overview: (id: string) => req<Overview>(`/api/analyses/${id}/overview`),
  features: (id: string, params?: { zones?: string[]; metrics?: string[] }) => {
    const q = new URLSearchParams();
    if (params?.zones?.length) q.set("zones", params.zones.join(","));
    if (params?.metrics?.length) q.set("metrics", params.metrics.join(","));
    const qs = q.toString();
    return req<{ rows: Record<string, unknown>[]; row_count: number }>(
      `/api/analyses/${id}/features${qs ? `?${qs}` : ""}`,
    );
  },
  bpmnXml: async (datasetId: string) => {
    await sessionInfo();
    const resp = await fetch(`/api/datasets/${datasetId}/bpmn.xml`);
    if (!resp.ok) {
      const body = await resp.json().catch(() => null);
      throw new Error(body?.detail ?? "BPMN could not be loaded. Use the Petri net or try again.");
    }
    return resp.text();
  },
  processTreeSvgUrl: (datasetId: string) => `/api/datasets/${datasetId}/process-tree.svg`,
  advancedAlerts: (
    id: string,
    rules: { metric: string; op: string; threshold: number }[],
    combineMode: "ANY" | "ALL",
    lookbackWindows: number,
  ) =>
    req<{ flagged_rows: Record<string, unknown>[] }>(`/api/analyses/${id}/alerts/advanced`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        rules,
        combine_mode: combineMode,
        lookback_windows: lookbackWindows,
      }),
    }),
  selectionChangepoints: (id: string, zones?: string[], metrics?: string[], strictness?: number) => {
    const q = new URLSearchParams();
    if (zones?.length) q.set("zones", zones.join(","));
    if (metrics?.length) q.set("metrics", metrics.join(","));
    if (strictness !== undefined) q.set("cp_strictness", String(strictness));
    return req<SelectionChanges>(`/api/analyses/${id}/changepoints/selection?${q}`);
  },
  dependencyPair: (id: string, srcMetric: string, tgtMetric: string, maxLag: number) =>
    req<{ note: string; rows: Record<string, unknown>[] }>(
      `/api/analyses/${id}/dependencies/pair?src_metric=${encodeURIComponent(srcMetric)}&tgt_metric=${encodeURIComponent(tgtMetric)}&max_lag=${maxLag}`,
    ),
  diagnostics: (id: string) =>
    req<{
      zone_diagnostics: Record<string, unknown>[];
      place_diagnostics: Record<string, unknown>[];
    }>(`/api/analyses/${id}/diagnostics`),
  tokenIntervals: (id: string, signal?: AbortSignal) =>
    allIntervalPages<Record<string, unknown>>(`/api/analyses/${id}/token-intervals`, signal),
  zoneStays: (id: string, signal?: AbortSignal) =>
    allIntervalPages<ZoneStay>(`/api/analyses/${id}/zone-stays`, signal),
  queueing: (id: string) =>
    req<{ note: string; zones: QueueingZoneProfile[] }>(`/api/analyses/${id}/queueing`),
  handovers: (id: string, periods?: number) =>
    req<{
      pairs: HandoverPair[];
      handover_count: number;
      periods: { start: string; end: string; pairs: HandoverPair[] }[];
    }>(`/api/analyses/${id}/handovers${periods ? `?periods=${periods}` : ""}`),
  comparePeriods: (id: string, startA: string, endA: string, startB: string, endB: string) => {
    const q = new URLSearchParams({ start_a: startA, end_a: endA, start_b: startB, end_b: endB });
    return req<{
      note: string;
      slice_a: { start: string; end: string };
      slice_b: { start: string; end: string };
      rows: {
        zone: string;
        metric: string;
        metric_label: string;
        mean_a: number;
        mean_b: number;
        delta: number;
        rel_delta: number | null;
        n_a: number;
        n_b: number;
        p_value: number;
        q_value: number;
        significant: boolean;
      }[];
    }>(`/api/analyses/${id}/compare?${q}`);
  },
  caseEstimates: (id: string, at?: string) =>
    req<{
      note: string;
      at: string;
      zones: {
        zone: string;
        open_cases: number;
        median_age_s: number | null;
        median_est_remaining_s: number | null;
      }[];
      cases: {
        case_id: string;
        zone: string;
        age_s: number;
        est_remaining_p50_s: number | null;
        est_remaining_p25_s: number | null;
        est_remaining_p75_s: number | null;
        support_n: number;
        actual_remaining_s: number | null;
      }[];
    }>(`/api/analyses/${id}/case-estimates${at ? `?at=${encodeURIComponent(at)}` : ""}`),
  whatif: (id: string, zone: string, capacityMultiplier: number) =>
    req<{
      note: string;
      zone: string;
      cases: number;
      calibration: {
        fitted_capacity: number;
        measured_mean_sojourn_s: number;
        simulated_mean_sojourn_s: number;
        relative_error: number;
        calibrated: boolean;
      };
      capacity_multiplier: number;
      whatif_capacity: number;
      baseline: { mean_wait_s: number; p90_wait_s: number; peak_backlog: number };
      whatif: { mean_wait_s: number; p90_wait_s: number; peak_backlog: number };
      curves: { t: string[]; measured_occ: number[]; baseline_occ: number[]; whatif_occ: number[] };
    }>(
      `/api/analyses/${id}/whatif?zone=${encodeURIComponent(zone)}&capacity_multiplier=${capacityMultiplier}`,
    ),
  trendCi: (id: string) =>
    req<{
      note: string;
      metric: string;
      rows: { zone: string; window_start: string; mean_s: number; lo_s: number | null; hi_s: number | null; n: number }[];
    }>(`/api/analyses/${id}/trends/ci`),
  drift: (id: string, halfWindow?: number) =>
    req<{ note: string; half_window: number; rows: { zone: string; window_start: string; drift_score: number | null }[] }>(
      `/api/analyses/${id}/drift${halfWindow ? `?half_window=${halfWindow}` : ""}`,
    ),
  bottlenecks: (id: string) =>
    req<{
      note: string;
      windows: string[];
      zones: { zone: string; states: BottleneckState[]; counts: Record<BottleneckState, number> }[];
      edges: { src: string; tgt: string }[];
    }>(`/api/analyses/${id}/bottlenecks`),
  alerts: (id: string) =>
    req<{
      thresholds: Record<string, number>;
      flagged_rows: Record<string, unknown>[];
      per_zone_summary: Record<string, unknown>[];
    }>(`/api/analyses/${id}/alerts`),
  trends: (id: string, zones?: string[], metrics?: string[], normalize?: boolean) => {
    const q = new URLSearchParams();
    if (zones?.length) q.set("zones", zones.join(","));
    if (metrics?.length) q.set("metrics", metrics.join(","));
    if (normalize) q.set("normalize", "true");
    return req<{ rows: TrendRecord[] }>(`/api/analyses/${id}/trends?${q}`);
  },
  changepoints: (id: string, zones?: string[], metrics?: string[], strictness = 50) => {
    const q = new URLSearchParams();
    if (zones?.length) q.set("zones", zones.join(","));
    if (metrics?.length) q.set("metrics", metrics.join(","));
    q.set("cp_strictness", String(strictness));
    return req<{ rows: ChangePointRecord[] }>(`/api/analyses/${id}/changepoints?${q}`);
  },
  dependencies: (id: string) =>
    req<{
      note: string;
      metric_options: string[];
      rows: Record<string, unknown>[];
      row_count_all: number;
    }>(`/api/analyses/${id}/dependencies`),
  forecastOptions: (id: string, study?: string | null) => req<ForecastOptions>(`/api/analyses/${id}/prediction/options${study ? `?study_id=${encodeURIComponent(study)}` : ''}`),
  retrospectiveOptions:(id:string)=>req<RetrospectiveOptions>(`/api/analyses/${id}/prediction/retrospective/options`),
  retrospectivePrediction:(id:string,body:Record<string,unknown>)=>req<RetrospectiveResult>(`/api/analyses/${id}/prediction/retrospective`,{
    method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),
  }),
  calibratePrediction: (id: string, end: string) => req<ModelGraph & { calibration: { id: string; calibration_end: string; observed_events: number; observed_cases: number } }>(`/api/analyses/${id}/prediction/calibrate`, {
    method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({calibration_end:end}),
  }),
  freezePrediction: (id: string, calibration: string, zones: ZoneDraft[]) => req<{id:string}>(`/api/analyses/${id}/prediction/studies`, {
    method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({calibration_id:calibration,zones}),
  }),
  prediction: (id: string, body: Record<string, unknown>) =>
    req<ForecastResult>(`/api/analyses/${id}/prediction`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    }),
};

/** Subscribe to a job's SSE progress stream, with a polling safety net so a
 * dropped stream can never leave the UI stuck in "running". Returns an
 * unsubscribe fn. */
export function subscribeJobEvents(
  jobId: string,
  onEvent: (ev: JobEvent) => void,
  onEnd: (status: "done" | "error") => void,
): () => void {
  const source = new EventSource(`/api/jobs/${jobId}/events`);
  let ended = false;

  const end = (status: "done" | "error") => {
    if (ended) return;
    ended = true;
    source.close();
    window.clearInterval(poller);
    onEnd(status);
  };

  source.onmessage = (msg) => {
    const ev = JSON.parse(msg.data) as JobEvent;
    if (ev.stage === "__done__") {
      end(ev.status === "error" ? "error" : "done");
    } else {
      onEvent(ev);
    }
  };
  // Safety net: if the SSE connection dies (server restart, proxy timeout),
  // a slow poll still resolves the job's terminal state.
  const poller = window.setInterval(async () => {
    try {
      const job = await api.job(jobId);
      for (const ev of job.events) if (ev.stage !== "__done__") onEvent(ev);
      if (job.status === "done" || job.status === "error") end(job.status);
    } catch (error) {
      if (error instanceof Error && /^(404|410):/.test(error.message)) {
        onEvent({ stage: "session", status: "error", detail: "Job is no longer available. The session may have expired or the server restarted.", ts: Date.now() / 1000 });
        end("error");
      }
    }
  }, 5000);

  return () => {
    ended = true;
    source.close();
    window.clearInterval(poller);
  };
}
