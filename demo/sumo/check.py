"""Small offline regression check. No SUMO, network, API, or database required."""
import copy
from datetime import timezone
from pathlib import Path
import tempfile
from types import SimpleNamespace
import xml.etree.ElementTree as ET
import contextlib, http.server, io, json, sys, threading
from urllib.parse import parse_qs, urlparse
import kit, ml_routes


def rejects(fn):
    try:
        fn()
    except (ValueError, FileExistsError):
        return
    raise AssertionError('Expected rejection')


s = kit.scenario()
assert s == kit.scenario() and s != kit.scenario(43)
assert len(s['trips']) == len({t['id'] for t in s['trips']}) == 500
assert kit.START.astimezone(timezone.utc).isoformat() == '2026-07-05T03:00:00+00:00'
assert all(0 <= t['depart'] < 7200 and t['origin'] != t['destination'] for t in s['trips'])
v2 = kit.scenario(42, 2)
assert v2 == kit.scenario(42, 2) and len({t['id'] for t in v2['trips']}) == 1000 and v2['version'] == 2
assert all(0 <= t['depart'] < 7200 and t['origin'] != t['destination'] and kit.BUSY.count(t['origin_name'])
           + kit.BUSY.count(t['destination_name']) for t in v2['trips'])
v3 = kit.scenario(42, 3)
assert v3 == kit.scenario(42, 3) and len(v3['trips']) == 1000 and v3['start'] == '2026-07-04T21:00:00-07:00'
assert all((t['destination_name'] in kit.VIEW and 0 <= t['depart'] < 1800) or
           (t['origin_name'] in kit.VIEW and 2700 <= t['depart'] < 6300) for t in v3['trips'])

with tempfile.TemporaryDirectory() as tmp:
    p = Path(tmp)
    kit.make_scenario(SimpleNamespace(out=p / 'scenario', seed=42, version=1))
    rejects(lambda: kit.make_scenario(SimpleNamespace(out=p / 'scenario', seed=42, version=1)))
    sp = p / 'scenario/scenario.json'
    data = dict(coordinate_order='lat,lon', scenario_sha256=kit.digest(sp), routes=[
        dict(trip_id=t['id'], decision='ml:offline-fixture', depart_at=t['depart_at'],
             coords=[t['origin'][::-1], t['destination'][::-1]]) for t in s['trips']])
    mp = p / 'ml.json'
    kit.write_json(mp, data)
    assert len(kit.ml_routes(mp, sp)) == 500
    for mutate in [lambda d: d['routes'].pop(),
                   lambda d: d['routes'].append(d['routes'][0]),
                   lambda d: d['routes'][0].update(decision='heuristic'),
                   lambda d: d.update(scenario_sha256='wrong'),
                   lambda d: d['routes'][0].update(coords=[[-122.4, 37.7], [-122.4, 37.8]]),
                   lambda d: d['routes'][0].update(depart_at='wrong')]:
        bad = copy.deepcopy(data)
        mutate(bad)
        mp.unlink()
        kit.write_json(mp, bad)
        rejects(lambda: kit.ml_routes(mp, sp))

    root = ET.Element('tripinfos')
    for id, extra in [('a', {}), ('b', {'arrival': '-1'}), ('c', {'depart': '-1', 'arrival': '-1'}),
                      ('d', {'vaporized': 'collision'}), ('f', {'arrival': '-1', 'vaporized': 'end'}),
                      ('g', {'depart': '-1', 'arrival': '-1', 'vaporized': 'end'})]:
        attrs = dict(id=id, depart='0', arrival='20', departDelay='5', duration='20',
                     waitingTime='2', timeLoss='3', routeLength='100', vaporized='', rerouteNo='0')
        attrs.update(extra)
        ET.SubElement(root, 'tripinfo', attrs)
    fp = p / 'tripinfo.xml'
    ET.ElementTree(root).write(fp)
    report, completed = kit.summarize(fp, {'a', 'b', 'c', 'd', 'e', 'f', 'g'})
    assert report['counts'] == dict(completed=1, unfinished=2, not_departed=2, failed=1, missing=1)
    assert report['completed_only_metrics']['total_seconds'] == dict(mean=25, p95=25)
    r = kit.comparison(dict(baseline=report, ml=report), dict(baseline=completed, ml=completed), True)
    assert not r['eligible_for_full_cohort_comparison'] and r['full_cohort_mean_delta_seconds'] is None
    good, done = kit.summarize(fp, {'a'})
    assert kit.comparison(dict(baseline=good, ml=good), dict(baseline=done, ml=done), True)['full_cohort_mean_delta_seconds'] == 0
    only = kit.comparison(dict(baseline=good), dict(baseline=done), True)
    assert only['mode'] == 'baseline-only' and set(only['variants']) == {'baseline'}
    assert 'full_cohort_mean_delta_seconds' not in only
    assert not kit.comparison(dict(baseline=good, ml=good), dict(baseline=done, ml=done), False)['eligible_for_full_cohort_comparison']

# Exercise shared connectivity/permission validation without mocking a SUMO execution.
class Edge:
    def __init__(self, id, allowed=True):
        self.id, self.allowed, self.out = id, allowed, {}
    def allows(self, cls): return self.allowed
    def getID(self): return self.id
    def getOutgoing(self): return self.out
    def getFromLane(self): return self
    def getToLane(self): return self


a, b = Edge('a'), Edge('b')
a.out[b] = [Edge('connection')]
kit.validate_route([a, b], a, b)
rejects(lambda: kit.validate_route([a], a, b))
a.out[b][0].allowed = False
rejects(lambda: kit.validate_route([a, b], a, b))
a.out.clear()
rejects(lambda: kit.validate_route([a, b], a, b))
a.out[b] = [Edge('connection')]
b.allowed = False
rejects(lambda: kit.validate_route([a, b], a, b))

# ml_routes.py against a stand-in /plan: exports every trip once, resumes, refuses heuristic answers.
calls, decision = [], ['heuristic (ml/ unreachable)']
class Plan(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        q = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
        calls.append(q)
        (a, b), (c, d) = (map(float, q[k].split(',')) for k in ('from', 'to'))
        body = json.dumps({'routes': [{'coords': []}, {'coords': [[b, a], [d, c]]}], 'plan': {'best': 1},
                           'data': {'decision': decision[0]}}).encode()
        self.send_response(200); self.end_headers(); self.wfile.write(body)
    def log_message(self, *a): pass
srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Plan)
threading.Thread(target=srv.serve_forever, daemon=True).start()
with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
    p = Path(tmp)
    kit.make_scenario(SimpleNamespace(out=p / 'demand', seed=42, version=1))
    sys.argv = ['ml_routes', '--demand', str(p / 'demand'), '--out', str(p / 'ml'), '--api', f'http://127.0.0.1:{srv.server_port}']
    try:
        ml_routes.main()
        raise AssertionError('heuristic routes must not become ml.json')
    except SystemExit:
        pass
    assert len(calls) == 500 and all(q['replay'] == 'true' for q in calls) and not (p / 'ml/ml.json').exists()
    (p / 'ml/responses.jsonl').write_text('')   # ask again, now answered by ml/, and stop after 100 calls
    decision[0], real = 'ml:fixture', ml_routes.urllib.request.urlopen
    ml_routes.urllib.request.urlopen = lambda *a, **k: real(*a, **k) if len(calls) < 600 else (_ for _ in ()).throw(OSError('cut'))
    try:
        ml_routes.main()
    except OSError:
        pass
    ml_routes.urllib.request.urlopen = real
    ml_routes.main()   # resumes: only the 400 missing trips are asked
    assert len(calls) == 1000 and len(kit.ml_routes(p / 'ml/ml.json', p / 'demand/scenario.json')) == 500
srv.shutdown()
print('PASS: ML route export (resumable, ml:-only), 500-user determinism/time, ML validation, route guards, incomplete-cohort accounting, no overwrite')
