/** Theme helpers shared by graphs and charts; no chart runtime is loaded here. */

function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

export function themedLayout(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  const text = cssVar("--text-2");
  const grid = cssVar("--grid");
  const baseline = cssVar("--baseline");
  return {
    paper_bgcolor: cssVar("--surface"),
    plot_bgcolor: cssVar("--surface"),
    font: { family: "system-ui, -apple-system, 'Segoe UI', sans-serif", size: 12, color: text },
    margin: { l: 48, r: 16, t: 8, b: 40 },
    hovermode: "x unified",
    xaxis: { gridcolor: grid, linecolor: baseline, zeroline: false },
    yaxis: { gridcolor: grid, linecolor: baseline, zeroline: false, rangemode: "tozero" },
    legend: { orientation: "h", y: -0.18 },
    ...overrides,
  };
}

/** Resolve a CSS var reference like "var(--zone-1)" to its hex value for Plotly. */
export function resolveColor(color: string): string {
  const m = color.match(/^var\((--[a-z0-9-]+)\)$/i);
  return m ? cssVar(m[1]) : color;
}
