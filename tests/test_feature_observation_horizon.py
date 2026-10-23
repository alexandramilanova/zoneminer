"""Independent horizon examples and an event-sweep oracle for token balances.

Fixtures describe token intervals directly; no replay engine, recorded
baseline, or case-stay builder supplies the expected token metrics.
"""

import unittest

import pandas as pd

from process_model.features import build_zone_token_features_from_places


def intervals(rows):
    frame = pd.DataFrame(rows, columns=["case_id", "place", "produced_ts", "consumed_ts"])
    for column in ("produced_ts", "consumed_ts"):
        frame[column] = pd.to_datetime(
            [pd.Timestamp(value) if value is not None else pd.NaT for value in frame[column]]
        )
    return frame


class ObservationHorizonTests(unittest.TestCase):
    def assert_token_consistency(self, source, zones, features):
        """Integrate a chronological +/-1 event ledger, independently of bins.

        Events at a window's right boundary are deliberately left for the
        following bin. The ledger verifies counts, conservation, occupancy
        integrals, final open balance, and coverage of every assigned event.
        """
        for zone, places in zones.items():
            tokens = source[source["place"].isin(places)]
            rows = features[features["zone"] == zone].sort_values("window_start")
            self.assertFalse(rows.empty)
            events = []
            for token in tokens.itertuples(index=False):
                events.append((token.produced_ts, 1))
                if pd.notna(token.consumed_ts):
                    events.append((token.consumed_ts, -1))
            events.sort(key=lambda event: event[0])
            position = 0
            balance = 0
            previous_end = rows.iloc[0]["window_start"]
            for row in rows.itertuples(index=False):
                self.assertEqual(row.window_start, previous_end)
                cursor = row.window_start
                token_seconds = 0.0
                entered = exited = 0
                previous_balance = balance
                while position < len(events) and events[position][0] < row.window_end:
                    timestamp, delta = events[position]
                    self.assertGreaterEqual(timestamp, row.window_start)
                    token_seconds += balance * (timestamp - cursor).total_seconds()
                    balance += delta
                    entered += int(delta == 1)
                    exited += int(delta == -1)
                    cursor = timestamp
                    position += 1
                token_seconds += balance * (row.window_end - cursor).total_seconds()
                self.assertEqual(row.token_enter, entered)
                self.assertEqual(row.token_exit, exited)
                self.assertEqual(row.token_netflow, entered - exited)
                self.assertEqual(row.token_present_end, balance)
                self.assertEqual(previous_balance + entered - exited, balance)
                self.assertAlmostEqual(
                    row.token_avg_present_window,
                    token_seconds / (row.window_end - row.window_start).total_seconds(),
                )
                previous_end = row.window_end
            self.assertEqual(position, len(events), "an assigned event was omitted from the grid")
            self.assertEqual(int(rows["token_enter"].sum()), len(tokens))
            self.assertEqual(int(rows["token_exit"].sum()), int(tokens["consumed_ts"].notna().sum()))
            self.assertEqual(balance, int(tokens["consumed_ts"].isna().sum()))

    def test_later_open_arrival_after_last_consumption(self):
        source = intervals([
            ("completed", "p", "2024-01-01", "2024-01-02"),
            ("open", "p", "2024-01-10", None),
        ])
        zones = {"Z": ["p"]}
        result = build_zone_token_features_from_places(source, zones)
        self.assertEqual(result["window_start"].tolist(), list(pd.date_range("2024-01-01", "2024-01-10")))
        self.assertEqual(result["token_present_end"].tolist(), [1] + [0] * 8 + [1])
        self.assertEqual(result.iloc[-1]["token_avg_age_open"], 86400.0)
        self.assertEqual(result.iloc[-1]["case_present_end"], 1)
        self.assert_token_consistency(source, zones, result)

    def test_completely_open_intervals(self):
        source = intervals([
            ("first", "p", "2024-01-01 12:00", None),
            ("last", "p", "2024-01-03 18:00", None),
        ])
        zones = {"Z": ["p"]}
        result = build_zone_token_features_from_places(source, zones)
        self.assertEqual(result["token_enter"].tolist(), [1, 0, 1])
        self.assertEqual(result["token_exit"].tolist(), [0, 0, 0])
        self.assertEqual(result["token_present_end"].tolist(), [1, 1, 2])
        self.assertEqual(result["token_avg_present_window"].tolist(), [0.5, 1.0, 1.25])
        self.assert_token_consistency(source, zones, result)

    def test_inactive_zone_retains_zero_rows_until_global_end(self):
        source = intervals([
            ("early", "a", "2024-01-01 06:00", "2024-01-01 12:00"),
            ("late", "b", "2024-01-03 06:00", "2024-01-03 12:00"),
        ])
        zones = {"A": ["a"], "B": ["b"]}
        result = build_zone_token_features_from_places(source, zones)
        a = result[result["zone"] == "A"]
        b = result[result["zone"] == "B"]
        self.assertEqual(a["window_start"].tolist(), list(pd.date_range("2024-01-01", "2024-01-03")))
        self.assertEqual(a["window_start"].tolist(), b["window_start"].tolist())
        self.assertEqual(a["token_enter"].tolist(), [1, 0, 0])
        self.assertEqual(a["token_present_end"].tolist(), [0, 0, 0])
        self.assertEqual(a["token_avg_present_window"].tolist(), [0.25, 0.0, 0.0])
        self.assert_token_consistency(source, zones, result)

    def test_unassigned_intervals_still_define_global_horizon(self):
        for final_exit in (None, "2024-01-05 18:00"):
            with self.subTest(final_exit=final_exit):
                source = intervals([
                    ("before", "unassigned", "2024-01-01 06:00", "2024-01-01 12:00"),
                    ("selected", "p", "2024-01-02 12:00", None),
                    ("after", "unassigned", "2024-01-04 06:00", final_exit),
                ])
                zones = {"Z": ["p"]}
                result = build_zone_token_features_from_places(source, zones)
                last_day = "2024-01-05" if final_exit else "2024-01-04"
                self.assertEqual(result["window_start"].tolist(), list(pd.date_range("2024-01-01", last_day)))
                self.assertEqual(result.iloc[-1]["token_present_end"], 1)
                self.assertEqual(result.iloc[-1]["case_present_end"], 1)
                self.assertEqual(
                    result.iloc[-1]["token_avg_age_open"],
                    (pd.Timestamp(last_day) + pd.Timedelta(days=1) - pd.Timestamp("2024-01-02 12:00")).total_seconds(),
                )
                self.assert_token_consistency(source, zones, result)

    def test_boundary_events_belong_to_following_window(self):
        source = intervals([
            ("first", "p", "2024-01-01", "2024-01-02"),
            ("second", "p", "2024-01-02", "2024-01-03"),
            ("last", "p", "2024-01-03", None),
        ])
        zones = {"Z": ["p"]}
        result = build_zone_token_features_from_places(source, zones)
        self.assertEqual(result["window_start"].tolist(), list(pd.date_range("2024-01-01", "2024-01-03")))
        self.assertEqual(result["token_enter"].tolist(), [1, 1, 1])
        self.assertEqual(result["token_exit"].tolist(), [0, 1, 1])
        self.assertEqual(result["token_present_end"].tolist(), [1, 1, 1])
        self.assertEqual(result["token_avg_present_window"].tolist(), [1.0, 1.0, 1.0])
        self.assert_token_consistency(source, zones, result)

    def test_known_long_consumption_is_not_capped(self):
        source = intervals([("long", "p", "2024-01-01", "2024-02-15")])
        zones = {"Z": ["p"]}
        for timeframe in ("h", "D", "7D", "30D"):
            with self.subTest(timeframe=timeframe):
                result = build_zone_token_features_from_places(source, zones, timeframe=timeframe)
                self.assertGreater(result.iloc[-1]["window_end"], pd.Timestamp("2024-02-15"))
                self.assertEqual(result.iloc[-1]["token_present_end"], 0)
                self.assert_token_consistency(source, zones, result)

    def test_single_zero_duration_interval_on_boundary(self):
        source = intervals([("instant", "p", "2024-01-01", "2024-01-01")])
        zones = {"Z": ["p"]}
        result = build_zone_token_features_from_places(source, zones)
        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["token_enter"], 1)
        self.assertEqual(result.iloc[0]["token_exit"], 1)
        self.assertEqual(result.iloc[0]["token_avg_present_window"], 0.0)
        self.assert_token_consistency(source, zones, result)

    def test_parallel_intervals_and_open_tail_match_event_ledger(self):
        source = intervals([
            ("parallel", "p", "2024-01-01 06:00", "2024-01-02 12:00"),
            ("parallel", "q", "2024-01-01 18:00", "2024-01-03 00:00"),
            ("instant", "p", "2024-01-02 12:00", "2024-01-02 12:00"),
            ("open", "p", "2024-01-05 06:00", None),
        ])
        zones = {"Z": ["p", "q"]}
        for timezone in (None, "UTC"):
            with self.subTest(timezone=timezone):
                frame = source.copy()
                if timezone:
                    for column in ("produced_ts", "consumed_ts"):
                        frame[column] = frame[column].dt.tz_localize(timezone)
                result = build_zone_token_features_from_places(frame, zones)
                self.assertEqual(result["token_present_end"].tolist(), [2, 1, 0, 0, 1])
                self.assertEqual(result.iloc[0]["case_present_end"], 1)
                self.assert_token_consistency(frame, zones, result)


if __name__ == "__main__":
    unittest.main()
