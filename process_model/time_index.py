"""Exact time indexes for repeated half-open window queries.

No binning approximation: searchsorted uses [start,end), and active intervals
are those produced strictly before end and not consumed strictly before end.
"""
from itertools import accumulate

import numpy as np
import pandas as pd


class EventTimeIndex:
    def __init__(self, timestamps):
        values = pd.to_datetime(timestamps).to_numpy(dtype='datetime64[ns]').astype(np.int64)
        valid = np.flatnonzero(values != np.iinfo(np.int64).min)
        self.order = valid[np.argsort(values[valid], kind='stable')]
        self.times = values[self.order]
        # Python integers avoid overflow when summing epoch nanoseconds.
        self.sums = list(accumulate(map(int, self.times), initial=0))

    def before(self, time):
        return int(np.searchsorted(self.times, pd.Timestamp(time).value, side='left'))

    def between(self, start, end):
        return np.sort(self.order[self.before(start):self.before(end)])

    def elapsed_ns(self, time):
        count = self.before(time)
        return count * int(pd.Timestamp(time).value) - self.sums[count]


class IntervalTimeIndex:
    def __init__(self, starts, ends):
        self.starts = EventTimeIndex(starts)
        self.ends = EventTimeIndex(ends)
        self.active = set()
        self.produced = self.consumed = 0

    def present_before(self, end):
        produced, consumed = self.starts.before(end), self.ends.before(end)
        self.active.update(map(int, self.starts.order[self.produced:produced]))
        self.active.difference_update(map(int, self.ends.order[self.consumed:consumed]))
        self.produced, self.consumed = produced, consumed
        return sorted(self.active)

    def occupied_seconds(self, start, end):
        def area(time):
            return self.starts.elapsed_ns(time) - self.ends.elapsed_ns(time)
        nanoseconds = area(end) - area(start)
        # Preserve historical Timedelta rounding within its representable range;
        # avoid overflow for large token-count x window-duration products.
        if abs(nanoseconds) <= np.iinfo(np.int64).max:
            return pd.Timedelta(nanoseconds, unit='ns').total_seconds()
        return nanoseconds / 1e9
