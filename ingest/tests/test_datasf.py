import io
import json
import unittest
import urllib.error
import urllib.parse
from datetime import datetime, timezone
from unittest import mock

from datasf import DATASETS, DataSF, DataSFError, active_street_closures, latest
from datasf.datasets import parse_ts, soql_ts


def fake_response(payload):
    return io.BytesIO(json.dumps(payload).encode())


class TimeTests(unittest.TestCase):
    def test_floating_local_timestamp_is_sf_time(self):
        # 2026-09-24 23:44 PDT == 2026-09-25 06:44 UTC
        self.assertEqual(parse_ts("2026-09-24T23:44:00.000"), datetime(2026, 9, 25, 6, 44, tzinfo=timezone.utc))

    def test_utc_column(self):
        self.assertEqual(parse_ts("2026-09-23T13:00:00.000", is_utc=True), datetime(2026, 9, 23, 13, tzinfo=timezone.utc))

    def test_round_trip(self):
        dt = datetime(2026, 7, 5, 4, 30, tzinfo=timezone.utc)
        self.assertEqual(soql_ts(dt), "2026-07-04T21:30:00")
        self.assertEqual(parse_ts(soql_ts(dt)), dt)


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.client = DataSF(app_token="tok", retries=2)

    def test_query_builds_soql_url_and_sends_token(self):
        with mock.patch("urllib.request.urlopen", return_value=fake_response([{"a": 1}])) as urlopen:
            rows = self.client.query("abcd-1234", where="x > 1", order="x DESC", limit=5)
        req = urlopen.call_args[0][0]
        url = urllib.parse.urlparse(req.full_url)
        self.assertEqual(url.path, "/resource/abcd-1234.json")
        self.assertEqual(urllib.parse.parse_qs(url.query), {"$where": ["x > 1"], "$order": ["x DESC"], "$limit": ["5"]})
        self.assertEqual(req.get_header("X-app-token"), "tok")
        self.assertEqual(rows, [{"a": 1}])

    def test_iter_rows_pages_until_short_page(self):
        pages = [[{"i": 0}, {"i": 1}], [{"i": 2}, {"i": 3}], [{"i": 4}]]
        with mock.patch.object(self.client, "query", side_effect=pages) as q:
            rows = list(self.client.iter_rows("abcd-1234", page_size=2))
        self.assertEqual([r["i"] for r in rows], [0, 1, 2, 3, 4])
        self.assertEqual([c.kwargs["offset"] for c in q.call_args_list], [0, 2, 4])

    def test_iter_rows_respects_max_rows(self):
        with mock.patch.object(self.client, "query", side_effect=[[{"i": 0}, {"i": 1}], [{"i": 2}]]) as q:
            rows = list(self.client.iter_rows("abcd-1234", page_size=2, max_rows=3))
        self.assertEqual(len(rows), 3)
        self.assertEqual(q.call_args_list[1].kwargs["limit"], 1)

    def test_retries_on_429_then_succeeds(self):
        err = urllib.error.HTTPError("u", 429, "slow down", {"Retry-After": "0"}, io.BytesIO(b""))
        with mock.patch("urllib.request.urlopen", side_effect=[err, fake_response([])]), mock.patch("time.sleep"):
            self.assertEqual(self.client.query("abcd-1234"), [])

    def test_client_error_raises_without_retry(self):
        err = urllib.error.HTTPError("u", 400, "bad", {}, io.BytesIO(b'{"message":"bad soql"}'))
        with mock.patch("urllib.request.urlopen", side_effect=err) as urlopen:
            with self.assertRaises(DataSFError) as ctx:
                self.client.query("abcd-1234")
        self.assertEqual(ctx.exception.status, 400)
        self.assertEqual(urlopen.call_count, 1)


class DatasetQueryTests(unittest.TestCase):
    def test_latest_filters_future_rows_and_applies_default_where(self):
        client = mock.Mock()
        now = datetime(2026, 9, 26, 12, tzinfo=timezone.utc)
        latest(client, DATASETS["sf311_street"], 2, not_after=now)
        kw = client.query.call_args.kwargs
        self.assertEqual(kw["order"], "requested_datetime DESC")
        self.assertIn("requested_datetime <= '2026-09-26T05:00:00'", kw["where"])  # SF local
        self.assertIn("Blocked Street and Sidewalk", kw["where"])

    def test_active_closures_uses_utc_window(self):
        client = mock.Mock()
        client.iter_rows.return_value = iter([{"type": "Special Event"}])
        rows = active_street_closures(client, datetime(2026, 9, 26, 12, tzinfo=timezone.utc))
        kw = client.iter_rows.call_args.kwargs
        self.assertEqual(kw["where"], "start_utc <= '2026-09-26T12:00:00' AND end_utc >= '2026-09-26T12:00:00'")
        self.assertEqual(rows, [{"type": "Special Event"}])


if __name__ == "__main__":
    unittest.main()
