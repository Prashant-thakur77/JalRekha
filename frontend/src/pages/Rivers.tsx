import { useCallback, useEffect, useId, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from 'react';
import { Timer } from 'lucide-react';
import {
  errorMessage,
  getAgentState,
  getEta,
  getRiver,
  getRivers,
  type AgentState,
  type EtaResult,
  type RiverGraph,
  type RiverNode,
  type RiverSummary,
} from '../api';
import { useI18n } from '../i18n';
import { fmtHours, fmtNum } from '../lib/format';
import { layoutRiver } from '../lib/riverLayout';
import { Chip, PageHeader, StateNotice } from '../components/ui';

type LevelStatus = 'unknown' | 'normal' | 'warning' | 'danger';

function levelFor(node: RiverNode, states: AgentState[]): { status: LevelStatus; stage: number | null } {
  const st = states.find((s) => (s.node_id && s.node_id === node.id) || (node.site_id && s.site_id === node.site_id));
  const stage =
    typeof node.live?.stage_m === 'number'
      ? node.live.stage_m
      : typeof st?.last_stage_m === 'number'
        ? st.last_stage_m
        : null;
  if (stage === null) return { status: 'unknown', stage };
  if (typeof node.danger_m === 'number' && stage >= node.danger_m) return { status: 'danger', stage };
  if (typeof node.warning_m === 'number' && stage >= node.warning_m) return { status: 'warning', stage };
  return { status: 'normal', stage };
}

function Schematic({
  graph,
  states,
  eta,
  onPick,
}: {
  graph: RiverGraph;
  states: AgentState[];
  eta: EtaResult | null;
  onPick: (nodeId: string) => void;
}) {
  const { t, td } = useI18n();
  const ids = useId();
  const [width, setWidth] = useState(480);
  const observer = useRef<ResizeObserver | null>(null);
  const figRef = useCallback((el: HTMLElement | null) => {
    observer.current?.disconnect();
    observer.current = null;
    if (!el || typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver((entries) => {
      const w = Math.round(entries[0]?.contentRect.width ?? 0);
      if (w > 0) setWidth(Math.min(600, Math.max(280, w)));
    });
    ro.observe(el);
    observer.current = ro;
  }, []);
  const layout = useMemo(() => layoutRiver(graph, width), [graph, width]);
  const etaById = useMemo(
    () => Object.fromEntries((eta?.downstream ?? []).map((d) => [d.node_id, d])),
    [eta],
  );
  const statusText: Record<LevelStatus, string> = {
    unknown: t('rivers.unknown'),
    normal: t('rivers.normal'),
    warning: t('rivers.warning'),
    danger: t('rivers.danger'),
  };

  const onKey = (event: KeyboardEvent<SVGGElement>, id: string) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      onPick(id);
    }
  };

  return (
    <figure className="ns-river" ref={figRef}>
      <svg
        viewBox={`0 0 ${layout.width} ${layout.height}`}
        className="ns-river__svg"
        aria-labelledby={`${ids}-t`}
        role="group"
      >
        <title id={`${ids}-t`}>{t('rivers.schematic', { name: graph.name })}</title>
        <defs>
          <marker id={`${ids}-arrow`} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10 z" className="ns-river__arrow" />
          </marker>
        </defs>

        {layout.borders.map((b) => (
          <g key={`${b.above}-${b.below}`} className="ns-river__border" aria-hidden="true">
            <line x1={8} x2={layout.width - 8} y1={b.y} y2={b.y} strokeDasharray="8 6" />
            <text x={layout.width - 8} y={b.y - 8} textAnchor="end">▲ {td(`country.${b.above}`, b.above)}</text>
            <text x={layout.width - 8} y={b.y + 18} textAnchor="end">▼ {td(`country.${b.below}`, b.below)}</text>
          </g>
        ))}

        {(graph.edges ?? []).map((e) => {
          const a = layout.placed[e.from];
          const b = layout.placed[e.to];
          if (!a || !b) return null;
          const dx = b.x - a.x;
          const dy = b.y - a.y;
          const len = Math.hypot(dx, dy) || 1;
          const r = 20;
          const x1 = a.x + (dx / len) * r;
          const y1 = a.y + (dy / len) * r;
          const x2 = b.x - (dx / len) * r;
          const y2 = b.y - (dy / len) * r;
          const onPath = Boolean(eta && etaById[e.to] && (e.from === eta.from_node || etaById[e.from]));
          const tt = e.travel_time_h;
          // Label sits on the edge (with a halo); lower when the source row has labels below it.
          const frac = a.shared ? 0.62 : 0.5;
          // Offset to the left of the edge so the label never sits on the border line.
          const lx = a.x + dx * frac - 10;
          const ly = a.y + dy * frac - 6;
          return (
            <g key={`${e.from}-${e.to}`} className={`ns-river__edge${onPath ? ' ns-river__edge--hot' : ''}`}>
              <line x1={x1} x2={x2} y1={y1} y2={y2} markerEnd={`url(#${ids}-arrow)`} />
              {tt && (
                <text x={lx} y={ly} textAnchor="end" className="ns-river__edge-label">
                  {fmtHours(tt.min)}–{fmtHours(tt.max)} h
                </text>
              )}
            </g>
          );
        })}

        {layout.order.map((id) => {
          const p = layout.placed[id];
          if (!p) return null;
          const { status, stage } = levelFor(p.node, states);
          const hit = etaById[id];
          const isSource = eta?.from_node === id;
          const lx = p.shared ? 0 : 26;
          const anchor = p.shared ? 'middle' : 'start';
          const ny = p.shared ? [30, 44, 58] : [-2, 14, 30];
          const label = `${t('rivers.computeFrom', { name: p.node.name })}. ${statusText[status]}${stage !== null ? `, ${t('rivers.level', { v: fmtNum(stage) })}` : ''}${hit ? `. ETA ${t('common.etaBand', { min: fmtHours(hit.eta_h.min), max: fmtHours(hit.eta_h.max), typ: fmtHours(hit.eta_h.typ) })}` : ''}`;
          return (
            <g
              key={id}
              className={`ns-river__node ns-river__node--${status}${hit ? ' ns-river__node--hit' : ''}${isSource ? ' ns-river__node--source' : ''}`}
              transform={`translate(${p.x},${p.y})`}
              role="button"
              tabIndex={0}
              aria-label={label}
              onClick={() => onPick(id)}
              onKeyDown={(event) => onKey(event, id)}
            >
              <circle r={24} className="ns-river__hit" />
              {(hit || isSource) && <circle r={20} className="ns-river__ring" />}
              <circle r={13} className="ns-river__dot" />
              <text y={4} textAnchor="middle" className="ns-river__kind" aria-hidden="true">
                {(p.node.kind ?? '?').charAt(0).toUpperCase()}
              </text>
              <text x={lx} y={ny[0]} textAnchor={anchor} className="ns-river__name">
                {p.node.name}
              </text>
              <text x={lx} y={ny[1]} textAnchor={anchor} className="ns-river__sub">
                {stage !== null ? `${fmtNum(stage)} m · ` : ''}
                {td(`rivers.kind.${p.node.kind}`, p.node.kind)}
                {p.node.admin_unit ? ` · ${p.node.admin_unit}` : ''}
              </text>
              {hit && (
                <text x={lx} y={ny[2]} textAnchor={anchor} className="ns-river__eta">
                  ≈ {fmtHours(hit.eta_h.typ)} h ({fmtHours(hit.eta_h.min)}–{fmtHours(hit.eta_h.max)})
                </text>
              )}
            </g>
          );
        })}
      </svg>
      <figcaption className="ns-legend" aria-label={t('rivers.legend')}>
        {(['normal', 'warning', 'danger', 'unknown'] as LevelStatus[]).map((s) => (
          <span key={s} className="ns-legend__item">
            <span className={`ns-legend__swatch ns-legend__swatch--${s}`} aria-hidden="true" /> {statusText[s]}
          </span>
        ))}
        <span className="ns-legend__item">
          <span className="ns-legend__dash" aria-hidden="true" /> {t('rivers.border')}
        </span>
      </figcaption>
    </figure>
  );
}

export default function Rivers() {
  const { t, td } = useI18n();
  const [rivers, setRivers] = useState<RiverSummary[] | null>(null);
  const [riversError, setRiversError] = useState<string | null>(null);
  const [basin, setBasin] = useState('');
  const [graph, setGraph] = useState<RiverGraph | null>(null);
  const [graphError, setGraphError] = useState<string | null>(null);
  const [states, setStates] = useState<AgentState[]>([]);
  const [fromNode, setFromNode] = useState('');
  const [rate, setRate] = useState('');
  const [eta, setEta] = useState<EtaResult | null>(null);
  const [etaError, setEtaError] = useState<string | null>(null);

  const loadRivers = useCallback(() => {
    getRivers().then(
      (list) => {
        const safe = Array.isArray(list) ? list : [];
        setRivers(safe);
        setRiversError(null);
        setBasin((b) => b || safe.find((r) => r.id === 'koshi')?.id || safe[0]?.id || '');
      },
      (err: unknown) => setRiversError(errorMessage(err)),
    );
    getAgentState()
      .then((s) => setStates(Array.isArray(s) ? s : []))
      .catch(() => setStates([]));
  }, []);

  useEffect(() => {
    void loadRivers();
  }, [loadRivers]);

  const loadGraph = useCallback(
    (id: string) =>
      getRiver(id).then(
        (g) => {
          setGraph(g);
          setGraphError(null);
          setFromNode((f) => (g.nodes?.some((n) => n.id === f) ? f : g.nodes?.[0]?.id ?? ''));
        },
        (err: unknown) => setGraphError(errorMessage(err)),
      ),
    [],
  );

  useEffect(() => {
    if (basin) void loadGraph(basin);
  }, [basin, loadGraph]);

  const compute = async (nodeId: string) => {
    if (!basin || !nodeId) return;
    setFromNode(nodeId);
    const parsedRate = rate.trim() ? Number(rate) : null;
    try {
      const result = await getEta(basin, nodeId, Number.isFinite(parsedRate) ? parsedRate : null);
      setEta(result);
      setEtaError(null);
    } catch (err) {
      setEta(null);
      setEtaError(errorMessage(err));
    }
  };

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    void compute(fromNode);
  };

  const fromName = graph?.nodes.find((n) => n.id === eta?.from_node)?.name ?? eta?.from_node ?? '';

  return (
    <div className="ns-page">
      <PageHeader title={t('rivers.title')} subtitle={t('rivers.subtitle')} />
      {riversError && <StateNotice kind="error" message={t('rivers.loadError')} detail={riversError} onRetry={() => void loadRivers()} />}
      {!riversError && rivers === null && <StateNotice kind="loading" message={t('common.loading')} />}
      {rivers?.length === 0 && <StateNotice kind="empty" message={t('rivers.empty')} />}

      {rivers && rivers.length > 0 && (
        <div className="ns-river-grid">
          <section className="ns-card ns-stack" aria-labelledby="river-controls-h">
            <h3 id="river-controls-h" className="sr-only">{t('rivers.basin')}</h3>
            <div className="ns-field">
              <label htmlFor="river-basin">{t('rivers.basin')}</label>
              <select
                id="river-basin"
                className="ns-input"
                value={basin}
                onChange={(e) => {
                  setEta(null);
                  setBasin(e.target.value);
                }}
              >
                {rivers.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.name} ({r.countries.map((c) => td(`country.${c}`, c)).join(' · ')})
                  </option>
                ))}
              </select>
            </div>
            {graph && (
              <form onSubmit={onSubmit} className="ns-stack">
                <div className="ns-field">
                  <label htmlFor="river-from">{t('rivers.from')}</label>
                  <select id="river-from" className="ns-input" value={fromNode} onChange={(e) => setFromNode(e.target.value)}>
                    {graph.nodes.map((n) => (
                      <option key={n.id} value={n.id}>
                        {n.name} ({td(`country.${n.country}`, n.country)})
                      </option>
                    ))}
                  </select>
                </div>
                <div className="ns-field">
                  <label htmlFor="river-rate">{t('rivers.rate')}</label>
                  <input
                    id="river-rate"
                    className="ns-input"
                    type="number"
                    step="0.05"
                    min="0"
                    inputMode="decimal"
                    value={rate}
                    onChange={(e) => setRate(e.target.value)}
                  />
                </div>
                <button type="submit" className="ns-btn ns-btn--primary">
                  <Timer className="w-4 h-4" aria-hidden="true" /> {t('rivers.compute')}
                </button>
              </form>
            )}
            <div aria-live="polite">
              {etaError && <StateNotice kind="error" message={t('rivers.etaError')} detail={etaError} />}
              {eta && (
                <div className="ns-stack-sm">
                  <h4 className="ns-label">{t('rivers.downstream', { name: fromName })}</h4>
                  {eta.downstream.length === 0 ? (
                    <p className="ns-muted">{t('rivers.noDownstream')}</p>
                  ) : (
                    <ol className="ns-eta-list">
                      {eta.downstream.map((d) => (
                        <li key={d.node_id}>
                          <span className="ns-strong">{d.name}</span>{' '}
                          <span className="ns-hint">({td(`country.${d.country}`, d.country)})</span>
                          <br />
                          {t('common.etaBand', { min: fmtHours(d.eta_h.min), max: fmtHours(d.eta_h.max), typ: fmtHours(d.eta_h.typ) })}
                          {d.crosses_border && (
                            <>
                              {' '}
                              <Chip tone="info">{t('rivers.crossesBorder')}</Chip>
                            </>
                          )}
                        </li>
                      ))}
                    </ol>
                  )}
                </div>
              )}
            </div>
          </section>

          <section className="ns-card" aria-label={graph ? t('rivers.schematic', { name: graph.name }) : t('rivers.title')}>
            {graphError && <StateNotice kind="error" message={t('rivers.loadError')} detail={graphError} onRetry={() => void loadGraph(basin)} />}
            {!graphError && !graph && <StateNotice kind="loading" message={t('common.loading')} />}
            {graph && <Schematic graph={graph} states={states} eta={eta} onPick={(id) => void compute(id)} />}
          </section>
        </div>
      )}
    </div>
  );
}
