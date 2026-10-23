/** Shared styling for bottleneck states (EXTENSIONS A7/B8).
 * Colors are never the sole encoding: legends carry labels and every
 * element using them has the state name in its tooltip. */

import type { BottleneckState } from "../api";

export const STATE_STYLE: Record<BottleneckState, { color: string; label: string }> = {
  flowing: { color: "rgba(25, 158, 112, 0.22)", label: "flowing" },
  queueing: { color: "#c98500", label: "queueing (own backlog builds)" },
  blocked: { color: "#d64545", label: "blocked (downstream congested)" },
  starving: { color: "#7f93ab", label: "starving (upstream holds flow)" },
};
