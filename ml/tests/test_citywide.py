"""Citywide invariants: spatial candidates, real event dates, paired demand."""
import unittest
from types import SimpleNamespace

import numpy as np

from eventsim.citywide import BoxIndex, EVENTS, city_trips, event_restrictions, normalized_rows


class CitywideData(unittest.TestCase):
    def test_export_keeps_missing_roads_missing_and_uses_utc_mph(self):
        patch = {"segments": {"observed": {"fallback_free_flow_mph": 25},
                               "empty": {"fallback_free_flow_mph": 25}}}
        # Columns follow sorted road IDs: empty, observed.
        data = {"speed": np.array([[np.nan, 10.]]), "sampledSeconds": np.array([[0., 10.]]),
                "left": np.array([[np.nan, 2.]]), "entered": np.array([[np.nan, 2.]]),
                "closed": np.zeros((1, 2))}
        cfg = {"time": {"sim_begin_s": 34200, "analysis_begin_s": 36000, "depart_end_s": 41400}}
        run = {"run_id": "test", "family_id": "pair", "event_key": "folsom"}
        row = normalized_rows(patch, cfg, run, data)
        self.assertEqual(list(row.road_segment_id), ["observed"])
        self.assertEqual(row.iloc[0].time, "2026-09-27T16:30:00+00:00")
        self.assertAlmostEqual(row.iloc[0].speed_mph, 22.369362920544)
        self.assertAlmostEqual(row.iloc[0].congestion_ratio, 1 - 22.369362920544 / 25)
        self.assertEqual(row.iloc[0].throughput_vph, 12.)
        self.assertEqual(row.iloc[0].phase, "warmup")
        self.assertTrue(row.iloc[0].synthetic)

    def test_spatial_candidates_keep_long_crossing_edges(self):
        index = BoxIndex({"crossing": np.array([[-1000., 0.], [1000., 0.]]),
                          "distant": np.array([[5000., 5000.], [5100., 5100.]])})
        self.assertEqual(index.query([-10, -10], [10, 10]), ["crossing"])

    def test_setup_date_is_not_public_event_date(self):
        # Folsom setup starts the prior day; its closure is already active at 09:30 Sunday.
        row = {"objectid": "r", "status": "Permitted", "veh_imp": "all-lanes-closed",
               "segment_ids": ["closed"], "start_utc": "2026-09-26T13:00:00Z",
               "end_utc": "2026-09-28T02:00:00Z", "match_status": "ambiguous",
               "flags": ["direction_undefined_treated_as_both"]}
        catalog = {EVENTS["folsom"]["case_num"]: {"rows": [row, {**row, "status": "Cancelled"}]}}
        matched = event_restrictions(catalog, "folsom", 9.5 * 3600, 12.5 * 3600)
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0]["begin_s"], -18 * 3600)
        self.assertEqual(matched[0]["end_s"], 19 * 3600)
        self.assertEqual(matched[0]["assumptions"], row["flags"])

    def test_event_does_not_change_background_trips(self):
        segments = {str(i): {"coords": [[-122.440 + i * .002, 37.760],
                                       [-122.439 + i * .002, 37.760]]} for i in range(6)}
        ctx = SimpleNamespace(
            fams={"family": {"background_vph": 100, "event_vehicle_trips": 50}},
            scen={"time": {"sim_begin_s": 34200, "depart_end_s": 41400}},
            od_by_event={"castro": [str(i) for i in range(1, 6)]},
            patch={"segments": segments, "proj": {"lon0": -122.44, "lat0": 37.76}},
            catalog={EVENTS["castro"]["case_num"]: {"segment_ids": ["0"]}})
        run = {"family_id": "family", "seed": 41, "event_key": "castro", "with_event": False}
        control = city_trips(ctx, run)
        event = city_trips(ctx, {**run, "with_event": True})
        self.assertGreater(len(control), 0)
        self.assertEqual(control, [t for t in event if t["kind"] == "background"])
        self.assertGreater(len(event), len(control))
        self.assertTrue(all(t["from"] != "0" and t["to"] != "0" for t in event))


if __name__ == "__main__":
    unittest.main()
