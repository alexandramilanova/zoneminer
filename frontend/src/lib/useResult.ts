import { useEffect, useRef, useState } from "react";

// A result is visible only for the request key that produced it. Cleanup
// ignores late replies, including when a selection is cleared or a request fails.
type Remote<T> = { key: string | null } & (
  { status: "idle" | "loading" } | { status: "success"; data: T } | { status: "error"; error: string }
);
export function useResult<T>(key: string | null, load: () => Promise<T>, debounceMs = 0): Remote<T> {
  const loader = useRef(load);
  loader.current = load;
  const [state, setState] = useState<Remote<T>>({ key: null, status: "idle" });
  useEffect(() => {
    if (!key) return;
    let current = true;
    setState({ key, status: "loading" });
    const loadCurrent = () => loader.current().then(
      (data) => { if (current) setState({ key, status: "success", data }); },
      (error) => { if (current) setState({ key, status: "error", error: String(error) }); },
    );
    const timer = debounceMs ? window.setTimeout(loadCurrent, debounceMs) : null;
    if (timer === null) void loadCurrent();
    return () => { current = false; if (timer !== null) window.clearTimeout(timer); };
  }, [key, debounceMs]);
  if (!key) return { key, status: "idle" };
  return state.key === key ? state : { key, status: "loading" };
}

