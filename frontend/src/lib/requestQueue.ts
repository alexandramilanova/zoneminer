// Leave capacity for job streams and other tabs sharing the anonymous session.
export function requestQueue(capacity = 3) {
  let active = 0;
  const waiting: (() => void)[] = [];
  return async function queued<T>(work: () => Promise<T>, signal?: AbortSignal): Promise<T> {
    await new Promise<void>((resolve, reject) => {
      const abort = () => {
        const index = waiting.indexOf(start);
        if (index >= 0) waiting.splice(index, 1);
        reject(new DOMException("Aborted", "AbortError"));
      };
      const start = () => {
        signal?.removeEventListener("abort", abort);
        active++;
        resolve();
      };
      if (signal?.aborted) return abort();
      if (active < capacity) start();
      else {
        waiting.push(start);
        signal?.addEventListener("abort", abort, { once: true });
      }
    });
    try {
      signal?.throwIfAborted();
      return await work();
    } finally {
      active--;
      waiting.shift()?.();
    }
  };
}
