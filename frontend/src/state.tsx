/** App-level state: which dataset + analysis the user is working with.
 *
 * Persisted to localStorage so a reload lands back in the same analysis.
 * Zone colors are assigned by fixed slot order from the sorted zone list —
 * the same zone always renders the same color everywhere in the app.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { api, type AnalysisMeta } from "./api";
import { useResult } from "./lib/useResult";

const STORAGE_KEY = "zone-analytics-current";

interface AppState {
  analysisId: string | null;
  analysis: AnalysisMeta | null;
  analysisError: string | null;
  workspaceDirty: boolean;
  setWorkspaceDirty: (dirty: boolean) => void;
  setAnalysisId: (id: string | null) => void;
  zoneColor: (zone: string) => string;
  zones: string[];
}

const Ctx = createContext<AppState | null>(null);

const ZONE_SLOTS = 8;

export function AppStateProvider({ children }: { children: ReactNode }) {
  const [workspaceDirty, setWorkspaceDirty] = useState(false);
  const [analysisId, setAnalysisIdRaw] = useState<string | null>(() => {
    // shareable/demo links: ?analysis=<id> overrides the stored selection
    const fromUrl = new URLSearchParams(window.location.search).get("analysis");
    if (fromUrl) {
      localStorage.setItem(STORAGE_KEY, fromUrl);
      return fromUrl;
    }
    return localStorage.getItem(STORAGE_KEY);
  });

  const setAnalysisId = useCallback((id: string | null) => {
    setAnalysisIdRaw(id);
    if (id) localStorage.setItem(STORAGE_KEY, id);
    else localStorage.removeItem(STORAGE_KEY);
  }, []);

  const result = useResult<AnalysisMeta>(analysisId, () => api.analysis(analysisId!));
  const analysis = result.status === "success" ? result.data : null;
  const error = result.status === "error" ? result.error : null;
  useEffect(() => {
    if (error?.includes("404:")) setAnalysisId(null);
  }, [error, setAnalysisId]);

  const zones = useMemo(
    () => (analysis ? Object.keys(analysis.zone_places).sort() : []),
    [analysis],
  );

  const zoneColor = useCallback(
    (zone: string) => {
      const idx = zones.indexOf(zone);
      const slot = idx >= 0 ? (idx % ZONE_SLOTS) + 1 : 8;
      return `var(--zone-${slot})`;
    },
    [zones],
  );

  const value = useMemo(
    () => ({ analysisId, analysis, analysisError: error, setAnalysisId, zoneColor, zones, workspaceDirty, setWorkspaceDirty }),
    [analysisId, analysis, error, setAnalysisId, zoneColor, zones, workspaceDirty],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAppState(): AppState {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useAppState outside provider");
  return ctx;
}
