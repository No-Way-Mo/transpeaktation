import tempfile
import unittest
from pathlib import Path

from worker.network import Network, maxspeed_mph, read_graphml, road_segment_doc

from .worker_graph import A, B, C, D, EAST, NORTH, WEST, write_graph


class NetworkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.graphml = write_graph(Path(self.tmp.name))
        self.net = Network(read_graphml(self.graphml))

    def tearDown(self):
        self.tmp.cleanup()

    def test_graphml_edges_and_attributes(self):
        self.assertEqual(set(self.net.edges), {EAST, WEST, NORTH})
        e = self.net.edges[EAST]
        self.assertEqual((e.name, e.highway, e.length_m, e.oneway), ("Test St", "residential", 88.0, False))
        self.assertEqual(e.maxspeed_mph, 25.0)  # lowest of a list attribute
        self.assertEqual(len(self.net.edges[NORTH].coords), 3)  # WKT geometry kept

    def test_maxspeed_units(self):
        self.assertEqual(maxspeed_mph("35 mph"), 35.0)
        self.assertEqual(maxspeed_mph("40"), 24.9)  # bare number = km/h in OSM
        self.assertIsNone(maxspeed_mph(None))

    def test_snap_piece_picks_direction(self):
        self.assertEqual(self.net.snap_piece(A, B), EAST)
        self.assertEqual(self.net.snap_piece(B, A), WEST)
        self.assertEqual(self.net.snap_piece(C, D), NORTH)
        self.assertIsNone(self.net.snap_piece(D, C))  # against a one-way: no edge runs that way
        self.assertIsNone(self.net.snap_piece((-122.41, 37.79), (-122.409, 37.79)))  # nowhere near

    def test_snap_line_merges_consecutive_pieces(self):
        segs = self.net.snap_line([A, (-122.3995, 37.78), B])
        self.assertEqual([s for s, _ in segs], [EAST])
        self.assertAlmostEqual(segs[0][1], 88.0, delta=1.0)

    def test_prune_detours(self):
        from worker.network import Edge
        # a path 1->2->3 with a stray 2->9 cross street matched in the middle
        for sid, u, v in (("1-2-0", "1", "2"), ("2-3-0", "2", "3"), ("2-9-0", "2", "9"), ("3-2-0", "3", "2")):
            self.net.edges.setdefault(sid, Edge(sid, u, v, "0", [A, B], 10.0))
        self.assertEqual(self.net.prune_detours(["1-2-0", "2-9-0", "2-9-0", "2-3-0"]), ["1-2-0", "2-3-0"])
        self.assertEqual(self.net.prune_detours(["1-2-0", "3-2-0", "2-3-0"]), ["1-2-0", "2-3-0"])  # wrong direction
        self.assertEqual(self.net.prune_detours(["1-2-0", "2-3-0"]), ["1-2-0", "2-3-0"])
        self.assertEqual(self.net.prune_detours(["2-9-0", "1-2-0"]), ["2-9-0", "1-2-0"])  # ends are left alone

    def test_cnn_link_and_speed_limit(self):
        streets = [{"cnn": "1000", "line": {"type": "MultiLineString", "coordinates": [[list(A), list(B)]]}},
                   {"cnn": "2000", "line": {"type": "LineString", "coordinates": [list(C), list(D)]}}]
        limits = [{"cnn": "1000", "speedlimit": "20"}, {"cnn": "2000", "speedlimit": "99"}]
        self.assertEqual(self.net.link_cnn(streets, limits), 3)
        self.assertEqual((self.net.edges[EAST].cnn, self.net.edges[WEST].cnn), ("1000", "1000"))
        self.assertEqual(self.net.edges[EAST].speed_limit_mph, 20)
        self.assertIsNone(self.net.edges[NORTH].speed_limit_mph)  # 99 = state freeway, not a limit

    def test_free_flow_fallback_order(self):
        e, n = self.net.edges[EAST], self.net.edges[NORTH]
        self.assertEqual(e.free_flow_mph, 25.0)      # OSM maxspeed
        e.speed_limit_mph = 20
        self.assertEqual(e.free_flow_mph, 20)        # DataSF posted limit wins
        self.assertEqual(n.free_flow_mph, 25.0)      # unposted default

    def test_road_segment_doc(self):
        doc = road_segment_doc(self.net.edges[NORTH])
        self.assertEqual(doc["segment_id"], NORTH)
        self.assertEqual(doc["geometry"]["type"], "LineString")
        self.assertEqual(doc["free_flow_speed_mph"], 25.0)


if __name__ == "__main__":
    unittest.main()
