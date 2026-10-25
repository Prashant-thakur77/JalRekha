import { useCallback, useMemo, useRef, useState, type PointerEvent } from 'react';
import type { LabEstimator } from '../api';
import { useVisionText, type VisionKey } from '../content/vision';
import { fmtNum } from '../lib/format';
import { nearestRow, profileGeometry } from '../lib/profile';

const H = 300;
const PAD = { top: 14, right: 12, bottom: 14, left: 44 };

/** Track the rendered width so SVG text stays at its real pixel size. */
function useWidth(fallback: number) {
  const [width, setWidth] = useState(fallback);
  const observer = useRef<ResizeObserver | null>(null);
  const ref = useCallback((el: HTMLElement | null) => {
    observer.current?.disconnect();
    observer.current = null;
    if (!el || typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver((entries) => {
      const w = Math.round(entries[0]?.contentRect.width ?? 0);
      if (w > 0) setWidth(Math.max(200, w));
    });
    ro.observe(el);
    observer.current = ro;
  }, []);
  return [ref, width] as const;
}

/**
 * One estimator's per-row signal along the gauge (small multiple). Metres run
 * down the left like the staff gauge; a lime mark shows the chosen waterline
 * and a dashed line the fused reading shared by all three charts.
 */
export default function ProfileChart({
  estimator,
  axisM,
  fusedM,
}: {
  estimator: LabEstimator;
  axisM: number[];
  fusedM: number | null;
}) {
  const t = useVisionText();
  const [figRef, W] = useWidth(320);
  const [hover, setHover] = useState<number | null>(null);
  const signal = estimator.signal;
  const geom = useMemo(
    () => (signal ? profileGeometry(axisM, signal, { width: W, height: H, pad: PAD }) : null),
    [axisM, signal, W],
  );
  const name = t(`e.${estimator.name}` as VisionKey);

  if (!signal || !geom) {
    return (
      <figure className="ns-profile" ref={figRef}>
        <div className="ns-profile__empty">
          <p>{t('noProfile')}</p>
        </div>
      </figure>
    );
  }

  const stage = estimator.stage_m;
  const label = t('chartLabel', {
    name,
    top: fmtNum(geom.top),
    bottom: fmtNum(geom.bottom),
    v: fmtNum(stage),
    f: fmtNum(fusedM),
  });

  const onMove = (event: PointerEvent<SVGRectElement>) => {
    const svg = event.currentTarget.ownerSVGElement;
    if (!svg) return;
    const rect = svg.getBoundingClientRect();
    if (rect.height === 0) return;
    const sy = ((event.clientY - rect.top) / rect.height) * H;
    const m = geom.top - ((sy - PAD.top) / (H - PAD.top - PAD.bottom)) * (geom.top - geom.bottom);
    setHover(nearestRow(axisM, m));
  };

  const inRange = (m: number | null): m is number => typeof m === 'number' && m <= geom.top && m >= geom.bottom;
  const right = W - PAD.right;
  const hv = hover !== null ? signal[hover] : null;

  return (
    <figure className="ns-profile" ref={figRef}>
      <svg className="ns-chart__svg ns-profile__svg" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label}>
        <g className="ns-chart__grid">
          {geom.ticks.map((m) => (
            <g key={m}>
              <line x1={PAD.left} x2={right} y1={geom.y(m)} y2={geom.y(m)} />
              <text x={PAD.left - 6} y={geom.y(m) + 4} textAnchor="end">
                {fmtNum(m, 1)}
              </text>
            </g>
          ))}
        </g>
        <path className="ns-profile__line" d={geom.path} />
        {inRange(fusedM) && (
          <g className="ns-profile__fused">
            <line x1={PAD.left} x2={right} y1={geom.y(fusedM)} y2={geom.y(fusedM)} />
          </g>
        )}
        {inRange(stage) && estimator.row !== null && (
          <g className="ns-profile__mark" data-testid={`mark-${estimator.name}`}>
            <line x1={PAD.left} x2={right} y1={geom.y(stage)} y2={geom.y(stage)} />
            <circle cx={geom.x(signal[Math.round(estimator.row)] ?? geom.lo)} cy={geom.y(stage)} r={5} />
            <text x={right - 2} y={geom.y(stage) < PAD.top + 18 ? geom.y(stage) + 15 : geom.y(stage) - 7} textAnchor="end">
              {t('waterline', { v: fmtNum(stage) })}
            </text>
          </g>
        )}
        {hover !== null && typeof hv === 'number' && (
          <g className="ns-chart__hover" aria-hidden="true">
            <line x1={PAD.left} x2={right} y1={geom.y(axisM[hover])} y2={geom.y(axisM[hover])} />
            <circle cx={geom.x(hv)} cy={geom.y(axisM[hover])} r={4} />
            <text x={PAD.left + 4} y={Math.max(PAD.top + 10, geom.y(axisM[hover]) - 6)}>
              {t('hoverRow', { r: hover, m: fmtNum(axisM[hover]) })} · {fmtNum(hv)}
            </text>
          </g>
        )}
        <rect
          x={PAD.left}
          y={PAD.top}
          width={Math.max(1, right - PAD.left)}
          height={H - PAD.top - PAD.bottom}
          fill="transparent"
          onPointerMove={onMove}
          onPointerLeave={() => setHover(null)}
        />
      </svg>
      <figcaption className="ns-profile__axis">
        <span>{t('axis')}</span>
        <span>
          <span className="ns-profile__key ns-profile__key--mark" aria-hidden="true" /> {t('waterline', { v: '' }).trim()}
          <span className="ns-profile__key ns-profile__key--fused" aria-hidden="true" /> {t('fusedLine', { v: fmtNum(fusedM) })} m
        </span>
      </figcaption>
    </figure>
  );
}
