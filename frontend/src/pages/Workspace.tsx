/** Data, Model & Zones: upload inputs or choose examples, inspect optional
 * helper diagrams, define zones on the net, and run analysis with progress. */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  api,
  subscribeJobEvents,
  type Dataset,
  type ExampleScenario,
  type JobEvent,
  type ModelGraph,
  type ZoneValidation,
  type ZoneDraft,
} from "../api";
import { useAppState } from "../state";
import { StageProgress } from "../components/shared";
import PetriNetView from "../components/PetriNetView";
import ZonePlaceSuggestions from "../components/ZonePlaceSuggestions";
import { BpmnView, ProcessTreeView } from "../components/ModelViews";

type EditorZone = ZoneDraft & { draftKey: number };

export default function Workspace() {
  const { analysis, setAnalysisId, setWorkspaceDirty } = useAppState();
  const navigate = useNavigate();

  const [datasetId, setDatasetId] = useState<string | null>(analysis?.dataset_id ?? null);
  const [datasetName, setDatasetName] = useState<string>("");
  const [graph, setGraph] = useState<ModelGraph | null>(null);
  const [zoneDrafts, setZoneDraftsRaw] = useState<EditorZone[]>([]);
  const [timeframe, setTimeframe] = useState("D");
  const [validation, setValidation] = useState<ZoneValidation | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [jobEvents, setJobEvents] = useState<JobEvent[]>([]);
  const [running, setRunning] = useState(false);
  const [activeZone, setActiveZone] = useState(0);
  const [showBpmn, setShowBpmn] = useState(false);
  const [noiseThreshold, setNoiseThreshold] = useState(0);
  const [uploadHasModel, setUploadHasModel] = useState(false);
  const [confirmDiscovery, setConfirmDiscovery] = useState(false);
  const [showTree, setShowTree] = useState(false);
  const [examples, setExamples] = useState<ExampleScenario[]>([]);
  const unsubscribe = useRef<(() => void) | null>(null);
  const draftVersion = useRef(0);
  const nextDraftKey = useRef(0);
  const validationRequest = useRef(0);
  const datasetRequest = useRef(0);
  const manualSelection = useRef(false);
  const beginSelection = () => {
    manualSelection.current = true;
    datasetRequest.current += 1;
  };
  const setZoneDrafts = useCallback((update: ZoneDraft[] | ((previous: EditorZone[]) => ZoneDraft[])) => {
    draftVersion.current += 1;
    setValidation(null);
    setError(null);
    setZoneDraftsRaw((previous) => {
      const drafts = typeof update === "function" ? update(previous) : update;
      return drafts.map((zone) => ({ ...zone, draftKey: "draftKey" in zone
        ? (zone as EditorZone).draftKey : nextDraftKey.current++ }));
    });
  }, []);

  const configurationChanged = Boolean(analysis && (
    datasetId !== analysis.dataset_id || timeframe !== analysis.timeframe ||
    JSON.stringify(zoneDrafts.map((z) => [z.name.trim(), z.places.slice().sort()]).sort()) !==
    JSON.stringify(Object.entries(analysis.zone_places).map(([n, p]) => [n, p.slice().sort()]).sort())
  ));

  useEffect(() => {
    setWorkspaceDirty(Boolean(graph && (configurationChanged || busy || running)));
  }, [graph, configurationChanged, busy, running, setWorkspaceDirty]);
  useEffect(() => () => setWorkspaceDirty(false), [setWorkspaceDirty]);

  useEffect(() => {
    api
      .examples()
      .then((r) => setExamples(r.examples))
      .catch(() => setExamples([]));
  }, []);

  const loadExample = async (ex: ExampleScenario) => {
    beginSelection();
    setBusy(`Loading ${ex.title}…`);
    setError(null);
    try {
      if (!await loadDataset(ex.dataset_id, ex.title)) return;
      setZoneDrafts(Object.entries(ex.zones).map(([name, places]) => ({ name, places })));
      setTimeframe(ex.timeframe);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  };

  const loadDataset = useCallback(async (id: string, name: string) => {
    const request = ++datasetRequest.current;
    draftVersion.current += 1;
    setValidation(null);
    setBusy("Loading model…");
    setError(null);
    try {
      const g = await api.modelGraph(id);
      if (request !== datasetRequest.current) return false;
      setActiveZone(0);
      setDatasetId(id);
      setDatasetName(name);
      setGraph(g);
      setNoiseThreshold(g.discovery_noise_threshold ?? 0);
      setConfirmDiscovery(false);
      setShowTree(false);
      setShowBpmn(false);
      setValidation(null);
      return true;
    } catch (e) {
      if (request === datasetRequest.current) setError(String(e));
      return false;
    } finally {
      if (request === datasetRequest.current) setBusy(null);
    }
  }, []);

  // restore state for the current analysis
  useEffect(() => {
    if (analysis && !graph && !manualSelection.current) {
      loadDataset(analysis.dataset_id, "");
      setZoneDrafts(
        Object.entries(analysis.zone_places).map(([name, places]) => ({ name, places })),
      );
      setTimeframe(analysis.timeframe);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [analysis]);

  useEffect(() => () => unsubscribe.current?.(), []);

  const loadDemo = async () => {
    beginSelection();
    setBusy("Loading demo…");
    setError(null);
    try {
      const demo = await api.demo();
      if (!await loadDataset(demo.dataset_id, "Demo: Online Order Fulfillment")) return;
      setZoneDrafts(
        Object.entries(demo.zones).map(([name, places]) => ({ name, places })),
      );
      setTimeframe(demo.timeframe);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  };

  const onUpload = async (ev: React.FormEvent<HTMLFormElement>) => {
    ev.preventDefault();
    const form = ev.currentTarget;
    const logFile = (form.elements.namedItem("log") as HTMLInputElement).files?.[0];
    const pnmlFile = (form.elements.namedItem("pnml") as HTMLInputElement).files?.[0] ?? null;
    if (!logFile) {
      setError("Choose an event log file (.csv or .xes).");
      return;
    }
    beginSelection();
    setBusy("Uploading & parsing…");
    setError(null);
    try {
      const ds: Dataset = await api.uploadDataset(logFile, pnmlFile, noiseThreshold);
      if (!await loadDataset(ds.id, ds.name)) return;
      setZoneDrafts([{ name: "Zone 1", places: [] }]);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  };

  const addZone = () => {
    const names = new Set(zoneDrafts.map((z) => z.name.trim()));
    let number = 1;
    while (names.has(`Zone ${number}`)) number++;
    setActiveZone(zoneDrafts.length);
    setZoneDrafts((previous) => [...previous, { name: `Zone ${number}`, places: [] }]);
  };

  const rediscover = async () => {
    if (!datasetId || busy || running) return;
    beginSelection();
    setBusy("Discovering model…");
    setError(null);
    try {
      const result = await api.rediscover(datasetId, noiseThreshold);
      if (!await loadDataset(result.id, result.name)) return;
      setAnalysisId(null);
      setZoneDrafts([{ name: "Zone 1", places: [] }]);
      setConfirmDiscovery(false);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  };

  const validate = async () => {
    if (!datasetId) return;
    const version = draftVersion.current;
    const request = ++validationRequest.current;
    setError(null);
    setValidation(null);
    setBusy("Validating zones…");
    try {
      const result = await api.validateZones(datasetId, zoneDrafts.map(({ name, places }) => ({ name, places })));
      if (version === draftVersion.current && request === validationRequest.current) {
        setValidation(result);
      }
    } catch (e) {
      if (version === draftVersion.current && request === validationRequest.current) {
        setError(String(e));
      }
    } finally {
      if (request === validationRequest.current) {
        setBusy((current) => current === "Validating zones…" ? null : current);
      }
    }
  };

  const run = async () => {
    if (!datasetId || !validation?.valid || busy || running) return;
    setError(null);
    setJobEvents([]);
    setRunning(true);
    try {
      const created = await api.createAnalysis(datasetId, validation.zone_places, timeframe);
      if (created.cached || !created.job_id) {
        finishRun(created.analysis_id);
        return;
      }
      unsubscribe.current = subscribeJobEvents(
        created.job_id,
        (ev) => setJobEvents((prev) => [...prev, ev]),
        async (status) => {
          if (status === "done") {
            finishRun(created.analysis_id);
            return;
          }
          try {
            const job = await api.job(created.job_id!);
            setError(job.error ?? "Analysis failed");
          } catch (e) {
            setError(`Analysis failed (${String(e)})`);
          } finally {
            setRunning(false);
          }
        },
      );
    } catch (e) {
      setError(String(e));
      setRunning(false);
    }
  };

  const finishRun = (analysisId: string) => {
    setRunning(false);
    setAnalysisId(analysisId);
    navigate("/overview");
  };

  const placeCount = graph?.places.length ?? 0;
  const selectedPlaces = new Set(zoneDrafts.flatMap((z) => z.places));
  const knownPlaces = new Set(graph?.places ?? []);
  const assignedCount = [...selectedPlaces].filter(place => knownPlaces.has(place)).length;
  const unknownPlaceCount = selectedPlaces.size - assignedCount;

  // One canonical color assignment (sorted zone names -> fixed slots), matching
  // state.zoneColor so a zone keeps the same color here and in every analysis view.
  const sortedNames = useMemo(
    () =>
      zoneDrafts
        .map((z, i) => z.name.trim() || `Zone ${i + 1}`)
        .slice()
        .sort(),
    [zoneDrafts],
  );
  const slotOf = (name: string) => (sortedNames.indexOf(name) % 8) + 1;

  return (
    <>
      <h1>Data, Model &amp; Zones</h1>
      <p className="help">
        Load an event log and a Petri net (or let one be discovered), group places into zones,
        then run the analysis. Zones are disjoint, connected groups of Petri-net places.
      </p>

      <div className="panel">
        <h2>1 · Data</h2>
        <h3>Upload your event log and Petri net</h3>
        <form onSubmit={onUpload} className="row" style={{ marginTop: 12 }}>
          <label className="help">
            Event log (.csv / .xes) <input type="file" name="log" accept=".csv,.xes" />
          </label>
          <label className="help">
            Petri net (.pnml, optional) <input type="file" name="pnml" accept=".pnml" onChange={(e) => setUploadHasModel(Boolean(e.target.files?.length))} />
          </label>
          {!uploadHasModel && <label className="help">
            Discovery noise threshold
            <select aria-label="Upload discovery noise threshold" value={noiseThreshold} onChange={(e) => setNoiseThreshold(Number(e.target.value))}>
              <option value={0}>0 · Keep all observed behavior</option>
              <option value={0.1}>0.1 · Filter infrequent behavior</option>
              <option value={0.2}>0.2 · More filtering</option>
              <option value={0.3}>0.3 · Stronger filtering</option>
            </select>
          </label>}
          <button className="primary" type="submit" disabled={busy !== null || running}>
            Upload
          </button>
        </form>

        <details data-testid="example-scenarios" style={{ marginTop: 14 }}>
            <summary>Example scenarios</summary>
            <div className="panel" style={{ marginTop: 12 }}>
              <h3>Online order fulfillment</h3>
              <p className="help">35 days, five zones, and four overlapping injected challenges:
                a payment-risk drift, an arrival surge, a fulfillment capacity bottleneck
                with real backlog, and a quality/rework drift. One click, no upload.</p>
              <button onClick={loadDemo} disabled={busy !== null}>Load demo dataset</button>
            </div>
            <p className="help">Without a PNML file a model is discovered from the log automatically.</p>
            <p className="help" style={{ marginBottom: 10 }}>
              Focused scenarios below isolate individual flow patterns. Zones and time windows
              come preconfigured; load a scenario, validate its zones, and run the analysis.
            </p>
            <div
              className="grid"
              style={{ gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))" }}
            >
              {examples.map((ex) => (
                <div
                  key={ex.dataset_id}
                  style={{
                    border: `1px solid ${datasetId === ex.dataset_id ? "var(--accent)" : "var(--grid)"}`,
                    borderRadius: 10,
                    padding: "12px 14px",
                    display: "flex",
                    flexDirection: "column",
                    gap: 8,
                  }}
                >
                  <strong>{ex.title}</strong>
                  <span className="help" style={{ flex: 1 }}>
                    {ex.description}
                  </span>
                  <ul className="help" style={{ margin: 0, paddingLeft: 18 }}>
                    {ex.highlights.map((h) => (
                      <li key={h}>{h}</li>
                    ))}
                  </ul>
                  <div>
                    <button
                      onClick={() => loadExample(ex)}
                      disabled={busy !== null}
                      className={datasetId === ex.dataset_id ? "primary" : ""}
                    >
                      {datasetId === ex.dataset_id ? "Loaded" : "Load scenario"}
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </details>


        {busy && <div className="notice muted">{busy}</div>}
        {error && <div className="notice error">{error}</div>}
        {datasetId && graph && (
          <div className="notice">
            Loaded <strong>{datasetName || datasetId}</strong>: {placeCount} places,{" "}
            {graph.transitions.length} transitions ({graph.model_source.replaceAll("_", " ")}).
            {graph.case_count !== undefined && <> {graph.case_count.toLocaleString()} cases, {graph.event_count?.toLocaleString()} events.</>}
            {graph.model_notice && <details><summary>Model import details</summary><p className="help">{graph.model_notice}</p></details>}
          </div>
        )}
      </div>

      {graph?.model_source === "discovered_from_log" && <div className="panel" aria-label="Model discovery">
        <h2>Model discovery</h2>
        <p className="help">Inductive Miner discovers the model. Higher noise thresholds allow infrequent behavior to be filtered during discovery; the full event log is still used for analysis.</p>
        <div className="row">
          <label>Noise threshold
            <select aria-label="Model discovery noise threshold" value={noiseThreshold} onChange={(e) => { setNoiseThreshold(Number(e.target.value)); setConfirmDiscovery(false); }} disabled={busy !== null || running}>
              <option value={0}>0 · Keep all observed behavior</option>
              <option value={0.1}>0.1 · Filter infrequent behavior</option>
              <option value={0.2}>0.2 · More filtering</option>
              <option value={0.3}>0.3 · Stronger filtering</option>
            </select>
          </label>
          <button disabled={busy !== null || running || noiseThreshold === (graph.discovery_noise_threshold ?? 0)} onClick={() => {
            if (zoneDrafts.some((zone) => zone.places.length > 0)) setConfirmDiscovery(true);
            else void rediscover();
          }}>Rediscover model</button>
          <span className="help">Current model: {graph.places.length} places, {graph.transitions.length} transitions; noise threshold {graph.discovery_noise_threshold ?? 0}.</span>
        </div>
        {confirmDiscovery && <div className="notice" role="alert">
          Rediscovering resets the zone selection in this editor. Previous analysis results remain available with their original model.
          <div className="row"><button onClick={() => void rediscover()} disabled={busy !== null || running}>Rediscover and reset zones</button><button onClick={() => setConfirmDiscovery(false)}>Keep current model</button></div>
        </div>}
      </div>}

      {graph && (
        <div className="panel">
          <h2>2 · Zones</h2>
          <p className="help">
            A place belongs to at most one zone;
            unassigned places are fine. Each zone must be connected in the place-adjacency graph.
          </p>
          <div className="notice">
            <strong>Draw zones on the net:</strong> select a zone, then click unassigned
            places to add them to it. Click a selected-zone place to remove it; click another zone's place to select that zone.
            Scroll to zoom, drag to pan.
          </div>
          <p className="zone-snapshot-summary" role="status">{zoneDrafts.length} {zoneDrafts.length === 1 ? 'zone' : 'zones'} · {assignedCount} of {placeCount} places assigned · {placeCount - assignedCount} unassigned{unknownPlaceCount > 0 ? ` · ${unknownPlaceCount} unknown place IDs` : ""}</p>
          <div className="zone-snapshot" role="group" aria-label="Zone snapshot">
            {zoneDrafts.map((z, i) => <button key={z.draftKey} className="zone-snapshot-card" aria-pressed={activeZone === i}
              aria-label={`Edit ${z.name.trim() || `Zone ${i + 1}`}, ${z.places.length} places`} onClick={() => setActiveZone(i)}
              style={{ borderLeftColor: `var(--zone-${slotOf(z.name.trim() || `Zone ${i + 1}`)})` }}>
              <strong>{z.name.trim() || `Zone ${i + 1}`}</strong><span>{z.places.length} places{activeZone === i ? " · Editing" : ""}</span>
            </button>)}
          </div>
          <div className="zone-toolbar row">
            <label>Editing zone
              <select aria-label="Active zone" value={zoneDrafts.length ? activeZone : ""} onChange={(e) => setActiveZone(Number(e.target.value))} disabled={!zoneDrafts.length}>
                {!zoneDrafts.length && <option value="">No zones yet</option>}
                {zoneDrafts.map((z, i) => <option key={z.draftKey} value={i}>{z.name.trim() || `Zone ${i + 1}`} ({z.places.length} places)</option>)}
              </select>
            </label>
            <button onClick={addZone} disabled={busy !== null || running}>+ Add zone</button>
            {!zoneDrafts.length && <span className="help">Add a zone to start selecting places</span>}
          </div>
          <div className="zone-workbench">
          <div className="zone-model">
          <PetriNetView
            graph={graph}
            zoneOf={Object.fromEntries(
              zoneDrafts.flatMap((z, i) =>
                z.places.map((p) => [p, z.name.trim() || `Zone ${i + 1}`]),
              ),
            )}
            zoneColorOf={(zone) => `var(--zone-${slotOf(zone)})`}
            onPlaceClick={(place) => {
              if (busy || running) return;
              const owner = zoneDrafts.findIndex((z) => z.places.includes(place));
              if (owner >= 0 && owner !== activeZone) { setActiveZone(owner); return; }
              const assignedSomewhere = owner === activeZone;
              setZoneDrafts((prev) =>
                prev.map((z, i) => {
                  if (assignedSomewhere) {
                    // Only toggle places in the active zone; other zones are selected first.
                    return i === activeZone ? { ...z, places: z.places.filter((p) => p !== place) } : z;
                  }
                  // click on an unassigned place: add to the selected zone
                  return i === activeZone ? { ...z, places: [...z.places, place] } : z;
                }),
              );
            }}
            selectedZone={zoneDrafts[activeZone]?.name.trim() || `Zone ${activeZone + 1}`}
            height={440}
          />
          </div>
          <aside className="zone-controls" aria-label="Selected zone editor">
            {!zoneDrafts.length && <p className="help">Add a zone, then select places on the model.</p>}
          {zoneDrafts.map((z, i) => (
            <div key={`${datasetId}:${z.draftKey}`} hidden={activeZone !== i}>
            <ZoneEditor
              key={`${datasetId}:${z.draftKey}`}
              zone={z}
              allPlaces={graph.places}
              takenElsewhere={new Set(
                zoneDrafts.filter((_, j) => j !== i).flatMap((zz) => zz.places),
              )}
              slot={i}
              color={`var(--zone-${slotOf(z.name.trim() || `Zone ${i + 1}`)})`}
              onChange={(nz) =>
                setZoneDrafts((prev) => prev.map((p, j) => (j === i ? nz : p)))
              }
              suggestions={datasetId && graph.activity_labels.length > 0 ? <ZonePlaceSuggestions
                datasetId={datasetId}
                zoneName={z.name.trim() || `Zone ${i + 1}`}
                activities={graph.activity_labels}
                takenElsewhere={new Set(zoneDrafts.filter((other) => other.draftKey !== z.draftKey).flatMap((other) => other.places))}
                onApply={(places) => setZoneDrafts((previous) => {
                  const taken = new Set(previous.filter((other) => other.draftKey !== z.draftKey).flatMap((other) => other.places));
                  return previous.map((other) => other.draftKey === z.draftKey
                    ? { ...other, places: [...new Set([...other.places, ...places.filter((p) => !taken.has(p))])] }
                    : other);
                })}
              /> : null}
              onRemove={() => {
                setZoneDrafts((prev) => prev.filter((_, j) => j !== i));
                setActiveZone((current) => current > i ? current - 1 : current === i ? Math.max(0, i - 1) : current);
              }}
            />
            </div>
          ))}

          </aside>
          </div>


          <div className="row" style={{ marginTop: 12 }}>
            <label className="help">
              <input
                type="checkbox"
                checked={showTree}
                disabled={graph.process_tree_available === false}
                onChange={(e) => setShowTree(e.target.checked)}
              />{" "}
              Process-tree helper view
            </label>
            <label className="help">
              <input
                type="checkbox"
                checked={showBpmn}
                disabled={graph.bpmn_available === false}
                onChange={(e) => setShowBpmn(e.target.checked)}
              />{" "}
              BPMN view
            </label>
            <span className="help">
              Helper diagrams for inspection. The Petri net remains the reference for zones and analysis.
            </span>
          </div>
          {graph.process_tree_available === false && <p className="help" data-testid="process-tree-explanation">
            {graph.process_tree_reason || "No process tree: this model cannot be represented by the converter's block-structured constructs. Use the Petri net for zone definition and analysis."}
          </p>}
          {graph.bpmn_available === false && <p className="help" data-testid="bpmn-explanation">
            {graph.bpmn_reason || "BPMN cannot be generated for this model. Use the Petri net for inspection."}
          </p>}
          {showTree && datasetId && <div style={{ marginTop: 8 }}><ProcessTreeView key={datasetId} datasetId={datasetId} /></div>}
          {showBpmn && datasetId && <div style={{ marginTop: 8 }}><BpmnView key={datasetId} datasetId={datasetId} /></div>}
          <div className="row" style={{ marginTop: 10 }}>
            <button onClick={validate} disabled={busy !== null || running}>Validate zones</button>
          </div>
          <div role="status" aria-live="polite" style={{ marginTop: 8 }}>
            {!validation ? "Zones not validated. Validate the current configuration before running." :
              validation.valid ? "Zone system is valid." : "Zone system is invalid. Correct the errors and validate again."}
          </div>
          {validation && (
            <div style={{ marginTop: 8 }}>
              {!validation.valid && (
                validation.errors.map((e, i) => (
                  <div key={i} className="notice error">
                    {e}
                  </div>
                ))
              )}
              {validation.warnings.map((w, i) => (
                <div key={i} className="notice muted">
                  {w}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {graph && (
        <div className="panel">
          <h2>3 · Run analysis</h2>
          <div className="row">
            <label>
              Time window{" "}
              <select value={timeframe} onChange={(e) => setTimeframe(e.target.value)}>
                <option value="h">Hourly</option>
                <option value="D">Daily</option>
                <option value="7D">Weekly</option>
                <option value="30D">Monthly</option>
              </select>
            </label>
            <button className="primary" onClick={run} disabled={running || busy !== null || !validation?.valid}>
              {running ? "Running…" : "Run analysis"}
            </button>
            <span className="help">
              Replays every case through the model (alignments) and aggregates token flow per zone
              and window. Results for identical inputs are cached.
            </span>
          </div>
          {configurationChanged && <p className="notice muted">Configuration changed. Rerun the analysis to update results; existing results use the previous configuration.</p>}
          {(running || jobEvents.length > 0) && <StageProgress events={jobEvents} />}
        </div>
      )}
    </>
  );
}

function ZoneEditor({
  zone,
  allPlaces,
  takenElsewhere,
  slot,
  color,
  onChange,
  onRemove,
  suggestions,
}: {
  zone: EditorZone;
  allPlaces: string[];
  takenElsewhere: Set<string>;
  slot: number;
  color: string;
  onChange: (z: EditorZone) => void;
  onRemove: () => void;
  suggestions: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div role="group" aria-label={`Zone ${slot + 1} configuration`} style={{ border: "1px solid var(--grid)", borderRadius: 10, padding: "10px 12px", marginTop: 8 }}>
      <div className="row">
        <span className="zone-chip">
          <span className="dot" style={{ background: color }} />
        </span>
        <input
          aria-label={`Zone ${slot + 1} name`}
          value={zone.name}
          onChange={(e) => onChange({ ...zone, name: e.target.value })}
          style={{ fontWeight: 600, width: "100%", minWidth: 0 }}
        />
        <span className="help">{zone.places.length} place(s)</span>
        <button aria-expanded={open} onClick={() => setOpen(!open)}>{open ? "Hide places" : "Edit places"}</button>
        <button onClick={onRemove} title="Remove zone">
          ✕
        </button>
      </div>
      {suggestions}
      {open && (
        <div className="checkgrid zone-place-list" style={{ marginTop: 8 }}>
          {[...new Set([...allPlaces, ...zone.places])].map((p) => {
            const inZone = zone.places.includes(p);
            const taken = !inZone && takenElsewhere.has(p);
            return (
              <label key={p} style={{ opacity: taken ? 0.4 : 1 }}>
                <input
                  type="checkbox"
                  checked={inZone}
                  disabled={taken}
                  onChange={(e) =>
                    onChange({
                      ...zone,
                      places: e.target.checked
                        ? [...zone.places, p]
                        : zone.places.filter((x) => x !== p),
                    })
                  }
                />
                {p}
                {!allPlaces.includes(p) && <span className="help"> (not in model)</span>}
                {taken && <span className="help"> (other zone)</span>}
              </label>
            );
          })}
        </div>
      )}
    </div>
  );
}
