"""API tests: full flow through the FastAPI backend against the demo dataset.

Uses an isolated temp data dir so tests never touch a developer's var/ state.
The analysis runs with the pm4py backend so results are directly comparable to
the recorded regression baseline (tests/baseline/baseline_summary.json).
"""

import json
import os
import tempfile
import time
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_tmpdir = tempfile.mkdtemp(prefix="zone_api_test_")
os.environ["ZONE_ANALYTICS_DATA_DIR"] = _tmpdir

from fastapi.testclient import TestClient  # noqa: E402

from backend.main import create_app, demo_zone_places  # noqa: E402


def _wait_for_job(client, job_id: str, timeout: float = 300.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "error"):
            return job
        time.sleep(0.5)
    raise TimeoutError("job did not finish in time")


class TestBackendApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(create_app())
        cls.client.__enter__()  # run startup events
        cls.zones = demo_zone_places()

        resp = cls.client.post(
            "/api/datasets/demo/analyses",
            json={"zones": cls.zones, "timeframe": "D", "backend": "pm4py"},
        )
        assert resp.status_code == 200, resp.text
        payload = resp.json()
        cls.analysis_id = payload["analysis_id"]
        if not payload["cached"]:
            job = _wait_for_job(cls.client, payload["job_id"])
            assert job["status"] == "done", job.get("error")

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)

    def test_health_and_demo_endpoints(self):
        self.assertEqual(self.client.get("/api/health").json()["status"], "ok")
        demo = self.client.get("/api/demo").json()
        # the one-click demo is the showcase dataset when bundled, else the small demo
        self.assertIn(demo["dataset_id"], ("showcase", "demo"))
        self.assertEqual(sorted(demo["zones"]), sorted(self.zones))

    def test_model_graph(self):
        graph = self.client.get("/api/datasets/demo/model").json()
        self.assertGreater(len(graph["places"]), 10)
        self.assertGreater(len(graph["transitions"]), 10)
        self.assertGreater(len(graph["arcs"]), 20)
        self.assertTrue(any(t["label"] == "C2_Pick_Items" for t in graph["transitions"]))

    def test_zone_validation_endpoint(self):
        ok = self.client.post(
            "/api/datasets/demo/zones/validate", json={"zones": self.zones}
        ).json()
        self.assertTrue(ok["valid"], ok["errors"])
        bad = self.client.post(
            "/api/datasets/demo/zones/validate",
            json={"zones": {"Broken": ["p_after_A1", "p_after_E4"]}},
        ).json()
        self.assertFalse(bad["valid"])

    def test_invalid_zones_rejected_on_analysis(self):
        resp = self.client.post(
            "/api/datasets/demo/analyses",
            json={"zones": {"Broken": ["p_after_A1", "p_after_E4"]}, "timeframe": "D"},
        )
        self.assertEqual(resp.status_code, 422)

    def test_features_match_baseline_summary(self):
        with open(os.path.join(REPO_ROOT, "tests", "baseline", "baseline_summary.json")) as f:
            summary = json.load(f)
        features = self.client.get(f"/api/analyses/{self.analysis_id}/features").json()
        self.assertEqual(features["row_count"], summary["zone_feature_rows"])
        zones_in_rows = sorted({r["zone"] for r in features["rows"]})
        self.assertEqual(zones_in_rows, summary["zones"])

    def test_rerun_is_cache_hit(self):
        resp = self.client.post(
            "/api/datasets/demo/analyses",
            json={"zones": self.zones, "timeframe": "D", "backend": "pm4py"},
        ).json()
        self.assertTrue(resp["cached"])
        self.assertEqual(resp["analysis_id"], self.analysis_id)

    def test_metric_catalog(self):
        cat = self.client.get(f"/api/analyses/{self.analysis_id}/metrics").json()
        names = {m["name"] for m in cat["metrics"]}
        self.assertIn("token_present_end", names)
        groups = {m["group"] for m in cat["metrics"]}
        self.assertIn("token", groups)
        self.assertIn("case", groups)

    def test_overview_alerts_trends_changepoints_dependencies(self):
        aid = self.analysis_id
        overview = self.client.get(f"/api/analyses/{aid}/overview").json()
        self.assertEqual(len(overview["per_zone_latest"]) >= 1, True)

        alerts = self.client.get(f"/api/analyses/{aid}/alerts").json()
        self.assertIn("per_zone_summary", alerts)

        trends = self.client.get(f"/api/analyses/{aid}/trends").json()
        self.assertGreater(len(trends["rows"]), 0)

        cps = self.client.get(f"/api/analyses/{aid}/changepoints").json()
        self.assertIn("rows", cps)

        deps = self.client.get(f"/api/analyses/{aid}/dependencies").json()
        self.assertIn("association", deps["note"])
        for r in deps["rows"]:
            self.assertIn("significant", r)
            if r.get("q_value") is not None and r.get("p_value") is not None:
                self.assertGreaterEqual(r["q_value"], r["p_value"] - 1e-12)

    def test_token_intervals(self):
        rows = self.client.get(f"/api/analyses/{self.analysis_id}/token-intervals").json()
        self.assertGreater(rows["row_count"], 100)
        zones_seen = {r["zone"] for r in rows["rows"] if r["zone"]}
        self.assertIn("Fulfillment", zones_seen)

    def test_zone_stays(self):
        rows = self.client.get(f"/api/analyses/{self.analysis_id}/zone-stays").json()
        self.assertGreater(rows["row_count"], 50)
        first = rows["rows"][0]
        for col in ("case_id", "zone", "stay_id", "entry_ts", "exit_ts", "is_open", "duration_s"):
            self.assertIn(col, first)
        completed = [r for r in rows["rows"] if not r["is_open"]]
        self.assertTrue(all(r["duration_s"] is not None and r["duration_s"] >= 0 for r in completed))
        # second call served from the persisted frame — identical
        again = self.client.get(f"/api/analyses/{self.analysis_id}/zone-stays").json()
        self.assertEqual(again["row_count"], rows["row_count"])

    def test_queueing_profile(self):
        resp = self.client.get(f"/api/analyses/{self.analysis_id}/queueing").json()
        self.assertIn("association", resp["note"])
        zones = {z["zone"]: z for z in resp["zones"]}
        self.assertIn("Fulfillment", zones)
        for z in resp["zones"]:
            self.assertGreater(z["arrival_rate_per_day"], 0)
            self.assertGreaterEqual(z["wip_time_avg"], 0)
            self.assertEqual(
                len(z["scatter"]["occupancy_at_entry"]), len(z["scatter"]["sojourn_s"])
            )
            if z["littles_ratio"] is not None:
                # sanity band, not exactness: stationary demo flow should not
                # be wildly off Little's law
                self.assertGreater(z["littles_ratio"], 0.3)
                self.assertLess(z["littles_ratio"], 3.0)
            qm = z.get("queue_model")
            if qm is not None:
                self.assertIn(
                    qm["fit"], ("plausible", "regime-shift", "degenerate", "overloaded")
                )
                self.assertGreater(qm["service_time_s"], 0)
                if qm["kingman_wait_s"] is not None:
                    self.assertGreaterEqual(qm["kingman_wait_s"], 0)
                    self.assertLess(qm["utilization"], 1)

    def test_handovers(self):
        resp = self.client.get(f"/api/analyses/{self.analysis_id}/handovers").json()
        self.assertGreater(resp["handover_count"], 0)
        pairs = {(p["src"], p["tgt"]): p for p in resp["pairs"]}
        # the order process hands over from Payment & Risk into Fulfillment
        self.assertIn(("Payment & Risk", "Fulfillment"), pairs)
        for p in resp["pairs"]:
            self.assertNotEqual(p["src"], p["tgt"])
            self.assertGreaterEqual(p["median_delay_s"], 0)

    def test_handovers_periods(self):
        resp = self.client.get(
            f"/api/analyses/{self.analysis_id}/handovers?periods=4"
        ).json()
        self.assertEqual(len(resp["periods"]), 4)
        # every handover lands in exactly one period
        per_period_total = sum(
            p["count"] for period in resp["periods"] for p in period["pairs"]
        )
        self.assertEqual(per_period_total, resp["handover_count"])

    def test_whatif(self):
        resp = self.client.get(
            f"/api/analyses/{self.analysis_id}/whatif",
            params={"zone": "Logistics", "capacity_multiplier": 1.5},
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        j = resp.json()
        self.assertIn("not a guarantee", j["note"])
        self.assertGreaterEqual(j["calibration"]["fitted_capacity"], 1)
        self.assertEqual(
            len(j["curves"]["t"]), len(j["curves"]["measured_occ"])
        )
        if j["calibration"]["calibrated"] and j["whatif_capacity"] > j["calibration"]["fitted_capacity"]:
            # more capacity never makes waits worse
            self.assertLessEqual(j["whatif"]["mean_wait_s"], j["baseline"]["mean_wait_s"] + 1e-6)
        bad = self.client.get(
            f"/api/analyses/{self.analysis_id}/whatif", params={"zone": "Nope"}
        )
        self.assertEqual(bad.status_code, 422)

    def test_trend_confidence_intervals(self):
        resp = self.client.get(f"/api/analyses/{self.analysis_id}/trends/ci").json()
        self.assertGreater(len(resp["rows"]), 0)
        by_key = {}
        for r in resp["rows"]:
            if r["lo_s"] is not None:
                self.assertLessEqual(r["lo_s"], r["mean_s"])
                self.assertLessEqual(r["mean_s"], r["hi_s"])
                self.assertGreaterEqual(r["n"], 2)
            by_key[(r["zone"], r["window_start"][:10])] = r["mean_s"]
        # CI means must agree with the feature table's own column (same buckets)
        feats = self.client.get(
            f"/api/analyses/{self.analysis_id}/features",
            params={"metrics": "case_avg_duration_completed"},
        ).json()["rows"]
        checked = 0
        for f in feats:
            key = (f["zone"], str(f["window_start"])[:10])
            if f["case_avg_duration_completed"] is not None and key in by_key:
                self.assertAlmostEqual(
                    by_key[key], f["case_avg_duration_completed"], places=6
                )
                checked += 1
        self.assertGreater(checked, 10)

    def test_alert_hints(self):
        resp = self.client.get(
            f"/api/analyses/{self.analysis_id}/alerts/hints", params={"zone": "Logistics"}
        ).json()
        self.assertIn("association, not causation", resp["note"])
        hint_zones = [h["zone"] for h in resp["hints"]]
        self.assertIn("Fulfillment", hint_zones)  # immediate upstream feeder
        self.assertNotIn("Logistics", hint_zones)
        bad = self.client.get(
            f"/api/analyses/{self.analysis_id}/alerts/hints", params={"zone": "Nope"}
        )
        self.assertEqual(bad.status_code, 422)

    def test_compare_periods(self):
        cat = self.client.get(f"/api/analyses/{self.analysis_id}/metrics").json()
        ws = cat["windows"]
        half = len(ws) // 2
        resp = self.client.get(
            f"/api/analyses/{self.analysis_id}/compare",
            params={
                "start_a": ws[0],
                "end_a": ws[half - 1],
                "start_b": ws[half],
                "end_b": ws[-1],
            },
        ).json()
        self.assertIn("FDR", resp["note"])
        self.assertGreater(len(resp["rows"]), 0)
        for r in resp["rows"]:
            self.assertGreaterEqual(r["q_value"], r["p_value"] - 1e-12)
            self.assertLessEqual(r["q_value"], 1.0)
        # empty slice is a clean 422, not a 500
        bad = self.client.get(
            f"/api/analyses/{self.analysis_id}/compare",
            params={
                "start_a": "1999-01-01",
                "end_a": "1999-01-02",
                "start_b": ws[0],
                "end_b": ws[-1],
            },
        )
        self.assertEqual(bad.status_code, 422)

    def test_case_estimates(self):
        # mid-log moment: some cases are open, estimates come from history only
        cat = self.client.get(f"/api/analyses/{self.analysis_id}/metrics").json()
        mid = cat["windows"][len(cat["windows"]) // 2]
        resp = self.client.get(
            f"/api/analyses/{self.analysis_id}/case-estimates", params={"at": mid}
        ).json()
        self.assertIn("not a trained model", resp["note"])
        for c in resp["cases"]:
            self.assertGreaterEqual(c["age_s"], 0)
            if c["est_remaining_p50_s"] is not None:
                self.assertGreaterEqual(c["support_n"], 5)
                self.assertGreaterEqual(c["est_remaining_p50_s"], 0)
                self.assertLessEqual(c["est_remaining_p25_s"], c["est_remaining_p75_s"])

    def test_drift_scores(self):
        resp = self.client.get(f"/api/analyses/{self.analysis_id}/drift").json()
        self.assertEqual(resp["half_window"], 5)
        zones_seen = {r["zone"] for r in resp["rows"]}
        self.assertIn("Fulfillment", zones_seen)
        finite = [r["drift_score"] for r in resp["rows"] if r["drift_score"] is not None]
        self.assertTrue(finite and all(s >= 0 for s in finite))

    def test_bottleneck_states(self):
        resp = self.client.get(f"/api/analyses/{self.analysis_id}/bottlenecks").json()
        self.assertIn("not ground truth", resp["note"])
        self.assertGreater(len(resp["windows"]), 0)
        valid = {"flowing", "queueing", "blocked", "starving"}
        for z in resp["zones"]:
            self.assertEqual(len(z["states"]), len(resp["windows"]))
            self.assertTrue(set(z["states"]) <= valid)
        # the handover graph must contain the process's main edge
        edges = {(e["src"], e["tgt"]) for e in resp["edges"]}
        self.assertIn(("Payment & Risk", "Fulfillment"), edges)

    def test_example_scenarios_listed_and_valid(self):
        resp = self.client.get("/api/examples").json()
        ids = {e["dataset_id"] for e in resp["examples"]}
        self.assertLessEqual(
            {"express-lane", "batch-dispatch", "review-rework", "capacity-cliff"}, ids
        )
        for ex in resp["examples"]:
            self.assertTrue(ex["title"] and ex["description"] and ex["highlights"])
            # dataset registered and model loadable
            graph = self.client.get(f"/api/datasets/{ex['dataset_id']}/model")
            self.assertEqual(graph.status_code, 200, ex["dataset_id"])
            # preconfigured zones must validate against the bundled net
            val = self.client.post(
                f"/api/datasets/{ex['dataset_id']}/zones/validate",
                json={"zones": ex["zones"]},
            ).json()
            self.assertTrue(val["valid"], f"{ex['dataset_id']}: {val['errors']}")

    def test_example_review_rework_shows_revisits(self):
        """The scenario built to demo revisits must actually produce them."""
        ex = next(
            e
            for e in self.client.get("/api/examples").json()["examples"]
            if e["dataset_id"] == "review-rework"
        )
        resp = self.client.post(
            f"/api/datasets/review-rework/analyses",
            json={"zones": ex["zones"], "timeframe": ex["timeframe"], "backend": "pm4py"},
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        payload = resp.json()
        if not payload["cached"]:
            job = _wait_for_job(self.client, payload["job_id"])
            self.assertEqual(job["status"], "done", job.get("error"))
        feats = self.client.get(
            f"/api/analyses/{payload['analysis_id']}/features",
            params={"metrics": "case_revisit_enter,zone_deviation_count"},
        ).json()["rows"]
        revisits = sum(
            r["case_revisit_enter"] or 0 for r in feats if r["zone"] == "Review"
        )
        self.assertGreater(revisits, 20, "review-rework must show revisits in Review")
        deviations = sum(r["zone_deviation_count"] or 0 for r in feats)
        self.assertGreater(deviations, 5, "expected zone-attributed deviations")

    def test_prediction_endpoint(self):
        resp = self.client.post(
            f"/api/analyses/{self.analysis_id}/prediction",
            json={
                "target_zone": "Fulfillment",
                "target_metric": "token_present_end",
                "models": ["decision_tree"],
                "search_best_horizon": False,
                "horizon": 1,
            },
        )
        # The legacy request omits the mandatory protocol choices. It must not
        # fall back to an automatic whole-series threshold or repaired features.
        self.assertEqual(resp.status_code, 422, resp.text)
        locations = [error['loc'][-1] for error in resp.json()['detail']]
        for required in ('threshold', 'development_end', 'observed_through', 'protocol_acknowledged', 'feature_pairs'):
            self.assertIn(required, locations)
        options = self.client.get(f"/api/analyses/{self.analysis_id}/prediction/options")
        self.assertEqual(options.status_code, 200, options.text)
        self.assertTrue(options.json()['eligible']) # model profile, not log fitness
        self.assertEqual(options.json()['forecast_profile'],'marking_set_occupancy')
        self.assertEqual({m['name'] for m in options.json()['metrics'] if m['forecast_supported']},
                         {'token_present_end','case_present_end'})



if __name__ == "__main__":
    unittest.main()
