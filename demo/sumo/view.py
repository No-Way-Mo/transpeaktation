"""Export a SUMO baseline run plus its FCD replay as demo/baseline.data.js for demo/baseline.html.

    demo/sumo/.venv/bin/python demo/sumo/view.py --run demo/sumo/runs/<measured-run> \
      --replay demo/sumo/runs/<new-replay-dir> --sumo demo/sumo/.venv/bin/sumo --out demo/baseline.data.js

If --replay does not exist yet, each variant is rerun with the exact command in the run's execution.json,
tripinfo redirected into --replay, plus `--fcd-output <variant>.fcd.xml --fcd-output.geo true
--fcd-output.attributes x,y,speed,waiting` (lon/lat, speed and SUMO's waiting counter of every vehicle every
simulated second).
Only app users (the scenario) get FCD; every vehicle, including identical background traffic, is
counted in SUMO's per-second --summary-output and per-minute edgeData (road speeds).
Nothing is interpolated or invented: the export aborts unless each replayed tripinfo matches the measured run,
every trip's FCD samples cover exactly its departure to arrival, and its seconds with waiting > 0 equal tripinfo
waitingTime. Variants come from report.json (`baseline` now; `ml` once a real ML run exists).
"""
import argparse, bisect, hashlib, json, re, subprocess, xml.etree.ElementTree as ET
from pathlib import Path

from pyproj import Proj

import kit

PERIOD = 60  # seconds per edgeData interval

def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def tripinfo(p):
    return {e.get('id'): e.attrib for e in ET.parse(p).getroot().iter('tripinfo')}


def same(measured, replay):
    # The replay adds an fcd device to each vehicle; every other value must be identical.
    def eq(a, b):
        try:
            return abs(float(a) - float(b)) <= 0.005 + 1e-9
        except ValueError:
            return a == b
    return measured.keys() == replay.keys() and all(
        eq(v, replay[i][k]) for i, t in measured.items() for k, v in t.items() if k != 'devices')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--run', required=True, type=Path)
    ap.add_argument('--replay', required=True, type=Path)
    ap.add_argument('--out', required=True, type=Path)
    ap.add_argument('--sumo', default='sumo', help='SUMO binary for a new replay (same version as the run)')
    a = ap.parse_args()

    report = json.loads((a.run / 'report.json').read_text())
    manifest = json.loads((a.run / 'inputs/manifest.json').read_text())
    execution = json.loads((a.run / 'execution.json').read_text())
    scenario = json.loads((a.run / 'inputs/scenario.json').read_text())
    for name, h in manifest['inputs'].items():
        assert sha(a.run / 'inputs' / name) == h, f'{name} changed since the run'

    users = {t['id']: t for t in scenario['trips']}
    if not a.replay.exists():
        a.replay.mkdir(parents=True)
        for name, r in execution['runs'].items():
            out = lambda f: str((a.replay / f'{name}.{f}').resolve())
            Path(out('edgedata.add.xml')).write_text(
                f'<additional><edgeData id="roads" period="{PERIOD}" file="{out("edges.xml")}" excludeEmpty="true"/></additional>\n')
            cmd = [a.sumo] + r['command'][1:]
            cmd[cmd.index('--tripinfo-output') + 1] = out('tripinfo.xml')
            cmd += ['--fcd-output', out('fcd.xml'), '--fcd-output.geo', 'true', '--fcd-output.attributes', 'x,y,speed,waiting',
                    '--device.fcd.explicit', ','.join(sorted(users)), '--summary-output', out('summary.xml'),
                    '--additional-files', out('edgedata.add.xml')]
            (a.replay / f'{name}.command.json').write_text(json.dumps(cmd, indent=1) + '\n')
            with (a.replay / f'{name}.log').open('w') as log:
                subprocess.run(cmd, check=True, stdout=log, stderr=subprocess.STDOUT)
    variants, road_ids = {}, {}
    for name, rep in report['variants'].items():
        every = tripinfo(a.run / f'{name}.tripinfo.xml')
        assert same(every, tripinfo(a.replay / f'{name}.tripinfo.xml')), f'{name}: replay tripinfo differs from the measured run'
        trips = {k: v for k, v in every.items() if k in users}
        assert set(trips) == set(users) and sum(rep['counts'].values()) == len(users)
        cars, _ = kit.summarize(a.run / f'{name}.tripinfo.xml', set(every))  # every car, same rules as report.json
        variants[name] = dict(counts=rep['counts'], metrics=rep['completed_only_metrics'],
                              all=dict(counts=cars['counts'], metrics=cars['completed_only_metrics']),
                              **export(a.replay / f'{name}.fcd.xml', trips, users, manifest['end']),
                              totals=summary(a.replay / f'{name}.summary.xml', every, manifest['end'],
                                             [d for f in (f'{name}.rou.xml', 'background.rou.xml') if (a.run / 'inputs' / f).exists()
                                              for d in departs(a.run / 'inputs' / f)]),
                              roads=roads(a.replay / f'{name}.edges.xml', road_ids))

    loc = next(e.attrib for _, e in ET.iterparse(a.run / 'inputs/network.net.xml') if e.tag == 'location')
    proj, (ox, oy) = Proj(loc['projParameter']), map(float, loc['netOffset'].split(','))
    lonlat = lambda x, y: proj(x - ox, y - oy, inverse=True)
    signals = []  # SUMO's guessed traffic-light junctions (netconvert --tls.guess-signals), as lon/lat
    shapes = [None] * len(road_ids)  # first-lane shape of every road that appears in edgeData
    for _, e in ET.iterparse(a.run / 'inputs/network.net.xml'):
        if e.tag == 'junction':
            if e.get('type') == 'traffic_light':
                lon, lat = lonlat(float(e.get('x')), float(e.get('y')))
                signals += [round(lon * 1e5), round(lat * 1e5)]
            e.clear()
        elif e.tag == 'edge':
            if e.get('id') in road_ids:
                flat, px, py = [], 0, 0
                for p in e.find('lane').get('shape').split():
                    x, y = (round(v * 1e5) for v in lonlat(*map(float, p.split(','))))
                    flat += [x - px, y - py]
                    px, py = x, y
                shapes[road_ids[e.get('id')]] = flat
            e.clear()
        elif e.tag in ('connection', 'request'):
            e.clear()
    assert all(shapes), 'every edgeData road needs a network shape'

    pins = {}
    for u in scenario['trips']:
        for end in ('origin', 'destination'):
            p = pins.setdefault(u[f'{end}_name'], {'name': u[f'{end}_name'], 'lonlat': u[end], 'from': 0, 'to': 0})
            p['from' if end == 'origin' else 'to'] += 1

    data = {
        'run': a.run.name, 'replay': a.replay.name,
        'sumo': re.search(r'SUMO sumo (\S+)', execution['sumo_version']).group(1),
        'start': scenario['start'], 'admission': scenario['admission_seconds'], 'seed': manifest['seed'], 'end': manifest['end'], 'radius': manifest['radius'],
        'background': any(n.startswith('background') for n in manifest['inputs']),
        'scenario_sha256': manifest['inputs']['scenario.json'], 'network_sha256': manifest['inputs']['network.net.xml'],
        'osm_snapshot': json.loads((a.run.parent.parent / 'data/network/source.json').read_text())['osm_meta']['osm_base'],
        'event': scenario.get('event'), 'description': scenario['description'], 'period': PERIOD, 'road_shapes': shapes,
        'crowd': crowd(a.run / 'inputs/background.rou.xml'),
        # model labels on the ML variant's routes (data.decision from /plan), None for a baseline-only run
        'ml_models': sorted({r['decision'] for r in json.loads(ml.read_text())['routes']}) if (ml := a.run / 'inputs/ml.json').exists() else None,
        'placeholder': manifest.get('placeholder', False),  # ml variant = the baseline routes (kit.py build --placeholder)
        'users': len(users), 'signals': signals, 'pins': sorted(pins.values(), key=lambda p: p['name']), 'variants': variants,
    }
    a.out.write_text('// Generated by demo/sumo/view.py from SUMO output; do not edit.\nwindow.BASELINE = '
                     + json.dumps(data, separators=(',', ':')) + ';\n')
    print(f'{a.out}: {a.out.stat().st_size / 1e6:.1f} MB, {len(signals) // 2} signals, '
          + ', '.join(f'{k}: {len(v["vehicles"])} trips' for k, v in variants.items()))


def crowd(path):
    # Identical background vehicles (not app users) that the run added, if any.
    if not path.exists():
        return None
    departs = [float(v.get('depart')) for v in ET.parse(path).getroot().iter('vehicle')]
    return {'count': len(departs), 'first_depart': min(departs), 'last_depart': max(departs)}


def departs(path):
    return [float(v.get('depart')) for v in ET.parse(path).getroot().iter('vehicle')]


def summary(path, every, end, requested):
    # SUMO's per-second network totals for ALL vehicles: on the road, halting (< 0.1 m/s), waiting to be inserted,
    # and arrived so far.
    rows = [(round(float(e.get('time'))), int(e.get('running')), int(e.get('halting')), int(e.get('waiting')), int(e.get('arrived')))
            for _, e in ET.iterparse(path) if e.tag == 'step']
    assert [r[0] for r in rows] == list(range(end)), 'summary must have one row per simulated second'
    ran = sum(min(end, float(t['arrival']) if float(t['arrival']) >= 0 else end) - float(t['depart'])
              for t in every.values() if float(t['depart']) >= 0)
    assert sum(r[1] for r in rows) == round(ran), 'summary running must add up to tripinfo time on the road'
    assert rows[-1][4] == sum(float(t['arrival']) >= 0 for t in every.values()), 'summary arrived must match tripinfo'
    # Every car whose requested departure has come is exactly one of: on the road, can't pull out yet, arrived.
    requested = sorted(requested)
    assert len(requested) == len(every) and all(
        r[1] + r[3] + r[4] == bisect.bisect_right(requested, r[0]) for r in rows), 'summary must account for every requested car'
    return {k: [r[i] for r in rows] for i, k in ((1, 'running'), (2, 'halting'), (3, 'waiting'), (4, 'arrived'))}


def roads(path, road_ids):
    # Per interval: [road index, SUMO speedRelative (mean speed / speed limit) in 0.05 steps, mean cars on it x10]
    # for roads that averaged at least 0.5 cars.
    frames = []
    for _, e in ET.iterparse(path):
        if e.tag == 'interval':
            period, f = float(e.get('end')) - float(e.get('begin')), []
            for r in e.iter('edge'):
                cars = float(r.get('sampledSeconds')) / period
                if cars >= 0.5:
                    f += [road_ids.setdefault(r.get('id'), len(road_ids)), round(float(r.get('speedRelative')) * 20), round(cars * 10)]
            frames.append(f)
            e.clear()
    return frames


def export(fcd, trips, users, end):
    samples = {}  # id -> [(t, lon, lat, speed, waiting)]
    for _, e in ET.iterparse(fcd):
        if e.tag == 'timestep':
            t = round(float(e.get('time')))
            for v in e.iter('vehicle'):
                samples.setdefault(v.get('id'), []).append(
                    (t, float(v.get('x')), float(v.get('y')), float(v.get('speed')), float(v.get('waiting'))))
            e.clear()
    vehicles = []
    for vid, ti in sorted(trips.items()):
        depart, arrival, u = round(float(ti['depart'])), round(float(ti['arrival'])), users[vid]
        if depart < 0:  # never got onto the road before the horizon
            assert vid not in samples
            vehicles.append([vid, u['depart'], None, False, u['origin_name'], u['destination_name'], []])
            continue
        s = samples[vid]
        assert [p[0] for p in s] == list(range(depart, arrival if arrival >= 0 else end)), f'{vid}: FCD does not cover depart..arrival'
        # SUMO's waiting counter grows each second a car halts (< 0.1 m/s, not at insertion); tripinfo sums those seconds.
        assert sum(p[4] > 0 for p in s) == round(float(ti['waitingTime'])), f'{vid}: waiting seconds != waitingTime'
        # One row per simulated second: lon, lat in 1e-5 degrees (~1 m, delta-coded), then 0 if SUMO counted the car
        # as waiting this second, else 1 + speed in 0.1 m/s.
        # A run of k identical rows [0, 0, 0] (still waiting, same spot) is stored once as [0, 0, -k].
        flat, px, py = [], 0, 0
        for _, lon, lat, v, w in s:
            x, y = round(lon * 1e5), round(lat * 1e5)
            row = [x - px, y - py, 0 if w > 0 else 1 + round(v * 10)]
            if row == [0, 0, 0] and flat[-3:-1] == [0, 0] and flat[-1] <= 0 and len(flat) >= 3:
                flat[-1] -= 1 if flat[-1] < 0 else 2  # [0,0,0] then [0,0,0] -> [0,0,-2]; [0,0,-k] -> [0,0,-k-1]
            else:
                flat += row
            px, py = x, y
        vehicles.append([vid, u['depart'], depart, arrival >= 0, u['origin_name'], u['destination_name'], flat])
    return {'vehicles': vehicles}


if __name__ == '__main__':
    main()
