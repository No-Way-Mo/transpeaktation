import unittest
from datetime import datetime, timezone

from worker.adapters import NORMALIZERS, UNSUPPORTED
from worker.adapters.common import incident_category, location_tokens
from worker.context import Context
from worker.geo import GeometryError, LineIndex, StreetIndex, normalize_geometry, valid_lonlat
from worker.records import Record, RecordError, make_id, natural_key
from worker.timeutil import chp_ts, datasf_ts, epoch, iso, local_day
from worker.validate import validate
from pull.sources import SOURCES

from tests import worker_fixtures as fx

NOW = datetime(2026, 9, 26, 1, tzinfo=timezone.utc)
UTC = timezone.utc


def ctx(with_streets=True, osm=None):
    idx = None
    if osm is not None:
        idx = LineIndex()
        for k, g in osm.items():
            idx.add(k, g)
    return Context(now=NOW, streets=StreetIndex.from_rows(fx.STREETS) if with_streets else None, osm=idx)


def norm(source, row, c=None):
    return NORMALIZERS[source](row, c or ctx())


class TimeTests(unittest.TestCase):
    def test_datasf_local_vs_utc_columns(self):
        # PDT: local 17:10 == 00:10 UTC next day
        self.assertEqual(datasf_ts("received_datetime", "2026-09-25T17:10:00.000"), datetime(2026, 9, 26, 0, 10, tzinfo=UTC))
        self.assertEqual(datasf_ts("start_utc", "2026-09-26T10:00:00.000"), datetime(2026, 9, 26, 10, tzinfo=UTC))
        self.assertIsNone(datasf_ts("x", ""))
        with self.assertRaises(ValueError):
            datasf_ts("x", "not a time")

    def test_winter_offset(self):
        self.assertEqual(datasf_ts("d", "2026-01-15T12:00:00.000"), datetime(2026, 1, 15, 20, tzinfo=UTC))  # PST

    def test_local_day_bounds(self):
        self.assertEqual(local_day("09/25/2026"), datetime(2026, 9, 25, 7, tzinfo=UTC))
        self.assertEqual(local_day("09/27/2026", end=True), datetime(2026, 9, 28, 7, tzinfo=UTC))

    def test_chp_timestamp(self):
        self.assertEqual(chp_ts("Sep 25 2026  5:59PM"), datetime(2026, 9, 26, 0, 59, tzinfo=UTC))
        self.assertIsNone(chp_ts(""))

    def test_caltrans_epoch(self):
        self.assertEqual(epoch("1790000000"), datetime.fromtimestamp(1790000000, UTC))
        self.assertEqual(epoch(1790000000000), datetime.fromtimestamp(1790000000, UTC))  # ms
        self.assertIsNone(epoch("0"))
        self.assertIsNone(epoch(""))

    def test_iso_serialization(self):
        self.assertEqual(iso(datetime(2026, 9, 26, tzinfo=UTC)), "2026-09-26T00:00:00Z")


class GeometryTests(unittest.TestCase):
    def test_valid_and_invalid_coordinates(self):
        self.assertTrue(valid_lonlat(-122.4, 37.7))
        for bad in [(0, 0), (200, 37), (-122, 95), ("x", 1), (float("nan"), 1), (None, None)]:
            self.assertFalse(valid_lonlat(*bad), bad)

    def test_geojson_normalization(self):
        g = normalize_geometry({"type": "LineString", "coordinates": [[-122.4, 37.7, 5], ["-122.41", "37.71"]]})
        self.assertEqual(g, {"type": "LineString", "coordinates": [[-122.4, 37.7], [-122.41, 37.71]]})
        self.assertEqual(normalize_geometry({"latitude": "37.7", "longitude": "-122.4", "human_address": "{}"}),
                         {"type": "Point", "coordinates": [-122.4, 37.7]})
        self.assertIsNone(normalize_geometry(None))
        self.assertIsNone(normalize_geometry({"latitude": "", "longitude": ""}))

    def test_malformed_geometry_raises(self):
        for bad in [{"type": "Point", "coordinates": [0, 0]}, {"type": "LineString", "coordinates": [[-122, 37]]},
                    {"type": "Polygon", "coordinates": [[[-122, 37], [-122, 38], [-121, 38]]]},
                    {"type": "Circle", "coordinates": [1, 2]}, "POINT(1 2)", {"foo": 1}]:
            with self.assertRaises(GeometryError, msg=bad):
                normalize_geometry(bad)


class IdTests(unittest.TestCase):
    def test_natural_and_composite_keys(self):
        self.assertEqual(natural_key({"objectid": 10}, "objectid"), "10")
        self.assertEqual(natural_key({"signid": "5", "cnn": "100", "sideofstreet": "N"},
                                     ("signid", "cnn", "sideofstreet")), "5|100|N")
        with self.assertRaises(RecordError):
            natural_key({"permit_number": "EX1"}, ("permit_number", "cnn"))

    def test_deterministic_ids(self):
        a = norm("parking_signs", fx.PARKING_SIGNS[0])
        b = norm("parking_signs", dict(fx.PARKING_SIGNS[0]))
        self.assertEqual(a.id, b.id)
        self.assertEqual(a.id, "parking_signs:5|100|N")
        self.assertEqual(make_id("chp_incidents", "X"), "chp_incidents:X")
        self.assertEqual(norm("excavation_permits", fx.EXCAVATION[0]).id, "excavation_permits:EX1|100")

    def test_every_pull_source_has_an_adapter_or_reason(self):
        for name in SOURCES:
            self.assertTrue(name in NORMALIZERS or name in UNSUPPORTED, name)


class RoadTests(unittest.TestCase):
    def test_street_segment(self):
        r = norm("streets", fx.STREETS[0])
        self.assertEqual((r.kind, r.source_id, r.attributes["oneway"], r.attributes["name"]),
                         ("road_segment", "100", "both", "MARKET ST"))
        self.assertEqual(r.attributes["to_node_cnn"], "901")
        self.assertNotIn(":@computed_region_abc", r.source_fields)
        self.assertNotIn("line", r.source_fields)
        self.assertEqual(validate(r), [])

    def test_speed_limit_sentinels_keep_source_meaning(self):
        posted, unposted, freeway = (norm("speed_limits", r).attributes for r in fx.SPEED_LIMITS[:3])
        self.assertEqual((posted["status"], posted["posted_mph"], posted["raw_value"]), ("posted", 25, "25"))
        self.assertEqual((unposted["status"], unposted["posted_mph"], unposted["raw_value"]), ("unposted", None, "0"))
        self.assertEqual((freeway["status"], freeway["posted_mph"], freeway["raw_value"]), ("state_managed", None, "99"))
        for attrs in (posted, unposted, freeway):
            self.assertNotIn("effective_mph", attrs)  # ingestion doesn't invent a speed
        with self.assertRaises(RecordError):
            norm("speed_limits", fx.SPEED_LIMITS[3])
        with self.assertRaises(RecordError):
            norm("speed_limits", {"objectid": "9", "cnn": "1", "speedlimit": ""})

    def test_osm_edge_with_and_without_graphml_geometry(self):
        geom = {"type": "LineString", "coordinates": [[-122.42, 37.77], [-122.419, 37.77]]}
        r = norm("osm_drive_graph", fx.OSM_EDGES[0], ctx(osm={"1-2-0": geom}))
        self.assertEqual((r.source_id, r.geometry, r.location_status), ("1-2-0", geom, "exact"))
        self.assertEqual(r.attributes["maxspeed_mph"], 25)
        r2 = norm("osm_drive_graph", fx.OSM_EDGES[1])
        self.assertEqual((r2.geometry, r2.location_status), (None, "network_ref"))
        self.assertEqual(r2.attributes["maxspeed_mph"], 24.9)  # min(40 km/h, 30 mph)
        self.assertEqual(validate(r2), [])

    def test_turn_restriction(self):
        r = norm("osm_turn_restrictions", fx.TURNS[0])
        self.assertEqual((r.kind, r.attributes["restriction"], len(r.attributes["members"])),
                         ("road_rule", "no_left_turn", 3))
        with self.assertRaises(RecordError):
            norm("osm_turn_restrictions", fx.TURNS[1])


class StreetIndexTests(unittest.TestCase):
    def test_cnn_segment_vs_intersection(self):
        idx = StreetIndex.from_rows(fx.STREETS)
        self.assertEqual(idx.classify("100"), "segment")
        self.assertEqual(idx.classify("901.0"), "intersection")
        self.assertEqual(idx.classify("555"), "unknown")
        self.assertEqual(idx.geometry_for("901"), {"type": "Point", "coordinates": [-122.419, 37.77]})
        self.assertEqual(idx.geometry_for("200")["type"], "MultiLineString")

    def test_nearest_segment(self):
        idx = StreetIndex.from_rows(fx.STREETS)
        cnn, d = idx.nearest_segment((-122.4195, 37.77005))
        self.assertEqual(cnn, "100")
        self.assertLess(d, 10)
        self.assertIsNone(idx.nearest_segment((-122.45, 37.75)))


class ClosureTests(unittest.TestCase):
    def test_street_closure_utc_and_special_event(self):
        r = norm("street_closures", fx.STREET_CLOSURES[0])
        self.assertEqual(r.valid_from, datetime(2026, 9, 26, 10, tzinfo=UTC))
        self.assertTrue(r.attributes["is_special_event"])
        self.assertEqual(validate(r), [])

    def test_inverted_span_fails_validation(self):
        self.assertIn("valid_to before valid_from", validate(norm("street_closures", fx.STREET_CLOSURES[1])))

    def test_excavation_is_geometryless_with_cnn(self):
        r = norm("excavation_permits", fx.EXCAVATION[0])
        self.assertIsNone(r.geometry)
        self.assertEqual(r.road_ref, {"cnn": "100", "match": "unknown"})
        self.assertEqual(validate(r), [])  # a cnn is a location

    def test_parking_sign_local_days(self):
        r = norm("parking_signs", fx.PARKING_SIGNS[0])
        self.assertEqual((r.valid_from, r.valid_to),
                         (datetime(2026, 9, 25, 7, tzinfo=UTC), datetime(2026, 9, 28, 7, tzinfo=UTC)))
        self.assertIsNone(norm("parking_signs", fx.PARKING_SIGNS[1]).geometry)  # blank location dict
        with self.assertRaises(RecordError):
            norm("parking_signs", fx.PARKING_SIGNS[2])

    def test_caltrans(self):
        r = norm("caltrans_lane_closures", fx.CALTRANS[0])
        self.assertEqual((r.source_id, r.geometry["type"]), ("C1", "LineString"))
        self.assertEqual(r.valid_from, datetime.fromtimestamp(1790000000, UTC))
        self.assertEqual(r.attributes["route"], "US-101")
        self.assertIsNone(norm("caltrans_lane_closures", fx.CALTRANS[1]))  # outside the Bay Area
        with self.assertRaises(RecordError):
            norm("caltrans_lane_closures", fx.CALTRANS[2])

    def test_caltrans_indefinite_end(self):
        row = fx.caltrans_row()
        row["closure"]["closureTimestamp"]["isClosureEndIndefinite"] = "true"
        self.assertIsNone(norm("caltrans_lane_closures", row).valid_to)


class IncidentTests(unittest.TestCase):
    def test_police_located(self):
        r = norm("police_dispatch", fx.POLICE[0])
        self.assertEqual((r.observed_at, r.attributes["category"], r.location_status),
                         (datetime(2026, 9, 26, 0, 10, tzinfo=UTC), "collision", "exact"))

    def test_police_withheld_is_never_geocoded(self):
        r = norm("police_dispatch", fx.POLICE[1])
        self.assertEqual((r.location_status, r.geocode_query), ("withheld", None))
        self.assertEqual(validate(r), [])

    def test_police_unlocated_gets_geocode_query(self):
        r = norm("police_dispatch", fx.POLICE[2])
        self.assertEqual(r.location_status, "unlocated")
        self.assertIn("MISSION ST", r.geocode_query)

    def test_chp(self):
        rows = fx.rows()["chp_incidents"]
        located = norm("chp_incidents", rows[0])
        self.assertEqual(located.geometry, {"type": "Point", "coordinates": [-122.419, 37.775]})
        self.assertEqual(located.observed_at, datetime(2026, 9, 26, 0, 0, tzinfo=UTC))
        self.assertEqual(located.attributes["details"][0]["time"], "2026-09-26T00:02:00Z")
        zero = norm("chp_incidents", rows[1])  # 0:0 from Golden Gate dispatch: kept, unlocated
        self.assertEqual((zero.geometry, zero.location_status), (None, "unlocated"))
        self.assertIn("Alemany", zero.geocode_query)
        self.assertIsNone(norm("chp_incidents", rows[2]))  # Los Angeles: filtered

    def test_categories_and_tokens(self):
        self.assertEqual(incident_category("1183-Trfc Collision-Unkn Inj"), "collision")
        self.assertEqual(incident_category("Traffic Stop"), "other")
        self.assertEqual(incident_category("1125-Traffic Hazard"), "hazard")
        self.assertEqual(location_tokens("I280 N / Bunker Hill Dr Ofr"), frozenset({"280", "BUNKER", "HILL", "OFR"}))


class ValidationTests(unittest.TestCase):
    def test_rejects_naive_datetimes_and_unknown_kind(self):
        r = Record(kind="bogus", source="s", source_id="1", observed_at=datetime(2026, 1, 1))
        errs = validate(r)
        self.assertTrue(any("unknown kind" in e for e in errs))
        self.assertTrue(any("not UTC-aware" in e for e in errs))

    def test_incident_without_location_must_be_flagged(self):
        r = Record(kind="incident", source="s", source_id="1", observed_at=NOW)
        self.assertTrue(validate(r))
        r.location_status = "withheld"
        self.assertEqual(validate(r), [])



def osm_ctx():
    from worker.osm_graphml import edge_index
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "g.graphml"
        path.write_text(fx.GRAPHML, encoding="utf-8")
        idx = edge_index(path)
    return Context(now=NOW, streets=StreetIndex.from_rows(fx.STREETS), osm=idx)


class GraphmlTests(unittest.TestCase):
    def test_segment_ids_and_geometry(self):
        c = osm_ctx()
        self.assertEqual(sorted(c.osm.geometry), ["1-2-0", "2-1-0", "2-3-0", "3-2-0"])
        self.assertEqual(len(c.osm.geometry["1-2-0"]["coordinates"]), 3)            # WKT geometry
        self.assertEqual(c.osm.geometry["3-2-0"]["coordinates"], [[-122.419, 37.771], [-122.419, 37.77]])  # u->v


class MapboxTests(unittest.TestCase):
    def setUp(self):
        self.c = osm_ctx()

    def test_pieces_map_to_directed_osm_edges(self):
        east = norm("mapbox_corridors", fx.mapbox_row("ab"), self.c)
        west = norm("mapbox_corridors", fx.mapbox_row("ba", coords=fx.MARKET_EAST[::-1]), self.c)
        self.assertEqual([r.attributes["road_segment_id"] for r in east], ["1-2-0"])
        self.assertEqual([r.attributes["road_segment_id"] for r in west], ["2-1-0"])  # heading picks direction
        r = east[0]
        self.assertEqual((r.kind, r.source_id, r.observed_at),
                         ("traffic_metric", "2026-09-26T00:40:00Z|1-2-0", datetime(2026, 9, 26, 0, 40, tzinfo=UTC)))
        self.assertAlmostEqual(r.attributes["speed_mph"], 88.4 / 20 * 2.2369362920544, places=2)
        self.assertAlmostEqual(r.attributes["travel_time_sec"], r.attributes["edge_length_m"] / (88.4 / 20), places=0)
        self.assertIsNone(r.attributes["free_flow_speed_mph"])
        self.assertIsNone(r.attributes["congestion_ratio"])  # Mapbox 0-100 isn't the contract's ratio
        self.assertEqual(r.attributes["mapbox_congestion_numeric"], 40)
        self.assertEqual(validate(r), [])

    def test_failed_poll_and_unmatched_route_are_filtered(self):
        self.assertIsNone(norm("mapbox_corridors", fx.mapbox_row(ok=False), self.c))
        self.assertEqual(norm("mapbox_corridors", fx.MAPBOX_POLLS[4], self.c), [])

    def test_partial_coverage_is_dropped(self):
        half = fx.MARKET_EAST[:2]  # one piece = ~50% of the edge; shrink it below the threshold
        row = fx.mapbox_row(coords=half, distance_m=[30.0], duration_s=[10.0])
        self.assertEqual(norm("mapbox_corridors", row, self.c), [])

    def test_malformed_poll_raises(self):
        for bad in (fx.mapbox_row(duration_s=[10.0]), {**fx.mapbox_row(), "polled_at": "2026-09-26T00:40:00"},
                    fx.mapbox_row(coords=[[0, 0], [-122.4195, 37.7701], [-122.419, 37.77]])):
            with self.assertRaises(RecordError):
                norm("mapbox_corridors", bad, self.c)


class LinkTests(unittest.TestCase):
    def setUp(self):
        self.c = osm_ctx()

    def test_osm_edge_to_cnn(self):
        from worker.link import match_cnn
        self.assertEqual(match_cnn(self.c.osm.geometry["1-2-0"], self.c.streets)[0], "100")
        self.assertEqual(match_cnn(self.c.osm.geometry["2-3-0"], self.c.streets), ("200", 0.0))

    def test_segment_ids_for_line_point_and_nothing(self):
        from worker.link import segment_ids_for
        market = {"type": "LineString", "coordinates": [[-122.42, 37.77], [-122.419, 37.77]]}
        self.assertEqual(segment_ids_for(market, self.c.osm), ["1-2-0", "2-1-0"])  # not the cross street
        node = {"type": "Point", "coordinates": [-122.419, 37.77]}
        self.assertEqual(segment_ids_for(node, self.c.osm), ["1-2-0", "2-1-0", "2-3-0", "3-2-0"])
        mid_fifth = {"type": "Point", "coordinates": [-122.419, 37.7705]}
        self.assertEqual(segment_ids_for(mid_fifth, self.c.osm), ["2-3-0", "3-2-0"])
        self.assertEqual(segment_ids_for({"type": "Point", "coordinates": [-122.45, 37.75]}, self.c.osm), [])
        self.assertEqual(segment_ids_for(None, self.c.osm), [])

    def test_speed_limits_by_cnn(self):
        from worker.link import speed_limits_by_cnn
        recs = [norm("speed_limits", r) for r in fx.SPEED_LIMITS[:3]]
        recs.append(norm("speed_limits", {"objectid": "10", "cnn": "100", "speedlimit": "30"}))
        m = speed_limits_by_cnn(recs)
        self.assertEqual(m["100"], {"status": "posted", "posted_mph": 25, "raw_value": "25",
                                    "source": "speed_limits", "source_id": "1", "rows": 2})
        self.assertEqual((m["200"]["status"], m["200"]["posted_mph"]), ("unposted", None))
        self.assertEqual(m["300"]["status"], "state_managed")


if __name__ == "__main__":
    unittest.main()
