import type { ForecastShap as ShapResult } from "../api";
import { Plot, themedLayout } from "../lib/plot";
import { DataTable } from "./shared";

export default function ForecastShap({ data }: { data: ShapResult }) {
  if (data.status === "not_applicable") return null;
  if (data.status !== "available") return <p role="status">SHAP explanation unavailable: {data.reason ?? data.status}</p>;
  const rows = data.rows.filter(r => r.mean_abs_shap > 0);
  if (!rows.length) return <p>No nonzero SHAP effects on the explained training sample.</p>;
  return <div data-testid="forecast-shap">
    <h3>SHAP feature explanations</h3>
    <p className="help">{data.scope}. Effects explain {data.scale}; positive values increase class-1 output. Background: {data.n_background} training rows; explained: {data.n_explained} training rows. These are model explanations, not causes or held-out performance. Interventional SHAP breaks feature dependence; correlated metrics may share or redistribute credit.</p>
    <Plot data={rows.map((r, rank) => {
      const min = Math.min(...r.feature_values), max = Math.max(...r.feature_values);
      return { type: "scatter", mode: "markers", name: r.feature, showlegend: false,
        x: r.values, y: r.values.map((_, i) => rank + ((i * 7 % 13) - 6) / 32),
        customdata: r.feature_values.map(v => [r.feature, v]),
        marker: { size: 6, opacity: .75, color: r.feature_values.map(v => max > min ? (v - min) / (max - min) : .5),
          colorscale: "Viridis", cmin: 0, cmax: 1, showscale: rank === 0,
          colorbar: { title: { text: "Within-feature value" }, tickvals: [0, 1], ticktext: ["Low", "High"], thickness: 10 } },
        hovertemplate: "%{customdata[0]}<br>Feature value: %{customdata[1]:.4~f}<br>SHAP: %{x:.4~f}<extra></extra>" };
    })} layout={themedLayout({ hovermode: "closest", margin: { l: 270, r: 125, t: 15, b: 55 },
      xaxis: { ...themedLayout().xaxis as object, title: { text: `SHAP value (${data.scale})` }, zeroline: true },
      yaxis: { tickvals: rows.map((_, i) => i), ticktext: rows.map(r => r.feature), autorange: "reversed", automargin: true } })}
      height={Math.max(280, rows.length * 34 + 90)} />
    <details><summary>SHAP variable ranking</summary><DataTable rows={rows.map(r => ({ feature: r.feature, "mean absolute SHAP": r.mean_abs_shap }))} /></details>
  </div>;
}
