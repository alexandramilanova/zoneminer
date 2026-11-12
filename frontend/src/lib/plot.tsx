/** Thin theme-aware wrapper around plotly.js.
 *
 * Reads the design tokens off the document so charts always match the active
 * light/dark theme, and re-renders on theme change. Zone series must be
 * colored by the caller via state.zoneColor so identity is consistent
 * everywhere.
 */

// @ts-expect-error plotly ships no types for the dist bundles
import Plotly from "plotly.js-basic-dist-min";
import { useEffect, useRef, useState } from "react";
import { fileStem } from "./download";

export interface PlotSpec {
  data: Record<string, unknown>[];
  layout?: Record<string, unknown>;
  onHover?: (ev: unknown) => void;
  onClick?: (ev: unknown) => void;
  height?: number;
  downloadName?: string;
}

import { themedLayout } from "./plotTheme";
export { resolveColor, themedLayout } from "./plotTheme";

export function Plot({ data, layout, onHover, onClick, height = 320, downloadName = "zone-analytics-plot" }: PlotSpec) {
  const ref = useRef<HTMLDivElement>(null);
  const hoverRef = useRef(onHover);
  const clickRef = useRef(onClick);
  hoverRef.current = onHover;
  clickRef.current = onClick;
  const lastSpec = useRef("");
  const queue = useRef<Promise<void>>(Promise.resolve());
  const lifetime = useRef(0);
  const [themeRevision, setThemeRevision] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [renderedKey, setRenderedKey] = useState("");
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const spec = JSON.stringify({ data, layout, height });
  const ready = renderedKey === `${themeRevision}:${spec}` && !error;

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    let current = true;
    const key = `${themeRevision}:${spec}`;
    // Plotly.react is asynchronous. Serialize updates and skip queued obsolete
    // specs so older layouts cannot finish after their replacements.
    queue.current = queue.current.then(async () => {
      if (!current || key === lastSpec.current) return;
      lastSpec.current = key;
      try {
        const parsed = JSON.parse(spec);
        await Plotly.react(el, parsed.data, { ...themedLayout(), height: parsed.height, ...parsed.layout }, {
          displayModeBar: false, responsive: true,
        });
        if (!current) return;
        setError(null);
        setRenderedKey(key);
        const anyEl = el as any;
        if (!anyEl.__handlersBound) {
          anyEl.__handlersBound = true;
          anyEl.on?.("plotly_hover", (ev: unknown) => hoverRef.current?.(ev));
          anyEl.on?.("plotly_click", (ev: unknown) => clickRef.current?.(ev));
        }
      } catch (failure) {
        lastSpec.current = "";
        if (current) setError(String(failure));
      }
    });
    return () => { current = false; };
  }, [spec, themeRevision]);

  useEffect(() => {
    const observer = new MutationObserver(() => setThemeRevision((n) => n + 1));
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const el = ref.current;
    const generation = ++lifetime.current;
    return () => {
      // A StrictMode remount supersedes this cleanup before the queue settles.
      // On a real unmount, wait for in-flight rendering before purging the node.
      void queue.current.then(() => {
        if (generation !== lifetime.current || !el) return;
        Plotly.purge(el);
        lastSpec.current = "";
        (el as any).__handlersBound = false;
      });
    };
  }, []);

  const download = async (format: "png" | "svg") => {
    if (!ref.current || !ready) return;
    setExporting(true);
    setExportError(null);
    try {
      await queue.current;
      await Plotly.downloadImage(ref.current, { format, filename: fileStem(downloadName), scale: 2 });
    } catch {
      setExportError("The plot could not be downloaded. Please try again.");
    } finally { setExporting(false); }
  };
  return <><div className="row" style={{ justifyContent: "flex-end", gap: 8 }}>
    <button disabled={!ready || exporting} onClick={() => download("png")}>Download plot (PNG)</button>
    <button disabled={!ready || exporting} onClick={() => download("svg")}>Download plot (SVG)</button>
  </div><div ref={ref} />{error && <div role="alert" className="notice error">Chart unavailable: {error}</div>}
    {exportError && <div role="alert" className="notice error">{exportError}</div>}</>;
}
