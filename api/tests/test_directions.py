"""Turn-by-turn for the load balancer's own route (app/directions.py), on a small metre grid."""
import unittest

from app import directions

LAT0, LON0 = 37.77, -122.42
M_LAT, M_LON = 1 / 110_540, 1 / 88_000          # degrees per metre, roughly, around SF


def route(points_m: list[tuple[float, float]]):
    """Metre points (x east, y north) -> (coords [lat, lon], xy)."""
    return [[LAT0 + y * M_LAT, LON0 + x * M_LON] for x, y in points_m], list(points_m)


class Build(unittest.TestCase):
    def test_turns_names_and_distances(self):
        # east 300 m on A St (two segments), left: north 200 m on B St, right: east 100 m on C St
        pts = [(0, 0), (150, 0), (300, 0), (300, 100), (300, 200), (400, 200)]
        coords, xy = route(pts)
        ids = ["1-2-0", "2-3-0", "3-4-0", "4-5-0", "5-6-0"]
        joints = [(150, 0), (300, 0), (300, 100), (300, 200)]
        names = {"1-2-0": "A St", "2-3-0": "A St", "3-4-0": "B St", "4-5-0": "B St", "5-6-0": "C St"}
        steps = directions.build(coords, xy, joints, ids, names, 600)
        self.assertEqual([(s["maneuver"]["type"], s["maneuver"].get("modifier"), s["name"]) for s in steps],
                         [("depart", "east", "A St"), ("turn", "left", "B St"), ("turn", "right", "C St"),
                          ("arrive", None, "")])
        self.assertEqual([round(s["distance"]) for s in steps], [300, 200, 100, 0])
        self.assertEqual([round(s["duration"]) for s in steps], [300, 200, 100, 0])   # shares of the card's time
        lon, lat = steps[1]["maneuver"]["location"]
        self.assertAlmostEqual(lat, coords[2][0], places=6)
        self.assertAlmostEqual(lon, coords[2][1], places=6)

    def test_new_street_straight_on_and_unnamed_connector_joins_the_street(self):
        pts = [(0, 0), (100, 0), (130, 0), (250, 0)]
        coords, xy = route(pts)
        ids = ["1-2-0", "2-3-0", "3-4-0"]
        steps = directions.build(coords, xy, [(100, 0), (130, 0)], ids, {"1-2-0": "Geary Blvd", "3-4-0": "Post St"}, 60)
        self.assertEqual([(s["maneuver"]["type"], s["name"]) for s in steps],
                         [("depart", "Geary Blvd"), ("new name", "Post St"), ("arrive", "")])
        self.assertEqual(round(steps[0]["distance"]), 130)          # the unnamed piece stays on Geary

    def test_same_street_corner_is_still_a_turn(self):
        pts = [(0, 0), (200, 0), (200, -150)]
        coords, xy = route(pts)
        steps = directions.build(coords, xy, [(200, 0)], ["1-2-0", "2-3-0"], {"1-2-0": "X St", "2-3-0": "X St"}, 60)
        self.assertEqual([(s["maneuver"]["type"], s["maneuver"].get("modifier")) for s in steps],
                         [("depart", "east"), ("turn", "right"), ("arrive", None)])

    def test_pieces_that_dont_line_up_give_no_directions(self):
        coords, xy = route([(0, 0), (200, 0)])
        self.assertEqual(directions.build(coords, xy, [(100, 500)], ["1-2-0", "2-3-0"], {}, 60), [])  # joint off the line
        self.assertEqual(directions.build(coords, xy, [], ["1-2-0", "2-3-0"], {}, 60), [])            # joints missing
        self.assertEqual(directions.build(coords[:1], xy[:1], [], ["1-2-0"], {}, 60), [])

    def test_modifiers(self):
        self.assertEqual([directions.modifier(d) for d in (5, -30, 90, -150, 175)],
                         ["straight", "slight left", "right", "sharp left", "uturn"])


if __name__ == "__main__":
    unittest.main()
