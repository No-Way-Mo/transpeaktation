// Pure replay math over demo/baseline.data.js, shared by index.html and baseline.html.
// No DOM access, so check.mjs can run it in Node.
const REPLAY = (() => {
  // App-user rows are [id, requested second, first sample second (null = never got on the road), arrived, origin,
  // destination, flat], flat = per second [dlon, dlat, code]: lon/lat in 1e-5 degrees, delta-coded; code 0 = SUMO
  // counted the car as waiting this second, else 1 + speed in 0.1 m/s; [0, 0, -k] = k waiting seconds at the same spot.
  function decode(rows) {
    return rows.map(([id, req, t0, arrived, from, to, f]) => {
      let n = 0;
      for (let j = 2; j < f.length; j += 3) n += f[j] < 0 ? -f[j] : 1;
      const lon = new Float64Array(n), lat = new Float64Array(n), spd = new Uint16Array(n), halt = new Uint8Array(n);
      for (let j = 0, i = 0, x = 0, y = 0; j < f.length; j += 3) {
        x += f[j]; y += f[j + 1];
        const code = f[j + 2];
        for (let r = code < 0 ? -code : 1; r > 0; r--, i++) {
          lon[i] = x / 1e5; lat[i] = y / 1e5; halt[i] = code <= 0 ? 1 : 0; spd[i] = code > 0 ? code - 1 : 0;
        }
      }
      const start = t0 ?? Infinity;
      return { id, req, t0: start, t1: start + n, arrived, from, to, lon, lat, spd, halt };
    });
  }
  const waited = (c, i) => c.halt[i] === 1;
  // Per simulated second for the tracked cars: on the road, waiting, cumulative requests and arrivals
  // (SUMO tripinfo arrival = first second a car is gone).
  function series(cars, end) {
    const road = new Uint16Array(end), wait = new Uint16Array(end), req = new Uint16Array(end + 1), arr = new Uint16Array(end + 1);
    for (const c of cars) {
      for (let i = 0; i < c.spd.length; i++) { road[c.t0 + i]++; wait[c.t0 + i] += c.halt[i]; }
      req[c.req]++; if (c.arrived) arr[c.t1]++;
    }
    const roadSum = new Float64Array(end + 1), waitSum = new Float64Array(end + 1);
    for (let t = 0; t < end; t++) {
      roadSum[t + 1] = roadSum[t] + road[t]; waitSum[t + 1] = waitSum[t] + wait[t];
      req[t + 1] += req[t]; arr[t + 1] += arr[t];
    }
    const done = cars.filter(c => c.arrived);
    return { road, wait, req, arr, roadSum, waitSum, lastArrival: done.length ? Math.max(...done.map(c => c.t1)) : null };
  }
  // Means over `size`-second steps of SUMO's per-second totals for every vehicle.
  function bins(totals, end, size) {
    const m = Math.ceil(end / size), out = { size, moving: new Float64Array(m), stopped: new Float64Array(m), enter: new Float64Array(m) };
    for (let t = 0; t < end; t++) {
      const i = Math.floor(t / size), w = Math.min(size, end - i * size);
      out.stopped[i] += totals.halting[t] / w; out.moving[i] += (totals.running[t] - totals.halting[t]) / w; out.enter[i] += totals.waiting[t] / w;
    }
    return out;
  }
  // Where every car is at second t; the five groups always add up to all cars.
  const allAt = (tt, t, total) => ({ moving: tt.running[t] - tt.halting[t], stopped: tt.halting[t], enter: tt.waiting[t],
    arrived: tt.arrived[t], later: total - tt.running[t] - tt.waiting[t] - tt.arrived[t] });
  return { decode, series, waited, bins, allAt };
})();
