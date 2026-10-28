/** A dataset-independent introduction to the analysis workspace. */

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useLocation, useNavigate } from "react-router-dom";

const STEPS: { route: string; title: string; text: string }[] = [
  {
    route: "/",
    title: "Data, model & zones",
    text: "Upload an event log and a Petri net, or discover a model from the log. Define zones by selecting model places, validate the configuration, choose a time window, and run the analysis. Example scenarios are optional starting points.",
  },
  {
    route: "/overview",
    title: "Overview & alerts",
    text: "Inspect zone occupancy at the latest analysis window and alerts across recent windows. Check their dates: they can describe different periods. Token counts and case counts differ when a case holds multiple parallel tokens.",
  },
  {
    route: "/replay",
    title: "Token replay",
    text: "Play the alignment-based reconstruction or select a historical moment. Node size shows reconstructed place occupancy. Click a place to inspect its cases and follow a case through the model; this is reconstructed behavior, not a uniquely observed token path.",
  },
  {
    route: "/trends",
    title: "Trends & change points",
    text: "Plot selected zone metrics over time and inspect vertical change-point markers. Local changes describe individual series; overall changes combine selected components. Drift scores and period comparisons provide separate views of changing behavior, without identifying causes.",
  },
  {
    route: "/flow",
    title: "Flow patterns",
    text: "Explore case-zone stays: cumulative entries and exits, durations, batching, overtaking and handovers. Repeated visits can contribute multiple stays per case. Queueing diagnostics and capacity scenarios are experimental interpretations, not observed resource states.",
  },
  {
    route: "/dependencies",
    title: "Dependencies",
    text: "Look for zone metrics that move together with a delay. Inspect the correlation, lag, available windows and significance together. These are associations, not evidence that one zone causes a change in another.",
  },
  {
    route: "/prediction",
    title: "Prediction",
    text: "Compare three classifiers for a threshold condition in a selected later window. Inspect class balance, temporal evaluation, simple baselines, the decision tree and SHAP explanations. Inputs use complete-trace reconstruction: these exploratory retrospective scores do not validate live forecasting.",
  },
  {
    route: "/metrics",
    title: "Metrics Reference",
    text: "Look up each metric’s meaning, identifier, unit, scope and calculation. Search or filter by token, case or conformance scope. End-of-window occupancy is a snapshot; average occupancy summarizes the window. Durations use seconds and ratios use fractions in metric charts and series tables; unavailable values are not zero.",
  },
];

// The portal escapes sidebar stacking contexts. A manual popover uses the
// browser top layer; when a native modal opens, host it inside that modal so
// its focus/inertness rules continue to apply. No backdrop blocks page controls.
export default function Tour() {
  const [step, setStep] = useState<number | null>(null);
  const [host, setHost] = useState<HTMLElement>(document.body);
  const [anchor, setAnchor] = useState<DOMRect | null>(null);
  const [position, setPosition] = useState({ left: 12, top: 12 });
  const trigger = useRef<HTMLButtonElement>(null);
  const layer = useRef<HTMLDivElement>(null);
  const tooltip = useRef<HTMLDivElement>(null);
  const next = useRef<HTMLButtonElement>(null);
  const navigate = useNavigate();
  const location = useLocation();
  const open = step !== null;

  const close = useCallback(() => {
    setStep(null);
    setHost(document.body);
    requestAnimationFrame(() => {
      const dialogs = [...document.querySelectorAll<HTMLDialogElement>("dialog:modal")];
      const modal = host.matches(":modal") ? host : dialogs[dialogs.length - 1];
      if (modal) modal.querySelector<HTMLElement>("button, input, [tabindex='0']")?.focus();
      else trigger.current?.focus();
    });
  }, [host]);

  const go = (i: number) => {
    setStep(i);
    navigate(STEPS[i].route);
  };

  useEffect(() => {
    if (!open) return;
    const syncHost = (records: MutationRecord[] = []) => {
      const opened = records.map((r) => r.target).filter(
        (el): el is HTMLDialogElement => el instanceof HTMLDialogElement && el.matches(":modal"),
      ).pop();
      const dialogs = [...document.querySelectorAll<HTMLDialogElement>("dialog:modal")];
      setHost((current) => opened ?? (current.matches(":modal") ? current : dialogs[dialogs.length - 1] ?? document.body));
    };
    syncHost();
    const observer = new MutationObserver(syncHost);
    observer.observe(document.body, { subtree: true, childList: true, attributes: true, attributeFilter: ["open"] });
    const onToggle = (event: Event) => {
      // A newer popover may otherwise cover ours in top-layer insertion order.
      if (event.target !== layer.current && event.target instanceof HTMLElement && event.target.matches(":popover-open")) {
        layer.current?.hidePopover?.();
        layer.current?.showPopover?.();
      }
    };
    document.addEventListener("toggle", onToggle, true);
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        close();
      }
      if (event.key === "Tab" && tooltip.current?.contains(document.activeElement)) {
        // Safari's default keyboard settings skip buttons. Keep the tour's
        // internal order consistent, while allowing Tab to leave either end.
        const buttons = [...tooltip.current.querySelectorAll<HTMLButtonElement>("button:not(:disabled)")];
        const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
        const adjacent = index >= 0 ? buttons[index + (event.shiftKey ? -1: 1)]: undefined;
        if (adjacent) {
          event.preventDefault();
          adjacent.focus();
        }
      }
    };
    document.addEventListener("keydown", onKey, true);
    return () => {
      observer.disconnect();
      document.removeEventListener("toggle", onToggle, true);
      document.removeEventListener("keydown", onKey, true);
    };
  }, [open, close]);

  useLayoutEffect(() => {
    if (!open) return;
    // React 18's DOM typings predate the popover attribute.
    layer.current?.setAttribute("popover", "manual");
    layer.current?.showPopover?.();
    next.current?.focus({ preventScroll: true });
  }, [open, host, step]);

  useEffect(() => {
    if (!open) return;
    // Keep the route and step in agreement on browser Back or sidebar navigation.
    const matching = STEPS.findIndex((s) => s.route === location.pathname);
    if (matching >= 0) setStep(matching);
    else close();
  }, [location.pathname, open, close]);

  useLayoutEffect(() => {
    if (!open) return;
    let frame = 0;
    let target: HTMLElement | null = null;
    const measure = () => {
      const scope = host === document.body ? document.querySelector("main") : host;
      const candidatesIn = (selector: string) => [...(scope?.querySelectorAll<HTMLElement>(selector) ?? [])]
     .find((el) => !layer.current?.contains(el) && el.getClientRects().length > 0);
      const found = candidatesIn("[data-tour-target]") ?? candidatesIn("h1, h2") ??
        (host !== document.body ? candidatesIn("button, input, select") : null) ?? null;
      if (found !== target) {
        target = found;
        if (target) resize.observe(target);
        target?.scrollIntoView({ block: "nearest" });
      }
      const box = target?.getBoundingClientRect() ?? null;
      setAnchor(box);
      const tip = tooltip.current?.getBoundingClientRect();
      if (!tip) return;
      const width = document.documentElement.clientWidth;
      const height = window.innerHeight;
      const clamp = (x: number, max: number) => Math.max(12, Math.min(x, Math.max(12, max)));
      const avoid = host === document.body ? box : host.getBoundingClientRect();
      const choices = avoid ? [
        [avoid.left, avoid.bottom + 12], [avoid.right + 12, avoid.top],
        [avoid.left - tip.width - 12, avoid.top], [avoid.left, avoid.top - tip.height - 12],
        [width - tip.width - 12, height - tip.height - 12], [12, height - tip.height - 12],
      ] : [[width - tip.width - 12, height - tip.height - 12]];
      const candidates = choices.map(([x, y]) => ({ left: clamp(x, width - tip.width - 12), top: clamp(y, height - tip.height - 12) }));
      const controls = [...(scope?.querySelectorAll<HTMLElement>("button, input, select, textarea, a, summary, [role=button]") ?? [])]
     .filter((el) => !layer.current?.contains(el)).map((el) => el.getBoundingClientRect());
      const area = (p: { left: number; top: number }, rect: DOMRect) =>
        Math.max(0, Math.min(p.left + tip.width, rect.right) - Math.max(p.left, rect.left)) *
        Math.max(0, Math.min(p.top + tip.height, rect.bottom) - Math.max(p.top, rect.top));
      // Prioritize access to controls over proximity to the highlighted title.
      const overlap = (p: { left: number; top: number }) =>
        (avoid ? area(p, avoid) : 0) + controls.reduce((sum, rect) => sum + 100 * area(p, rect), 0);
      candidates.sort((a, b) => overlap(a) - overlap(b));
      setPosition(candidates[0]);
    };
    const schedule = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(measure);
    };
    const resize = new ResizeObserver(schedule);
    if (tooltip.current) resize.observe(tooltip.current);
    const observer = new MutationObserver((records) => {
      if (records.some((r) => !layer.current?.contains(r.target))) schedule();
    });
    observer.observe(document.body, { subtree: true, childList: true });
    window.addEventListener("resize", schedule);
    window.addEventListener("scroll", schedule, true);
    document.addEventListener("animationend", schedule, true);
    schedule();
    return () => {
      cancelAnimationFrame(frame);
      resize.disconnect();
      observer.disconnect();
      window.removeEventListener("resize", schedule);
      window.removeEventListener("scroll", schedule, true);
      document.removeEventListener("animationend", schedule, true);
    };
  }, [open, step, host, location.pathname]);

  const s = step === null ? null : STEPS[step];
  return <>
    <button ref={trigger} onClick={() => go(0)} aria-expanded={open} title="Guided tour of ZoneMiner">✦ Tour</button>
    {s && createPortal(
      <div ref={layer} className="tour-layer" data-testid="tour-layer">
        {anchor && <div className="tour-highlight" data-testid="tour-highlight" style={{ left: anchor.left - 4, top: anchor.top - 4, width: anchor.width + 8, height: anchor.height + 8 }} />}
        <div ref={tooltip} className="tour-tooltip" role="dialog" aria-modal="false" aria-labelledby="tour-title" aria-describedby="tour-description" style={position}>
          <div className="help" aria-live="polite">Step {step! + 1} / {STEPS.length}</div>
          <h2 id="tour-title">{s.title}</h2>
          <p id="tour-description">{s.text}</p>
          {host !== document.body && <p className="help">Close the open dialog to return to this page.</p>}
          <div className="row">
            <button onClick={() => go(step! - 1)} disabled={step === 0}>← Back</button>
            <button ref={next} className="primary" onClick={() => step! < STEPS.length - 1 ? go(step! + 1) : close()}>{step! < STEPS.length - 1 ? "Next →" : "Finish"}</button>
            <button onClick={close} aria-label="Close tour" style={{ marginLeft: "auto" }}>✕</button>
          </div>
        </div>
      </div>, host,
    )}
  </>;
}
