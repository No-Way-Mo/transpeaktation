"""footage/tour.log -> footage/marks.json: tour beats and taps as seconds into footage/sim.mov. Run by record.sh.

The tour logs wall-clock times; the recording's clock starts at its first frame, which comes a few seconds after
`recordVideo` says it started (the simulator is still booting). That offset is measured, not guessed: it's the shift
that lines the taps up with the screen changes they cause.
"""
import json
import re
import subprocess
import sys

log = open('footage/tour.log').read()
t0 = float(open('footage/t0').read())
beats = {m[1]: float(m[2]) - t0 for m in re.finditer(r'^TOUR ([a-z-]+) ([0-9.]+)$', log, re.M)}
taps = [(float(m[3]) - t0, float(m[1]), float(m[2])) for m in re.finditer(r'^TOUR-TAP ([0-9.]+) ([0-9.]+) ([0-9.]+) [0-9.]+$', log, re.M)]

info = subprocess.run(['ffmpeg', '-v', 'info', '-i', 'footage/sim.mov', '-vf', "scale=64:-2,select='gt(scene,0.015)',showinfo",
                       '-f', 'null', '-'], capture_output=True, text=True).stderr
changes = [float(x) for x in re.findall(r'pts_time:([0-9.]+)', info)]


def lag(t, d):
    """How long after the tap (shifted by d) the screen changed, if it did within half a second."""
    after = [c - (t - d) for c in changes if 0 <= c - (t - d) <= 0.5]
    return min(after) if after else None


# Most taps followed by a change within half a second; then the median lag moves the taps onto their changes.
best = max((sum(lag(t, d / 50) is not None for t, _, _ in taps), -d / 50) for d in range(0, 751))
d = -best[1]
lags = sorted(x for t, _, _ in taps if (x := lag(t, d)) is not None)
offset = d - lags[len(lags) // 2] + 0.1   # the finger lands a beat before the screen reacts
print(f'recording offset {offset:.2f} s ({best[0]} of {len(taps)} taps matched)', file=sys.stderr)
if best[0] < len(taps) // 2:
    sys.exit('could not line taps up with the recording; check footage/sim.mov')

json.dump({'offset': round(offset, 2), 'beats': {k: round(v - offset, 2) for k, v in beats.items()},
           'taps': [[round(t - offset, 2), x, y] for t, x, y in taps]}, open('footage/marks.json', 'w'), indent=1)
