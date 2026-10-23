import { useEffect, useRef, useState } from "react";

// A result is visible only for the request key that produced it. Cleanup
// ignores late replies, including when a selection is cleared or a request fails.
type Remote<T> = { key: string | null } & (
  { status: "idle" | "loading" } | { status: "success"; data: T } | { status: "error"; error: string }
);
export function useResult<T>(key: string | null, load: () => Promise<T>): Remote<T> {
  const loader = useRef(load);
  loader.current = load;
  const [state, setState] = useState<Remote<T>>({ key: null, status: "idle" });
  useEffect(() => {
    if (!key) return;
    let current = true;
    setState({ key, status: "loading" });
    loader.current().then(
      (data) => { if (current) setState({ key, status: "success", data }); },
      (error) => { if (current) setState({ key, status: "error", error: String(error) }); },
    );
    return () => { current = false; };
  }, [key]);
  if (!key) return { key, status: "idle" };
  return state.key === key ? state : { key, status: "loading" };
}

