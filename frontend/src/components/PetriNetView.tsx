/** Interactive Petri-net view (cytoscape.js + dagre layout).
 *
 * Modes: edit (click a place to assign/unassign it to the active zone) and
 * view with an optional replay overlay (per-place token counts as node size
 * + badge). Fully theme-aware: node/edge colors come from the design tokens
 * and restyle live when the theme toggles. Zone places carry their zone's
 * color with a soft glow; replay size changes animate smoothly.
 */

import cytoscape, { type Core, type ElementDefinition } from "cytoscape";
import dagre from "cytoscape-dagre";
import { useEffect, useMemo, useRef } from "react";
import type { BottleneckState, ModelGraph } from "../api";
import { resolveColor } from "../lib/plot";
import { STATE_STYLE } from "../lib/states";

cytoscape.use(dagre);

function tokens() {
  const s = getComputedStyle(document.documentElement);
  const v = (n: string) => s.getPropertyValue(n).trim();
  return {
    place: v("--net-place"),
    stroke: v("--net-stroke"),
    transBg: v("--net-trans-bg"),
    transStroke: v("--net-trans-stroke"),
    silent: v("--net-silent"),
    edge: v("--net-edge"),
    label: v("--net-label"),
    text: v("--text"),
  };
}

export interface PetriNetViewProps {
  graph: ModelGraph;
  zoneOf: Record<string, string>;
  zoneColorOf: (zone: string) => string;
  onPlaceClick?: (place: string) => void;
  tokenCounts?: Record<string, number>;
  highlightZone?: string | null;
  /** Bottleneck-state overlay (replay): non-flowing zones get a halo in the
   * state's color instead of the soft zone glow. */
  zoneStates?: Record<string, BottleneckState>;
  height?: number;
}

export default function PetriNetView({
  graph,
  zoneOf,
  zoneColorOf,
  onPlaceClick,
  tokenCounts,
  highlightZone,
  zoneStates,
  height = 420,
}: PetriNetViewProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const clickRef = useRef(onPlaceClick);
  clickRef.current = onPlaceClick;

  const elements: ElementDefinition[] = useMemo(() => {
    const els: ElementDefinition[] = [];
    for (const p of graph.places) {
      els.push({ data: { id: p, kind: "place", label: p.replace(/^p_/, "") } });
    }
    for (const t of graph.transitions) {
      els.push({
        data: {
          id: t.name,
          kind: t.label ? "transition" : "silent",
          label: t.label ? t.label.replace(/_/g, " ") : "",
        },
      });
    }
    graph.arcs.forEach((a, i) => {
      els.push({ data: { id: `e${i}`, source: a.source, target: a.target, weightLabel: a.weight > 1 ? String(a.weight) : "" } });
    });
    return els;
  }, [graph]);

  // (re)build the graph when the structure changes
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const t = tokens();
    const cy = cytoscape({
      container: el,
      elements,
      layout: { name: "dagre", rankDir: "LR", nodeSep: 20, rankSep: 50 } as never,
      wheelSensitivity: 0.2,
      style: [
        {
          selector: "node[kind='place']",
          style: {
            shape: "ellipse",
            width: 26,
            height: 26,
            "background-color": t.place,
            "border-width": 2,
            "border-color": t.stroke,
            label: "data(label)",
            "font-size": 8,
            "font-family": "Inter Variable, system-ui, sans-serif",
            color: t.label,
            "text-valign": "bottom",
            "text-margin-y": 5,
            "transition-property": "width height background-color border-color opacity",
            "transition-duration": 180,
          } as never,
        },
        {
          selector: "node[kind='transition']",
          style: {
            shape: "round-rectangle",
            width: 88,
            height: 27,
            "corner-radius": 6,
            "background-color": t.transBg,
            "border-width": 1.4,
            "border-color": t.transStroke,
            label: "data(label)",
            "font-size": 8,
            "font-family": "Inter Variable, system-ui, sans-serif",
            "font-weight": 500,
            "text-wrap": "wrap",
            "text-max-width": "82px",
            "text-valign": "center",
            color: t.text,
          } as never,
        },
        {
          selector: "node[kind='silent']",
          style: {
            shape: "round-rectangle",
            width: 13,
            height: 27,
            "corner-radius": 4,
            "background-color": t.silent,
            "border-width": 0,
          } as never,
        },
        {
          selector: "edge",
          style: {
            label: "data(weightLabel)",
            "font-size": 10,
            color: t.text,
            "text-background-color": t.place,
            "text-background-opacity": 1,
            width: 1.3,
            "line-color": t.edge,
            "target-arrow-color": t.edge,
            "target-arrow-shape": "triangle",
            "arrow-scale": 0.75,
            "curve-style": "bezier",
          },
        },
      ],
    });
    cy.on("tap", "node[kind='place']", (ev) => clickRef.current?.(ev.target.id()));
    cy.fit(undefined, 26);
    cyRef.current = cy;

    const observer = new MutationObserver(() => restyle(cy));
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => {
      observer.disconnect();
      cy.destroy();
      cyRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [elements]);

  // restyle on zone/overlay/theme changes (no relayout)
  const restyle = (cy: Core) => {
    const t = tokens();
    cy.batch(() => {
      cy.nodes("[kind='transition']").style({
        "background-color": t.transBg,
        "border-color": t.transStroke,
        color: t.text,
      });
      cy.nodes("[kind='silent']").style({ "background-color": t.silent });
      cy.edges().style({ "line-color": t.edge, "target-arrow-color": t.edge, color: t.text, "text-background-color": t.place });
      for (const p of graph.places) {
        const node = cy.getElementById(p);
        if (node.empty()) continue;
        const zone = zoneOf[p];
        const color = zone ? resolveColor(zoneColorOf(zone)) : "";
        const count = tokenCounts?.[p] ?? 0;
        const dimmed = highlightZone && zone !== highlightZone;
        const replayMode = Boolean(tokenCounts);
        const size = replayMode ? 17 + Math.min(count, 25) * 2.3 : 26;
        const state = zone ? zoneStates?.[zone] : undefined;
        const alerting = state && state !== "flowing";
        node.style({
          "background-color": zone ? color : t.place,
          "background-opacity": zone ? (replayMode ? 0.4 : 0.9) : 1,
          "border-color": zone ? color : t.stroke,
          "border-width": zone ? 2.6 : 2,
          // soft glow for zone membership; stronger when tokens are present,
          // and repainted in the bottleneck state's color when a zone alerts
          "underlay-color": alerting ? STATE_STYLE[state].color : zone ? color : t.stroke,
          "underlay-padding": alerting ? 10 : zone ? (replayMode && count > 0 ? 7 : 3.5) : 0,
          "underlay-opacity": alerting ? 0.4 : zone ? (replayMode && count > 0 ? 0.22 : 0.12) : 0,
          "underlay-shape": "ellipse",
          opacity: dimmed ? 0.22 : 1,
          width: size,
          height: size,
          label: replayMode && count > 0 ? String(count) : node.data("label"),
          "font-size": replayMode && count > 0 ? 11 : 8,
          "font-weight": replayMode && count > 0 ? 700 : 400,
          "text-valign": replayMode && count > 0 ? "center" : "bottom",
          color: replayMode && count > 0 ? t.text : t.label,
        } as never);
      }
    });
  };

  useEffect(() => {
    if (cyRef.current) restyle(cyRef.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [graph.places, zoneOf, zoneColorOf, tokenCounts, highlightZone, zoneStates]);

  return <div ref={containerRef} className="net-frame" style={{ height }} />;
}
