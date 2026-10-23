import type { MetricInfo } from "../api";

// API values stay canonical; normalized series must not inherit duration units.
export const metricUnit = (metric?: MetricInfo, normalized = false) =>
  normalized ? "z-score" : metric?.unit_label ?? "unit unavailable";
export const metricAxisLabel = (metric?: MetricInfo, normalized = false, fallback = "Metric") =>
  `${metric?.label ?? fallback} (${metricUnit(metric, normalized)})`;

export function formatMetricValue(value: unknown, metric?: MetricInfo, normalized = false): string {
  if (value == null || !Number.isFinite(Number(value))) return "Unavailable";
  return `${Number(value).toLocaleString(undefined, { maximumFractionDigits: 3 })} ${metricUnit(metric, normalized)}`;
}

// Only explicit compact summaries convert seconds, never chart/series data.
export function formatDuration(seconds: unknown): string {
  if (seconds == null || !Number.isFinite(Number(seconds))) return "–";
  const s = Number(seconds);
  return s >= 172800 ? `${(s / 86400).toFixed(1)} d` : s >= 3600 ? `${(s / 3600).toFixed(1)} h`
    : s >= 60 ? `${(s / 60).toFixed(1)} min` : `${s.toFixed(1)} s`;
}
