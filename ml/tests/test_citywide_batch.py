"""Batch generator invariants: paired background demand, windows/phases, restriction selection, review rules."""
import unittest
from types import SimpleNamespace

import numpy as np

from eventsim import citywide_batch as b
from eventsim.citywide import review_row


def fake_ctx(n=40):
    segs = {str(i): {"coords": [[-122.44 + (i % 8) * .003, 37.76 + (i // 8) * .003],
                                [-122.439 + (i % 8) * .003, 37.76 + (i // 8) * .003]],
                     "rank": 1 + i % 3, "length_m": 90.0} for i in range(n)}
    return SimpleNamespace(patch={"segments": segs, "proj": {"lon0": -122.44, "lat0": 37.76}})


def fam(window="full"):
    rng = np.random.default_rng(1)
    f = b.sample_family(rng, "castro", window, 0, "t")
    a, e = b.window_for(window, (11, 18))
    f["time"] = {"sim_begin_s": a, "analysis_begin_s": a + b.WARMUP_S, "depart_end_s": e - b.DRAIN_S, "sim_end_s": e}
    f["public_hours_s"] = [11 * 3600, 18 * 3600]
    f["event"]["vehicle_trips"] = 200
    return f


class BatchInvariants(unittest.TestCase):
    def test_pair_has_identical_background(self):
        ctx, f = fake_ctx(), fam()
        ids = [str(i) for i in range(1, 40)]
        restr = [{"source": "event_permit", "segment_ids": ["0"]}]
        ev = b.batch_trips(ctx, f, {"run_id": "e", "seed": 5, "with_event": True, "restrictions": restr}, ids)
        ctl = b.batch_trips(ctx, f, {"run_id": "c", "seed": 5, "with_event": False, "restrictions": []}, ids)
        self.assertGreater(len(ctl), 0)
        self.assertEqual(ctl, [t for t in ev if t["kind"] == "background"])
        self.assertTrue(any(t["kind"] != "background" for t in ev))
        self.assertTrue(all(t["from"] != "0" and t["to"] != "0" for t in ev))  # closed edge never an endpoint
        t = f["time"]
        self.assertTrue(all(t["sim_begin_s"] <= x["depart"] < t["depart_end_s"] for x in ev))  # nothing departs in drain

    def test_evening_event_with_late_arrivals(self):
        f = b.sample_family(np.random.default_rng(3), "halloween_cortland", "full", 0, "t")
        a, e = b.window_for("full", (17, 20))
        f["time"] = {"sim_begin_s": a, "analysis_begin_s": a + b.WARMUP_S, "depart_end_s": e - b.DRAIN_S, "sim_end_s": e}
        f["public_hours_s"] = [17 * 3600, 20 * 3600]
        f["event"].update(vehicle_trips=500, arrival_offset_min=120, arrival_sigma_min=90, departure_surge_share=0.4)
        ids = [str(i) for i in range(1, 40)]
        run = {"run_id": "e", "seed": 2, "with_event": True, "restrictions": [{"source": "event_permit", "segment_ids": ["0"]}]}
        trips = b.batch_trips(fake_ctx(), f, run, ids)  # used to raise "high - low < 0"
        self.assertTrue(any(t["kind"] == "event_departure" for t in trips))

    def test_view_carries_batch_families(self):
        bc = SimpleNamespace(base=SimpleNamespace(scen={"time": {}}, fams={"pilot": {}}), fams={"batch_f": {}})
        v = b.BatchContext.view(bc, {"time": {"sim_begin_s": 1}})
        self.assertIn("batch_f", v.fams)
        self.assertEqual(v.scen["time"]["sim_begin_s"], 1)
        self.assertIn("pilot", bc.base.fams)  # shared base untouched

    def test_sampler_v3_limits_load_and_records_sources(self):
        for i in range(40):
            f = b.sample_family(np.random.default_rng(i), "folsom", "arrival", 0, "t", 3, (9000, 12000))
            e = f["event"]
            self.assertLessEqual(e["vehicle_trips"], b.MAX_EVENT_VEHICLES)
            peak_in = e["vehicle_trips"] / (e["arrival_sigma_min"] / 60 * 2.5066)
            self.assertLessEqual(peak_in, b.MAX_PEAK_ARRIVALS_VPH * 1.001)
            peak_out = e["vehicle_trips"] * e["departure_surge_share"] / (e["departure_surge_sigma_min"] / 60 * 2.5066)
            self.assertLessEqual(peak_out, b.MAX_PEAK_DEPARTURES_VPH * 1.001)
            self.assertEqual(e["ridehail_stop"], "off_lane")
            self.assertIn(f["network"]["signal_control"], ("static", "actuated"))
            self.assertIn("folsomstreet.org", f["sourced"]["public_hours"])
        g = b.sample_family(np.random.default_rng(0), "halloween_cortland", "full", 0, "t", 3)
        self.assertIn("public hours (2025 or partial)", g["assumed"])

    def test_off_lane_ridehail_stop_written_as_parking(self):
        import tempfile, xml.etree.ElementTree as ET
        from pathlib import Path
        from eventsim.simulate import write_routes
        f = fam()
        trips = [{"id": "r", "kind": "ridehail_dropoff", "depart": 1.0, "from": "a", "to": "b", "stop": "c",
                  "dwell": 30.0, "off_lane": True},
                 {"id": "o", "kind": "background", "depart": 2.0, "from": "a", "to": "b", "stop": "c", "dwell": 30.0}]
        with tempfile.TemporaryDirectory() as d:
            write_routes(trips, f, Path(d) / "r.xml")
            stops = {t.get("id"): t.find("stop") for t in ET.parse(Path(d) / "r.xml").getroot().iter("trip")}
        self.assertEqual(stops["r"].get("parking"), "true")
        self.assertIsNone(stops["o"].get("parking"))  # pilot/v2 trips unchanged

    def test_closures_on_merged_parallel_edges_move_to_the_kept_edge(self):
        bc = SimpleNamespace(represented={"a-b-1": "a-b-0"})
        run = {"restrictions": [{"source": "event_permit", "segment_ids": ["a-b-1", "x-y-0"]}]}
        out = b.BatchContext.restrictions(bc, run)
        self.assertEqual(out[0]["segment_ids"], ["a-b-0", "x-y-0"])
        self.assertEqual(run["restrictions"][0]["segment_ids"], ["a-b-1", "x-y-0"])  # scenario record untouched
        self.assertEqual(b.run_ids(run), {"a-b-1", "x-y-0"})

    def test_windows_cover_surges_and_recovery(self):
        a, e = b.window_for("departure", (11, 18))
        self.assertLessEqual(a, 16 * 3600)
        self.assertGreaterEqual(e, 21 * 3600)  # 3 h recovery after the declared end
        a, e = b.window_for("arrival", (11, 18))
        self.assertLess(a, 11 * 3600)
        self.assertEqual(a % 600, 0)
        self.assertEqual(e % 600, 0)

    def test_family_records_assumptions_and_group(self):
        f = fam("arrival")
        self.assertEqual(f["family_group"], "castro")
        self.assertIn("attendance", f["assumed"])
        self.assertNotIn("public hours", f["assumed"])       # Castro hours are sourced
        g = b.sample_family(np.random.default_rng(0), "bearrison", "arrival", 1, "t")
        self.assertIn("public hours", g["assumed"])           # assumed for most events

    def test_restrictions_use_only_accepted_rows_on_the_day(self):
        review = {"rows": [
            {"case_num": "1", "decision": "accept", "segment_ids": ["a"], "start_utc": "2026-10-04T16:00:00.000",
             "end_utc": "2026-10-05T01:00:00.000", "objectid": "x", "reason": "r", "match_flags": []},
            {"case_num": "1", "decision": "needs_review", "segment_ids": ["b"], "start_utc": "2026-10-04T16:00:00.000",
             "end_utc": "2026-10-05T01:00:00.000", "objectid": "y", "reason": "r", "match_flags": []}]}
        r = b.restrictions_on(review, "1", "2026-10-04", 8 * 3600, 20 * 3600, "event_permit")
        self.assertEqual([x["id"] for x in r], ["x"])
        self.assertEqual(r[0]["begin_s"], 9 * 3600)  # 16:00 UTC = 09:00 PDT
        self.assertEqual(b.restrictions_on(review, "1", "2026-10-04", 18 * 3600 + 3600 * 6, 24 * 3600, "e"), [])

    def test_review_accepts_undefined_direction_on_all_lane_closures_only(self):
        row = {"objectid": "1", "case_num": "9", "cnn": "c", "street": "X ST", "status": "Permitted",
               "veh_imp": "all-lanes-closed", "direction": "undefined", "start_utc": "s", "end_utc": "e"}
        match = {"status": "ambiguous", "flags": ["direction_undefined_treated_as_both"],
                 "edges": [{"segment_id": "s1", "name_match": True, "osm_name": "X Street", "overlap": 1.0}]}
        self.assertEqual(review_row(row, match, {}, None, None)["decision"], "accept")
        self.assertEqual(review_row({**row, "veh_imp": "some-lanes-closed"}, match, {}, None, None)["decision"],
                         "partial_restriction")
        self.assertEqual(review_row({**row, "status": "Cancelled"}, match, {}, None, None)["decision"], "reject")


if __name__ == "__main__":
    unittest.main()
