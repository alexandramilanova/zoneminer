export interface ReplayInterval {
  case_id: string;
  place: string;
  zone: string | null;
  produced: number;
  consumed: number | null;
}

export function upperBound(values: number[], time: number): number {
  let lo = 0, hi = values.length;
  while (lo < hi) {
    const mid = (lo + hi) >>> 1;
    if (values[mid] <= time) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

export function indexReplayPlaces(intervals: ReplayInterval[]) {
  const places = new Map<string, { produced: number[]; consumed: number[]; intervals: ReplayInterval[] }>();
  for (const interval of intervals) {
    let place = places.get(interval.place);
    if (!place) {
      place = { produced: [], consumed: [], intervals: [] };
      places.set(interval.place, place);
    }
    place.produced.push(interval.produced);
    if (interval.consumed !== null) place.consumed.push(interval.consumed);
    place.intervals.push(interval);
  }
  for (const place of places.values()) {
    place.produced.sort((a, b) => a - b);
    place.consumed.sort((a, b) => a - b);
    place.intervals.sort((a, b) => a.produced - b.produced);
  }
  return places;
}

export function indexedTokenCounts(places: ReturnType<typeof indexReplayPlaces>, time: number) {
  const counts: Record<string, number> = {};
  for (const [name, place] of places) {
    const count = upperBound(place.produced, time) - upperBound(place.consumed, time);
    if (count > 0) counts[name] = count;
  }
  return counts;
}

export function indexedCasesAtPlace(places: ReturnType<typeof indexReplayPlaces>, name: string | null, time: number) {
  const place = name === null ? undefined : places.get(name);
  if (!place) return [];
  const ids = new Set<string>();
  const end = upperBound(place.produced, time);
  for (let i = 0; i < end; i++) {
    const interval = place.intervals[i];
    if (interval.consumed === null || interval.consumed > time) ids.add(interval.case_id);
  }
  return [...ids].sort((a, b) => Number(a) - Number(b) || a.localeCompare(b));
}
