"""Request-based demand: pairing, snapping, dropping far requests, loading client files."""
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from eventsim.citywide_demand import (EdgeSnapper, category_estimate, load_requests, synthetic_requests,
                                      trips_from_requests, REQUEST_COLUMNS)


def grid_patch(n=6):
    segs = {}
    for i in range(n):
        for j in range(n - 1):  # east-west roads, 0.002 deg (~175 m) long
            segs[f"r{i}_{j}"] = {"coords": [[-122.44 + j * .002, 37.76 + i * .002], [-122.438 + j * .002, 37.76 + i * .002]],
                                 "length_m": 175.0, "rank": 1, "name": f"Row {i}"}
    return {"segments": segs, "proj": {"lon0": -122.44, "lat0": 37.76}}


FAM = {"background": {"vph_peak": 600, "profile_jitter": 1.0, "local_share": 0.5}, "date": "2026-10-04",
       "time": {"sim_begin_s": 36000, "depart_end_s": 43200}}


class Requests(unittest.TestCase):
    def setUp(self):
        self.patch = grid_patch()
        self.ids = sorted(self.patch["segments"])
        w = np.ones(len(self.ids)) / len(self.ids)
        cell_of = [(0, 0)] * len(self.ids)
        self.args = (w, cell_of, {(0, 0): list(range(len(self.ids)))}, [1.0] * 24)

    def test_pair_gets_identical_background_requests(self):
        a = synthetic_requests(self.patch, FAM, {"seed": 3, "with_event": True}, self.ids, *self.args)
        b = synthetic_requests(self.patch, FAM, {"seed": 3, "with_event": False}, self.ids, *self.args)
        self.assertGreater(len(a), 100)
        pd.testing.assert_frame_equal(a, b)
        self.assertEqual(list(a.columns), REQUEST_COLUMNS)

    def test_requests_snap_back_to_their_roads_and_far_ones_are_dropped(self):
        req = synthetic_requests(self.patch, FAM, {"seed": 4}, self.ids, *self.args)
        far = req.iloc[:3].copy()
        far["origin_lat"] += 0.05  # ~5.5 km north of every road
        far["request_id"] = ["far0", "far1", "far2"]
        trips, stats = trips_from_requests(pd.concat([req, far]), EdgeSnapper(self.patch, self.ids))
        self.assertEqual(stats["dropped_far_from_road"], 3)
        self.assertLess(stats["snap_distance_m_p95"], 30)
        self.assertTrue(all(t["from"] in self.patch["segments"] for t in trips))
        self.assertEqual(stats["trips"] + stats["dropped_far_from_road"] + stats["dropped_same_origin_destination"],
                         stats["requests"])

    def test_client_request_file_is_filtered_to_the_window(self):
        df = pd.DataFrame({"request_id": ["a", "b"], "depart_utc": ["2026-10-04T17:30:00Z", "2026-10-05T03:00:00Z"],
                           "origin_lon": [-122.44, -122.44], "origin_lat": [37.76, 37.76],
                           "dest_lon": [-122.43, -122.43], "dest_lat": [37.762, 37.762]})
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "req.csv"
            df.to_csv(p, index=False)
            out = load_requests(p, FAM)
        self.assertEqual(list(out.request_id), ["a"])          # 17:30 UTC = 10:30 PDT, inside 10:00-12:00
        self.assertEqual(float(out.depart_local_s.iloc[0]), 10.5 * 3600)
        self.assertEqual(out.kind.iloc[0], "background")

    def test_attendance_estimates_are_category_based(self):
        self.assertEqual(category_estimate("Block Party - Surrey Street", 2)[0], 300)
        self.assertEqual(category_estimate("The Midway Block Parties 2026", 8)[0], 300)
        self.assertEqual(category_estimate("Playmates Preschool Harvest Festival", 6)[0], 500)
        self.assertEqual(category_estimate("Potrero Street Fair", 30)[0], 15_000)


if __name__ == "__main__":
    unittest.main()
