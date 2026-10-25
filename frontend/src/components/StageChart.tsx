import { useCallback, useId, useMemo, useRef, useState, type PointerEvent } from 'react';
import type { SeriesPoint } from '../api';
import { useI18n } from '../i18n';
import { fmtNum, fmtTime } from '../lib/format';

const H = 240;
const PAD = { top: 16, right: 12, bottom: 28, left: 44 };

/** Track the rendered width so SVG text stays at its real pixel size on phones. */
function useWidth(fallback: number) {
  const [width, setWidth] = useState(fallback);
  const observer = useRef<ResizeObserver | null>(null);
  const ref = useCallback((el: HTMLElement | null) => {
    observer.current?.disconnect();
    observer.current = null;
    if (!el || typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver((entries) => {
      const w = Math.round(entries[0]?.contentRect.width ?? 0);
      if (w > 0) setWidth(Math.max(300, w));
    });
    ro.observe(el);
    observer.current = ro;
  }, []);
  return [ref, width] as const;
}

/**
 * River stage over time as inline SVG: one line, a ±sigma band, dashed warning
 * and danger lines (labelled, not colour-only), a hover readout, and a visually
 * hidden summary + table as the text alternative.
 */
export default function StageChart({
  series,
  warning,
  danger,
}: {
  series: SeriesPoint[];
  warning?: number | null;
  danger?: number | null;
}) {
  const { t } = useI18n();
  const ids = useId();
  const [hover, setHover] = useState<number | null>(null);
  const [figRef, W] = useWidth(640);

  const points = useMemo(
    // Readings the agent rejected (bad frame, disagreement, camera moved) are not plotted.
    () => series.filter((p) => typeof p.stage_m === 'number' && Number.isFinite(p.stage_m) && p.usable !== false),
    [series],
  );

  const geom = useMemo(() => {
    if (points.length === 0) return null;
    const times = points.map((p, i) => {
      const ms = Date.parse(p.t);
      return Number.isNaN(ms) ? i : ms;
    });
    const t0 = Math.min(...times);
    const t1 = Math.max(...times);
    const values = points.flatMap((p) => [p.stage_m - (p.sigma_m ?? 0), p.stage_m + (p.sigma_m ?? 0)]);
    const extras = [warning, danger].filter((v): v is number => typeof v === 'number');
    let lo = Math.min(...values, ...extras);
    let hi = Math.max(...values, ...extras);
    if (hi - lo < 0.5) {
      const mid = (hi + lo) / 2;
      lo = mid - 0.25;
      hi = mid + 0.25;
    }
    const pad = (hi - lo) * 0.08;
    lo -= pad;
    hi += pad;
    const x = (ms: number) =>
      PAD.left + (t1 === t0 ? (W - PAD.left - PAD.right) / 2 : ((ms - t0) / (t1 - t0)) * (W - PAD.left - PAD.right));
    const y = (v: number) => PAD.top + (1 - (v - lo) / (hi - lo)) * (H - PAD.top - PAD.bottom);
    const xs = times.map(x);
    const line = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${xs[i].toFixed(1)},${y(p.stage_m).toFixed(1)}`).join(' ');
    const upper = points.map((p, i) => `${xs[i].toFixed(1)},${y(p.stage_m + (p.sigma_m ?? 0)).toFixed(1)}`);
    const lower = points
      .map((p, i) => `${xs[i].toFixed(1)},${y(p.stage_m - (p.sigma_m ?? 0)).toFixed(1)}`)
      .reverse();
    const band = `${upper.join(' ')} ${lower.join(' ')}`;
    const ticks = Array.from({ length: 5 }, (_, i) => lo + ((hi - lo) * i) / 4);
    return { x, y, xs, line, band, ticks, lo, hi };
  }, [points, warning, danger, W]);

  if (!geom) {
    return (
      <figure className="ns-chart" ref={figRef}>
        <p className="ns-muted">{t('live.chartEmpty')}</p>
      </figure>
    );
  }

  const stages = points.map((p) => p.stage_m);
  const last = points[points.length - 1];
  const summary = t('live.chartSummary', {
    n: points.length,
    min: fmtNum(Math.min(...stages)),
    max: fmtNum(Math.max(...stages)),
    last: fmtNum(last.stage_m),
    warn: fmtNum(warning),
    danger: fmtNum(danger),
  });

  const onMove = (event: PointerEvent<SVGRectElement>) => {
    const svg = event.currentTarget.ownerSVGElement;
    if (!svg) return;
    const rect = svg.getBoundingClientRect();
    if (rect.width === 0) return;
    const sx = ((event.clientX - rect.left) / rect.width) * W;
    let best = 0;
    for (let i = 1; i < geom.xs.length; i++) {
      if (Math.abs(geom.xs[i] - sx) < Math.abs(geom.xs[best] - sx)) best = i;
    }
    setHover(best);
  };

  const hp = hover !== null ? points[hover] : null;
  const threshold = (value: number | null | undefined, label: string, cls: string) => {
    if (typeof value !== 'number' || value < geom.lo || value > geom.hi) return null;
    const yy = geom.y(value);
    return (
      <g className={cls}>
        <line x1={PAD.left} x2={W - PAD.right} y1={yy} y2={yy} strokeDasharray="6 4" strokeWidth={1.5} />
        <text x={W - PAD.right} y={yy - 5} textAnchor="end" className="ns-chart__thresh-label">
          {label} {fmtNum(value, 1)}
        </text>
      </g>
    );
  };

  return (
    <figure className="ns-chart" ref={figRef}>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="ns-chart__svg"
        role="img"
        aria-labelledby={`${ids}-title`}
        aria-describedby={`${ids}-desc`}
      >
        <title id={`${ids}-title`}>{t('live.chart')}</title>
        <desc id={`${ids}-desc`}>{summary}</desc>
        {geom.ticks.map((v) => (
          <g key={v} className="ns-chart__grid">
            <line x1={PAD.left} x2={W - PAD.right} y1={geom.y(v)} y2={geom.y(v)} />
            <text x={PAD.left - 6} y={geom.y(v) + 4} textAnchor="end">
              {v.toFixed(1)}
            </text>
          </g>
        ))}
        <text x={PAD.left} y={H - 8} className="ns-chart__axis">
          {fmtTime(points[0].t)}
        </text>
        <text x={W - PAD.right} y={H - 8} textAnchor="end" className="ns-chart__axis">
          {fmtTime(last.t)}
        </text>
        {threshold(warning, t('live.warning'), 'ns-chart__warn')}
        {threshold(danger, t('live.danger'), 'ns-chart__danger')}
        <polygon points={geom.band} className="ns-chart__band" />
        <path d={geom.line} className="ns-chart__line" />
        <circle cx={geom.xs[geom.xs.length - 1]} cy={geom.y(last.stage_m)} r={5} className="ns-chart__dot" />
        {hp && hover !== null && (
          <g className="ns-chart__hover" aria-hidden="true">
            <line x1={geom.xs[hover]} x2={geom.xs[hover]} y1={PAD.top} y2={H - PAD.bottom} />
            <circle cx={geom.xs[hover]} cy={geom.y(hp.stage_m)} r={5} />
            <g transform={`translate(${Math.min(geom.xs[hover] + 8, W - PAD.right - 120)},${PAD.top + 4})`}>
              <rect width={120} height={38} rx={4} />
              <text x={8} y={16}>{fmtTime(hp.t)}</text>
              <text x={8} y={31} className="ns-chart__hover-value">
                {fmtNum(hp.stage_m)} m{hp.sigma_m ? ` ± ${fmtNum(hp.sigma_m)}` : ''}
              </text>
            </g>
          </g>
        )}
        <rect
          x={PAD.left}
          y={PAD.top}
          width={W - PAD.left - PAD.right}
          height={H - PAD.top - PAD.bottom}
          fill="transparent"
          onPointerMove={onMove}
          onPointerLeave={() => setHover(null)}
        />
      </svg>
      <figcaption className="sr-only">
        <p>{summary}</p>
        <table>
          <caption>{t('live.chart')}</caption>
          <thead>
            <tr>
              <th scope="col">{t('common.time')}</th>
              <th scope="col">{t('live.stageCol')}</th>
            </tr>
          </thead>
          <tbody>
            {points.slice(-12).map((p, i) => (
              <tr key={`${p.t}-${i}`}>
                <td>{fmtTime(p.t)}</td>
                <td>
                  {fmtNum(p.stage_m)}
                  {p.sigma_m ? ` ± ${fmtNum(p.sigma_m)}` : ''}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </figcaption>
    </figure>
  );
}
