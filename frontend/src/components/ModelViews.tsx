/** Optional readable model views: BPMN (bpmn-js) and process tree (SVG).
 * Helper perspectives only — zones stay defined on the Petri net's places. */

import { useEffect, useRef, useState } from "react";
import BpmnNavigatedViewer from "bpmn-js/lib/NavigatedViewer";
import { api } from "../api";

export function BpmnView({ datasetId }: { datasetId: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!ref.current) return;
    setError(null);
    let disposed = false;
    const viewer = new BpmnNavigatedViewer({ container: ref.current });
    api
      .bpmnXml(datasetId)
      .then((xml) => (disposed ? null : viewer.importXML(xml)))
      .then(() => {
        if (!disposed) {
          (viewer.get("canvas") as { zoom: (m: string, c: string) => void }).zoom(
            "fit-viewport",
            "auto",
          );
        }
      })
      .catch((e: unknown) => { if (!disposed) setError(e instanceof Error ? e.message : "BPMN could not be loaded. Try again or use the Petri net."); });
    return () => {
      disposed = true;
      viewer.destroy();
    };
  }, [datasetId]);

  return <>{error && <div className="notice muted">{error}</div>}
    <div ref={ref} className="net-frame" style={{ height: error ? 0 : 320 }} />
    {!error && <p className="help">BPMN is a structural helper diagram; zone membership and replay refer to the Petri net.</p>}</>;
}

export function ProcessTreeView({ datasetId }: { datasetId: string }) {
  const [error, setError] = useState(false);
  if (error)
    return <div className="notice muted">The process-tree helper could not be loaded. Try reopening it; the Petri net remains available for inspection and analysis.</div>;
  return (
    <div className="net-frame" style={{ maxHeight: 340, overflow: "auto", padding: 8 }}>
      <img
        src={api.processTreeSvgUrl(datasetId)}
        alt="Process tree helper view"
        style={{ maxWidth: "100%" }}
        onError={() => setError(true)}
      />
    </div>
  );
}
