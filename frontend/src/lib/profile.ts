/**
 * Geometry for a Vision Lab profile chart: one estimator's per-row signal along
 * the gauge. The vertical axis is the gauge in metres (high stage at the top,
 * as on the staff), the horizontal axis is the signal value.
 */

export interface Box {
  width: number;
  height: number;
  pad: { top: number; right: number; bottom: number; left: number };
}

export interface ProfileGeometry {
  /** Signal value -> x pixel. */
  x: (v: number) => number;
  /** Gauge stage in metres -> y pixel. */
  y: (m: number) => number;
  /** SVG path through every row with a finite value. */
  path: string;
  /** Metre ticks inside the axis range. */
  ticks: number[];
  /** Highest and lowest stage on the axis. */
  top: number;
  bottom: number;
  /** Signal range shown. */
  lo: number;
  hi: number;
}

/** A "nice" tick step (1, 2, 2.5 or 5 x 10^k) giving about `count` intervals. */
export function niceStep(range: number, count = 4): number {
  if (!(range > 0) || !Number.isFinite(range)) return 1;
  const raw = range / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  for (const f of [1, 2, 2.5, 5, 10]) {
    if (f * mag >= raw) return f * mag;
  }
  return 10 * mag;
}

export function metreTicks(lo: number, hi: number, count = 4): number[] {
  const step = niceStep(hi - lo, count);
  const out: number[] = [];
  for (let v = Math.ceil(lo / step - 1e-9) * step; v <= hi + 1e-9; v += step) out.push(Math.round(v * 1000) / 1000);
  return out;
}

export function profileGeometry(axisM: number[], signal: number[], box: Box): ProfileGeometry | null {
  const n = Math.min(axisM.length, signal.length);
  if (n < 2) return null;
  const finiteAxis = axisM.slice(0, n).filter(Number.isFinite);
  const finiteSig = signal.slice(0, n).filter(Number.isFinite);
  if (finiteAxis.length < 2 || finiteSig.length < 2) return null;
  const top = Math.max(...finiteAxis);
  const bottom = Math.min(...finiteAxis);
  if (top === bottom) return null;
  let lo = Math.min(...finiteSig);
  let hi = Math.max(...finiteSig);
  if (hi === lo) {
    lo -= 1;
    hi += 1;
  }
  const { pad } = box;
  const innerW = Math.max(1, box.width - pad.left - pad.right);
  const innerH = Math.max(1, box.height - pad.top - pad.bottom);
  const x = (v: number) => pad.left + ((v - lo) / (hi - lo)) * innerW;
  const y = (m: number) => pad.top + ((top - m) / (top - bottom)) * innerH;
  let path = '';
  let pen = false;
  for (let i = 0; i < n; i++) {
    const v = signal[i];
    const m = axisM[i];
    if (!Number.isFinite(v) || !Number.isFinite(m)) {
      pen = false;
      continue;
    }
    path += `${pen ? 'L' : 'M'}${x(v).toFixed(1)},${y(m).toFixed(1)}`;
    pen = true;
  }
  return { x, y, path, ticks: metreTicks(bottom, top, Math.max(3, Math.round(innerH / 50))), top, bottom, lo, hi };
}

/** Row whose stage is closest to `m` (for hover readouts). */
export function nearestRow(axisM: number[], m: number): number {
  let best = 0;
  for (let i = 1; i < axisM.length; i++) {
    if (Math.abs(axisM[i] - m) < Math.abs(axisM[best] - m)) best = i;
  }
  return best;
}
