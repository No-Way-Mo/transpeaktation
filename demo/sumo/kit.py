#!/usr/bin/env python3
"""Offline preparation by default. Only the explicit run subcommand starts SUMO."""
import argparse
from datetime import datetime, timedelta
import hashlib
import json
import math
from pathlib import Path
import random
import shutil
import statistics
import subprocess
import sys
from urllib.parse import urlencode
import xml.etree.ElementTree as ET

START = datetime.fromisoformat('2026-07-04T20:00:00-07:00')
# Hardcoded curb-area coordinates, lon/lat. Repeated ODs represent distinct users.
PLACES = {
    'mission': [-122.4194, 37.7599], 'castro': [-122.4350, 37.7609],
    'sunset': [-122.4660, 37.7637], 'richmond': [-122.4661, 37.7810],
    'union_square': [-122.4075, 37.7880], 'caltrain': [-122.3952, 37.7764],
    'marina': [-122.4368, 37.8005], 'ferry': [-122.3940, 37.7955],
    'wharf': [-122.4157, 37.8075], 'oracle': [-122.3893, 37.7786],
}
# Version 2: 1000 users steered through the northern waterfront and downtown. Busy places are
# destinations/waypoints by construction; this is synthetic demand, not observed July 4 travel.
HOMES = ['mission', 'castro', 'sunset', 'richmond', 'caltrain', 'oracle',
         'pacific_heights', 'hayes_valley', 'noe_valley', 'soma']
BUSY = ['wharf', 'pier_39', 'ghirardelli', 'fort_mason', 'marina_green', 'marina',
        'north_beach', 'chinatown', 'union_square', 'ferry']
PLACES |= {
    'pier_39': [-122.4098, 37.8086], 'ghirardelli': [-122.4225, 37.8057],
    'fort_mason': [-122.4325, 37.8052], 'marina_green': [-122.4400, 37.8056],
    'north_beach': [-122.4098, 37.8003], 'chinatown': [-122.4077, 37.7939],
    'pacific_heights': [-122.4340, 37.7898], 'hayes_valley': [-122.4240, 37.7765],
    'noe_valley': [-122.4318, 37.7516], 'soma': [-122.4016, 37.7839],
}
# Version 3: fireworks exodus, 21:00-23:00. Timing from the fetched PredictHQ record (show starts 21:30)
# and SFMTA's advisory (show ~21:30-21:45; Crissy Field, Marina Green, northern waterfront viewing areas).
VIEW = ['golden_gate', 'crissy_field', 'marina_green', 'fort_mason', 'ghirardelli', 'wharf', 'pier_39']
PLACES |= {'golden_gate': [-122.4742, 37.8065], 'crissy_field': [-122.4510, 37.8047]}
EVENT = dict(source='PredictHQ', title='Fourth of July fireworks on Golden Gate Bridge',
             start='2026-07-04T21:30:00-07:00', phq_attendance=300000)
V3_START = START + timedelta(hours=1)
ARRIVE, LEAVE = (0, 1800), (2700, 6300)  # 21:00-21:30 to a viewing site; 21:45-22:45 away from one


def exodus(rng):
    # ponytail: uniform site/home/time picks; replace with observed exit counts if they ever exist.
    return rng.choice(VIEW), rng.choice(HOMES), rng.randrange(*LEAVE)


V1 = ['mission', 'castro', 'sunset', 'richmond', 'union_square', 'caltrain', 'marina', 'ferry', 'wharf', 'oracle']


def require(ok, message):
    if not ok:
        raise ValueError(message)


def write_json(path, value):
    with Path(path).open('x') as f:
        json.dump(value, f, indent=2, allow_nan=False)
        f.write('\n')


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def scenario(seed=42, version=1):
    rng = random.Random(seed)
    trips = []
    start = V3_START if version == 3 else START
    for i in range(500 if version == 1 else 1000):
        if version == 3:  # 25% head to a viewing site before the show, 75% leave one after it
            if rng.random() < 0.25:
                a, b, depart = rng.choice(HOMES), rng.choice(VIEW), rng.randrange(*ARRIVE)
            else:
                a, b, depart = exodus(rng)
        else:
            if version == 1:
                a, b = rng.sample(V1, 2)
            else:  # 50% home -> busy, 35% busy -> busy, 15% busy -> home
                r = rng.random()
                a, b = ((rng.choice(HOMES), rng.choice(BUSY)) if r < 0.5 else rng.sample(BUSY, 2) if r < 0.85
                        else (rng.choice(BUSY), rng.choice(HOMES)))
            depart = rng.randrange(7200)
        trips.append(dict(id=f'user-{i:04d}', origin=PLACES[a], destination=PLACES[b],
                          origin_name=a, destination_name=b, depart=depart,
                          depart_at=(start + timedelta(seconds=depart)).isoformat()))
    out = dict(version=version, seed=seed, start=start.isoformat(), admission_seconds=7200,
               description='Synthetic bookings; no historical traffic calibration' + (
                   '' if version == 1 else '; 1000 users routed to/through waterfront and downtown places' if version == 2
                   else '; 1000 users: 25% go to fireworks viewing sites 21:00-21:30, 75% leave them 21:45-22:45'),
               coordinate_order='lon,lat', trips=sorted(trips, key=lambda t: (t['depart'], t['id'])))
    if version == 3:
        out['event'] = EVENT
    return out


def load_scenario(path):
    s = json.loads(Path(path).read_text())
    require(s == scenario(s['seed'], s['version']), 'Scenario must match the seeded kit scenario; regenerate it')
    return s


def make_scenario(args):
    s = scenario(args.seed, args.version)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=False)
    write_json(out / 'scenario.json', s)
    # Request paths are a demand export, never executed here.
    with (out / 'requests.jsonl').open('x') as f:
        for t in s['trips']:
            query = urlencode({'from': ','.join(map(str, t['origin'])),
                               'to': ','.join(map(str, t['destination'])),
                               'depart_at': t['depart_at'], 'replay': 'true'})
            f.write(json.dumps({'trip_id': t['id'], 'path': '/plan?' + query}) + '\n')


def ml_routes(path, s):
    data = json.loads(Path(path).read_text())
    require(data['coordinate_order'] == 'lat,lon', 'ML coords must explicitly be lat,lon')
    require(data['scenario_sha256'] == digest(s), 'ML output belongs to a different scenario')
    trips = load_scenario(s)['trips']
    rows = data['routes']
    by_id = {r['trip_id']: r for r in rows}
    require(len(rows) == len(by_id) == len(trips) and set(by_id) == {t['id'] for t in trips},
            'Need exactly one ML route per trip; no duplicates, extras, or omissions')
    for t in trips:
        r = by_id[t['id']]
        require(isinstance(r['decision'], str) and r['decision'].startswith('ml:')
                and r['decision'][3:].strip(), f"{t['id']}: heuristic/missing ML decision")
        require(r['depart_at'] == t['depart_at'], 'ML departure differs from scenario')
        coords = r['coords']
        require(isinstance(coords, list) and len(coords) >= 2, 'Need final route geometry')
        for p in coords:
            require(isinstance(p, list) and len(p) == 2 and
                    all(type(x) in (int, float) and math.isfinite(x) for x in p)
                    and 37.6 < p[0] < 37.9 and -122.6 < p[1] < -122.3,
                    'Invalid SF lat,lon coordinate (check coordinate order)')
    return by_id


def validate_route(edges, start, end):
    require(edges and edges[0] == start and edges[-1] == end, 'Route endpoint edges differ')
    require(all(e.allows('passenger') and not e.getID().startswith(':') for e in edges),
            'Route contains internal or passenger-forbidden edges')
    for a, b in zip(edges, edges[1:]):
        require(any(c.allows('passenger') and c.getFromLane().allows('passenger')
                    and c.getToLane().allows('passenger') for c in a.getOutgoing().get(b, [])),
                f'Disconnected or forbidden turn: {a.getID()} -> {b.getID()}')


def snap(net, lonlat, radius):
    # ponytail: nearest edge ignores curb direction/along-edge position; use calibrated
    # pickup edge/position pairs when block-level endpoint error affects conclusions.
    xy = net.convertLonLat2XY(*lonlat)
    candidates = [(d, e.getID(), e) for e, d in net.getNeighboringEdges(*xy, r=radius)
                  if e.allows('passenger') and not e.getID().startswith(':')]
    require(candidates, f'No passenger edge within {radius}m of {lonlat}')
    return min(candidates)[2]


def build(args):
    import sumolib
    from sumolib.route import mapTrace
    s = load_scenario(args.scenario)
    ml = ml_routes(args.ml, args.scenario) if args.ml else None
    require(args.end >= s['admission_seconds'] and math.isfinite(args.radius) and args.radius > 0,
            'end must cover the admission window; radius must be positive and finite')
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=False)
    for src, name in [(args.net, 'network.net.xml'), (args.scenario, 'scenario.json'),
                      (__file__, 'kit.py')]:
        shutil.copyfile(src, out / name)
    if args.ml:
        shutil.copyfile(args.ml, out / 'ml.json')
    net = sumolib.net.readNet(str(out / 'network.net.xml'), withInternal=True)
    # --placeholder: an `ml` variant on the baseline's own routes, so the demo can run both before ML exists.
    roots = {k: ET.Element('routes') for k in (('baseline', 'ml') if ml or args.placeholder else ('baseline',))}
    for root in roots.values():
        ET.SubElement(root, 'vType', id='kit-car', vClass='passenger', speedFactor='1', speedDev='0')
    audit = []
    # The 500 users share ten locations; snap each location only once.
    points = {tuple(t[k]) for t in s['trips'] for k in ('origin', 'destination')}
    snapped = {point: snap(net, point, args.radius) for point in sorted(points)}
    for t in s['trips']:
        try:
            a, b = [snapped[tuple(t[k])] for k in ('origin', 'destination')]
            baseline, _ = net.getFastestPath(a, b, vClass='passenger')
            paths = {'baseline': baseline} | ({'ml': baseline} if args.placeholder else {})
            if ml:
                trace = [net.convertLonLat2XY(lon, lat) for lat, lon in ml[t['id']]['coords']]
                for p, key in [(trace[0], 'origin'), (trace[-1], 'destination')]:
                    require(math.dist(p, net.convertLonLat2XY(*t[key])) <= args.radius,
                            'ML geometry endpoint too far from requested OD')
                # ponytail: linear densification assumes provider geometry follows each bend;
                # sparse waypoints are not geometry. Export full geometry to upgrade fidelity.
                dense = []
                for p, q in zip(trace, trace[1:]):
                    n = max(1, math.ceil(math.dist(p, q) / 10))
                    dense.extend((p[0] + (q[0]-p[0])*i/n, p[1] + (q[1]-p[1])*i/n) for i in range(n))
                dense.append(trace[-1])
                # ponytail: 30 m search around each point (endpoints are pinned by vias); args.radius here was
                # ~10x slower. Raise it if provider geometry drifts further from SUMO's lanes.
                mapped = mapTrace(dense, net, min(args.radius, 30), vClass='passenger', fillGaps=0,
                                  vias={0: [a.getID()], len(dense)-1: [b.getID()]})
                paths['ml'] = [e for e in mapped if not e.getID().startswith(':')]  # junction internals: validate_route rechecks the turns
            for name, edges in paths.items():
                validate_route(edges, a, b)
                v = ET.SubElement(roots[name], 'vehicle', id=t['id'], type='kit-car',
                                  depart=str(t['depart']), departLane='best', departPos='0',
                                  departSpeed='0', arrivalPos='max')
                ET.SubElement(v, 'route', edges=' '.join(e.getID() for e in edges))
            audit.append(dict(trip_id=t['id'], from_edge=a.getID(), to_edge=b.getID(),
                              baseline_edges=len(baseline), ml_edges=len(paths['ml']) if ml else None))
        except ValueError as e:
            raise ValueError(f"{t['id']}: {e}; incomplete bundle must not be run") from e
    # Only fixed, explicitly enumerated background vehicles; no flows or rerouting devices.
    if args.background:
        bg = ET.parse(args.background).getroot()
        require(bg.tag == 'routes', 'Background root must be routes')
        ids = set()
        last_depart = -1.0
        for v in bg:
            require(v.tag == 'vehicle' and set(v.attrib) == {'id', 'depart'}
                    and v.get('id', '').startswith('bg-') and v.get('id') not in ids,
                    'Background needs unique bg-* vehicles with only id/depart attributes')
            ids.add(v.get('id'))
            require(0 <= float(v.get('depart')) < args.end and len(v) == 1 and v[0].tag == 'route'
                    and set(v[0].attrib) == {'edges'}, 'Background requires fixed inline edges and depart in [0,end)')
            depart = float(v.get('depart'))
            require(depart >= last_depart, 'Background vehicles must be sorted by departure')
            last_depart = depart
            edges = [net.getEdge(e) for e in v[0].get('edges').split()]
            require(edges, 'Empty background route')
            validate_route(edges, edges[0], edges[-1])
        shutil.copyfile(args.background, out / 'background.rou.xml')
    for name, root in roots.items():
        ET.ElementTree(root).write(out / f'{name}.rou.xml', encoding='utf-8', xml_declaration=True)
    write_json(out / 'matching.json', audit)
    write_json(out / 'manifest.json', dict(seed=s['seed'], end=args.end, radius=args.radius, variants=list(roots),
        placeholder=bool(args.placeholder),
        baseline='SUMO free-flow fastest on imported OSM; not OSRM/Mapbox',
        sumolib_version=getattr(sumolib, '__version__', 'unknown'),
        inputs={p.name: digest(p) for p in sorted(out.iterdir()) if p.is_file()}))


def background(args):
    # Non-app crowd leaving the viewing sites: fixed fastest routes, identical in every variant.
    import sumolib
    s = load_scenario(args.scenario)
    require(s['version'] == 3 and args.count > 0, 'Background exodus needs a version 3 scenario and a positive count')
    net = sumolib.net.readNet(args.net, withInternal=True)
    homes = {h: snap(net, PLACES[h], args.radius) for h in HOMES}
    # Crowd cars are parked around each viewing site: start on any ordinary street edge within --spread metres
    # (no freeways or ramps) that reaches every home.
    parked = {}
    for site in VIEW:
        near = sorted((e.getID(), e) for e, _ in net.getNeighboringEdges(*net.convertLonLat2XY(*PLACES[site]), r=args.spread)
                      if e.allows('passenger') and not e.getID().startswith(':')
                      and not any(k in (e.getType() or '') for k in ('motorway', 'trunk', '_link')))
        parked[site] = [e for _, e in near if all(net.getFastestPath(e, h, vClass='passenger')[0] for h in homes.values())]
        require(parked[site], f'No street edge within {args.spread} m of {site}')
    rng = random.Random(args.seed)
    rows = []
    for _ in range(args.count):
        site, home, depart = exodus(rng)
        rows.append((rng.choice(parked[site]), home, depart))
    rows.sort(key=lambda r: r[2])
    paths, root = {}, ET.Element('routes')
    for i, (start, home, depart) in enumerate(rows):
        if (start, home) not in paths:
            paths[start, home] = net.getFastestPath(start, homes[home], vClass='passenger')[0]
            validate_route(paths[start, home], start, homes[home])
        v = ET.SubElement(root, 'vehicle', id=f'bg-{i:05d}', depart=str(depart))
        ET.SubElement(v, 'route', edges=' '.join(e.getID() for e in paths[start, home]))
    with Path(args.out).open('xb') as f:
        ET.ElementTree(root).write(f, encoding='utf-8', xml_declaration=True)
    write_json(Path(args.out).with_suffix('.json'), dict(
        count=args.count, seed=args.seed, radius=args.radius, spread=args.spread, scenario_sha256=digest(args.scenario),
        parked_edges={k: len(v) for k, v in parked.items()},
        origins=VIEW, destinations=HOMES, depart_seconds=list(LEAVE), start=s['start'], event=EVENT,
        note='Assumed crowd size and uniform picks; not observed July 4 traffic.'))


def summarize(path, expected):
    rows = {}
    if Path(path).exists():
        for v in ET.parse(path).getroot().findall('tripinfo'):
            if v.get('id') not in expected:
                continue
            require(v.get('id') not in rows, 'Duplicate tripinfo ID')
            rows[v.get('id')] = v.attrib
    statuses, complete = {}, {}
    for id in expected:
        v = rows.get(id)
        status = 'missing'
        if v:
            # write-unfinished marks cars still running or never inserted at the horizon as vaporized="end".
            if v.get('vaporized') not in ('', 'end', None) or int(v.get('rerouteNo', '0')):
                status = 'failed'
            elif float(v['depart']) < 0:
                status = 'not_departed'
            elif float(v['arrival']) < 0:
                status = 'unfinished'
            else:
                status = 'completed'
                values = {k: float(v[k]) for k in
                          ('departDelay', 'duration', 'waitingTime', 'timeLoss', 'routeLength')}
                require(all(math.isfinite(x) and x >= 0 for x in values.values()), 'Invalid trip metrics')
                values['total_seconds'] = values['departDelay'] + values['duration']
                complete[id] = values
        statuses[id] = status
    metrics = {}
    for k in next(iter(complete.values()), {}):
        values = sorted(v[k] for v in complete.values())
        metrics[k] = dict(mean=statistics.mean(values), p95=values[math.ceil(.95*len(values))-1])
    return dict(counts={k: list(statuses.values()).count(k) for k in
                       ('completed', 'unfinished', 'not_departed', 'failed', 'missing')},
                completed_only_metrics=metrics, trips=statuses), complete


def comparison(results, completed, clean):
    if 'ml' not in results:
        return dict(mode='baseline-only', clean=bool(clean),
                    note='No ML run or comparative claim; synthetic OSM baseline.', variants=results)
    eligible = clean and all(all(v == 'completed' for v in r['trips'].values()) for r in results.values())
    paired = sorted(set(completed['baseline']) & set(completed['ml']))
    delta = [completed['ml'][i]['total_seconds'] - completed['baseline'][i]['total_seconds'] for i in paired]
    return dict(eligible_for_full_cohort_comparison=eligible, paired_completed_count=len(paired),
                paired_mean_delta_seconds=statistics.mean(delta) if delta else None,
                full_cohort_mean_delta_seconds=statistics.mean(delta) if eligible and delta else None,
                note='ML minus baseline; negative is faster. Paired-only metrics may have survivor bias.',
                variants=results)


def run(args):
    bundle = Path(args.bundle).resolve()
    m = json.loads((bundle / 'manifest.json').read_text())
    for name, sha in m['inputs'].items():
        require(Path(name).name == name and digest(bundle / name) == sha, f'Changed input: {name}')
    s = load_scenario(bundle / 'scenario.json')
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=False)
    # Archive the entire bundle so later changes cannot destroy run provenance.
    shutil.copytree(bundle, out / 'inputs')
    bundle = out / 'inputs'
    version = subprocess.check_output([args.sumo, '--version'], text=True)
    records, results, completed = {}, {}, {}
    clean = True
    for name in m.get('variants', ['baseline', 'ml']):
        require(name in ('baseline', 'ml'), 'Unknown variant in manifest')
        routes = str(bundle / f'{name}.rou.xml')
        if (bundle / 'background.rou.xml').exists():
            routes += ',' + str(bundle / 'background.rou.xml')
        cmd = [args.sumo, '--net-file', str(bundle / 'network.net.xml'), '--route-files', routes,
               '--begin', '0', '--end', str(m['end']), '--seed', str(m['seed']),
               '--time-to-teleport', '-1', '--max-depart-delay', '-1',
               '--device.rerouting.probability', '0', '--ignore-route-errors', 'false',
               '--tripinfo-output', str(out / f'{name}.tripinfo.xml'),
               '--tripinfo-output.write-unfinished', 'true',
               '--tripinfo-output.write-undeparted', 'true', '--no-step-log', 'true']
        # SUMO's native config writer creates a reusable GUI/headless demo entrypoint.
        subprocess.run(cmd + ['--save-configuration', str(out / f'{name}.sumocfg'),
                              '--save-configuration.relative', 'true'],
                       check=True, stdout=subprocess.DEVNULL)
        with (out / f'{name}.log').open('x') as log:
            code = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT).returncode
        records[name] = dict(command=cmd, returncode=code)
        clean &= code == 0 and 'Warning:' not in (out / f'{name}.log').read_text()
        expected = {t['id'] for t in s['trips']}
        try:
            results[name], completed[name] = summarize(out / f'{name}.tripinfo.xml', expected)
        except (ET.ParseError, ValueError, KeyError) as e:
            clean = False
            records[name]['output_error'] = str(e)
            results[name], completed[name] = summarize(out / 'no-valid-tripinfo.xml', expected)
    write_json(out / 'execution.json', dict(sumo_version=version, runs=records))
    report = comparison(results, completed, clean)
    if m.get('placeholder'):
        report['note'] = 'PLACEHOLDER: the ml variant drives the baseline routes; no ML output, no comparative claim.'
    write_json(out / 'report.json', report)
    require(clean, 'SUMO failure/warnings: inspect logs; report is not eligible for a performance claim')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    a = sub.add_parser('scenario', help='Write synthetic users and request paths; offline')
    a.add_argument('--out', required=True)
    a.add_argument('--seed', type=int, default=42)
    a.add_argument('--version', type=int, choices=(1, 2, 3), default=1,
                   help='1: 500 users between 10 places; 2: 1000 users through waterfront/downtown; '
                        '3: 1000 users around the fireworks, 21:00-23:00')
    a.set_defaults(func=make_scenario)
    a = sub.add_parser('background', help='Write the version 3 non-app exodus background; offline')
    for name in ('scenario', 'net', 'out'):
        a.add_argument('--' + name, required=True)
    a.add_argument('--count', type=int, required=True, help='assumed number of crowd cars')
    a.add_argument('--spread', type=float, default=400, help='metres around each viewing site where crowd cars are parked')
    a.add_argument('--seed', type=int, default=42)
    a.add_argument('--radius', type=float, default=60)
    a.set_defaults(func=background)
    a = sub.add_parser('build', help='Map/validate routes and prepare bundle; does NOT run SUMO')
    for name in ('scenario', 'net', 'out'):
        a.add_argument('--' + name, required=True)
    mode = a.add_mutually_exclusive_group(required=True)
    mode.add_argument('--ml', help='Import ML routes and build both variants')
    mode.add_argument('--baseline-only', action='store_true', help='Build without ML output')
    mode.add_argument('--placeholder', action='store_true', help='Build an ml variant on the baseline routes (no ML yet)')
    a.add_argument('--background')
    a.add_argument('--radius', type=float, default=60)
    a.add_argument('--end', type=int, default=10800)
    a.set_defaults(func=build)
    a = sub.add_parser('run', help='EXPLICITLY RUN the bundle variants (baseline-only or comparison)')
    a.add_argument('--bundle', required=True)
    a.add_argument('--out', required=True)
    a.add_argument('--sumo', default='sumo')
    a.set_defaults(func=run)
    args = p.parse_args()
    try:
        args.func(args)
    except (ValueError, KeyError, TypeError, OSError, ImportError, ET.ParseError, subprocess.SubprocessError) as e:
        sys.exit(f'Error: {e}')


if __name__ == '__main__':
    main()
