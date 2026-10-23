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

const STORAGE_KEY = "zone-analytics-current";

interface AppState {
  analysisId: string | null;
  analysis: AnalysisMeta | null;
  setAnalysisId: (id: string | null) => void;
  refresh: () => void;
  zoneColor: (zone: string) => string;
  zones: string[];
}

const Ctx = createContext<AppState | null>(null);

const ZONE_SLOTS = 8;

export function AppStateProvider({ children }: { children: ReactNode }) {
  const [analysisId, setAnalysisIdRaw] = useState<string | null>(() => {
    // shareable/demo links: ?analysis=<id> overrides the stored selection
    const fromUrl = new URLSearchParams(window.location.search).get("analysis");
    if (fromUrl) {
      localStorage.setItem(STORAGE_KEY, fromUrl);
      return fromUrl;
    }
    return localStorage.getItem(STORAGE_KEY);
  });
  const [analysis, setAnalysis] = useState<AnalysisMeta | null>(null);

  const setAnalysisId = useCallback((id: string | null) => {
    setAnalysisIdRaw(id);
    if (id) localStorage.setItem(STORAGE_KEY, id);
    else localStorage.removeItem(STORAGE_KEY);
  }, []);

  const refresh = useCallback(() => {
    if (!analysisId) {
      setAnalysis(null);
      return;
    }
    api
      .analysis(analysisId)
      .then(setAnalysis)
      .catch((e: Error) => {
        // Only a definitive 404 means the reference is stale; transient
        // failures (backend restarting, network blip) must not wipe the
        // user's selection.
        if (String(e.message).startsWith("404")) {
          setAnalysis(null);
          setAnalysisId(null);
        }
      });
  }, [analysisId, setAnalysisId]);

  useEffect(refresh, [refresh]);

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
    () => ({ analysisId, analysis, setAnalysisId, refresh, zoneColor, zones }),
    [analysisId, analysis, setAnalysisId, refresh, zoneColor, zones],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAppState(): AppState {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useAppState outside provider");
  return ctx;
}
