"""Ask a running api/ (with ML_URL set) for every scenario trip's route and write kit.py's `build --ml` input.

    demo/sumo/.venv/bin/python demo/sumo/ml_routes.py --demand demo/sumo/data/demand-v3-seed42 \
      --api http://localhost:8000 --out demo/sumo/data/ml-v3-<model>

Calls `GET /plan?...&replay=true` for each line of <demand>/requests.jsonl (replay calls log no trips) and appends
every raw answer to <out>/responses.jsonl, so an interrupted export resumes where it stopped instead of paying
for the same calls twice. Writes <out>/ml.json only when every trip has a route decided by ml/: a heuristic
fallback (`data.decision` not starting with `ml:`) is reported and never relabeled.
"""
import argparse, json, sys, urllib.request
from pathlib import Path

import kit


def route(answer):
    # The picked route's final road geometry, [lat, lon] (contracts/route_decision.md), and who picked it.
    return answer['data']['decision'], answer['routes'][answer['plan']['best']]['coords']


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--demand', required=True, type=Path, help='kit.py scenario output (scenario.json + requests.jsonl)')
    ap.add_argument('--api', default='http://localhost:8000')
    ap.add_argument('--out', required=True, type=Path)
    ap.add_argument('--timeout', type=float, default=60)
    a = ap.parse_args()

    scenario = kit.load_scenario(a.demand / 'scenario.json')
    requests = [json.loads(line) for line in (a.demand / 'requests.jsonl').read_text().splitlines()]
    a.out.mkdir(parents=True, exist_ok=True)
    log = a.out / 'responses.jsonl'
    got = {r['trip_id']: r['answer'] for r in map(json.loads, log.read_text().splitlines())} if log.exists() else {}
    # ponytail: one request at a time (~1000 calls, each up to the 8 s ml/ timeout); add a thread pool if too slow.
    with log.open('a') as f:
        for i, r in enumerate(requests):
            if r['trip_id'] in got:
                continue
            with urllib.request.urlopen(a.api.rstrip('/') + r['path'], timeout=a.timeout) as res:
                got[r['trip_id']] = json.load(res)
            f.write(json.dumps({'trip_id': r['trip_id'], 'answer': got[r['trip_id']]}) + '\n')
            f.flush()
            print(f"{i + 1}/{len(requests)} {r['trip_id']}: {got[r['trip_id']]['data']['decision']}", file=sys.stderr)

    rows, fallback = [], []
    for t in scenario['trips']:
        decision, coords = route(got[t['id']])
        if not decision.startswith('ml:'):
            fallback.append(f"{t['id']}: {decision}")
        rows.append(dict(trip_id=t['id'], depart_at=t['depart_at'], decision=decision, coords=coords))
    if fallback:
        sys.exit(f'{len(fallback)} of {len(rows)} trips were not routed by ml/, e.g. {fallback[0]}. '
                 f'Fix ML_URL / ml/ and delete those lines from {log} to ask again.')
    kit.write_json(a.out / 'ml.json', dict(coordinate_order='lat,lon', scenario_sha256=kit.digest(a.demand / 'scenario.json'),
                                           api=a.api, responses='responses.jsonl', routes=rows))
    print(f"{a.out / 'ml.json'}: {len(rows)} routes by {sorted({r['decision'] for r in rows})}")


if __name__ == '__main__':
    main()
