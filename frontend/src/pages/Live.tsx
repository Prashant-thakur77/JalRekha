import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowDownRight, ArrowRight, ArrowUpRight, Camera, CheckCircle2, Clock, Play, ShieldAlert } from 'lucide-react';
import {
  errorMessage,
  getAgentState,
  getScenarioRun,
  getScenarios,
  getSiteLive,
  getTraces,
  mediaUrl,
  runScenario,
  type AgentState,
  type Scenario,
  type ScenarioRun,
  type SiteLive,
  type TraceSummary,
} from '../api';
import { useI18n, type MsgKey } from '../i18n';
import { fmtClock, fmtNum, fmtSigned, fmtTime } from '../lib/format';
import { BranchChip, Chip, ModeChip, PageHeader, StateNotice } from '../components/ui';
import StageChart from '../components/StageChart';
import { levelFor, type Level } from '../lib/level';

const POLL_MS = 1500;
const SPEEDS = [1, 2, 5] as const;

const LEVEL_KEY: Record<Level, MsgKey> = {
  unknown: 'live.levelUnknown',
  ok: 'live.levelNormal',
  watch: 'live.levelWatch',
  warn: 'live.levelWarning',
  danger: 'live.levelDanger',
};

/** Vertical gauge: water fills to the current stage, warning and danger marked on the staff. */
function LevelGauge({
  stage,
  warn,
  danger,
  series,
}: {
  stage: number | null;
  warn: number | null;
  danger: number | null;
  series: number[];
}) {
  const { t } = useI18n();
  const known = [stage, warn, danger, ...series].filter((v): v is number => typeof v === 'number' && Number.isFinite(v));
  const lo = known.length ? Math.max(0, Math.floor(Math.min(...known) - 1)) : 0;
  const hi = known.length ? Math.ceil(Math.max(...known) + 0.8) : 1;
  const pct = (v: number) => Math.min(100, Math.max(0, ((v - lo) / (hi - lo || 1)) * 100));
  const fill = typeof stage === 'number' ? pct(stage) : 0;
  return (
    <div
      className="ns-gauge"
      role="img"
      aria-label={t('live.gauge', { v: fmtNum(stage), warn: fmtNum(warn, 1), danger: fmtNum(danger, 1) })}
      style={{ ['--fill' as string]: `${fill}%` }}
    >
      <div className="ns-gauge__ticks" />
      {typeof warn === 'number' && (
        <div className="ns-gauge__mark ns-gauge__mark--warn" style={{ ['--at' as string]: `${pct(warn)}%` }}>
          <span>{fmtNum(warn, 1)}</span>
        </div>
      )}
      {typeof danger === 'number' && (
        <div className="ns-gauge__mark ns-gauge__mark--danger" style={{ ['--at' as string]: `${pct(danger)}%` }}>
          <span>{fmtNum(danger, 1)}</span>
        </div>
      )}
      <div className="ns-gauge__water">
        {typeof stage === 'number' && (
          <>
            <svg className="ns-gauge__wave ns-gauge__wave--back" viewBox="0 0 128 10" preserveAspectRatio="none" aria-hidden="true">
              <path d="M0 6 Q 16 0 32 6 T 64 6 T 96 6 T 128 6 V 10 H 0 Z" fill="currentColor" />
            </svg>
            <svg className="ns-gauge__wave" viewBox="0 0 128 10" preserveAspectRatio="none" aria-hidden="true">
              <path d="M0 6 Q 16 0 32 6 T 64 6 T 96 6 T 128 6 V 10 H 0 Z" fill="currentColor" />
            </svg>
          </>
        )}
      </div>
    </div>
  );
}

/** "Koshi: rise to the peak (stops at ...)" -> "Koshi: rise to the peak"; the full title is shown below. */
function shortTitle(s: Scenario): string {
  return s.title.split(' (')[0].split(',')[0].trim();
}

function ReplayKind({ scenario }: { scenario: Scenario }) {
  const { t } = useI18n();
  const real = scenario.real === true;
  return (
    <span className={`ns-replay-kind ns-replay-kind--${real ? 'real' : 'scenario'}`} title={scenario.label}>
      <span className="ns-replay-kind__dot" aria-hidden="true" />
      {real ? t('live.kindReal') : t('live.kindScenario')}
    </span>
  );
}

export default function Live() {
  const { t } = useI18n();
  const [scenarios, setScenarios] = useState<Scenario[] | null>(null);
  const [scenarioError, setScenarioError] = useState<string | null>(null);
  const [agentStates, setAgentStates] = useState<AgentState[]>([]);
  const [selectedId, setSelectedId] = useState('');
  const [speed, setSpeed] = useState<number>(1);
  const [run, setRun] = useState<ScenarioRun | null>(null);
  const [starting, setStarting] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [runSiteId, setRunSiteId] = useState<string | null>(null);
  const [live, setLive] = useState<SiteLive | null>(null);
  const [liveError, setLiveError] = useState<string | null>(null);
  const [traces, setTraces] = useState<TraceSummary[]>([]);

  const loadScenarios = useCallback(
    () =>
      Promise.allSettled([getScenarios(), getAgentState()]).then(([sc, st]) => {
        if (sc.status === 'fulfilled') {
          const list = Array.isArray(sc.value) ? sc.value : [];
          setScenarios(list);
          setScenarioError(null);
          setSelectedId((current) => current || list.find((s) => s.id === 'koshi-to-peak')?.id || list[0]?.id || '');
        } else {
          setScenarios(null);
          setScenarioError(errorMessage(sc.reason));
        }
        if (st.status === 'fulfilled' && Array.isArray(st.value)) setAgentStates(st.value);
      }),
    [],
  );

  useEffect(() => {
    void loadScenarios();
  }, [loadScenarios]);

  const scenario = scenarios?.find((s) => s.id === selectedId) ?? null;
  const scenarioSteps = typeof scenario?.steps === 'number' ? scenario.steps : null;
  const scenarioSiteId = useMemo(() => {
    if (!scenario) return null;
    if (scenario.site_id) return scenario.site_id;
    const byBasin = agentStates.filter((s) => scenario.basin && s.basin === scenario.basin);
    // Prefer a camera site if several sites share the basin.
    return (byBasin.find((s) => s.site_id.includes('cam')) ?? byBasin[0])?.site_id ?? null;
  }, [scenario, agentStates]);
  const siteId = runSiteId ?? run?.site_id ?? scenarioSiteId;
  const siteRef = useRef<string | null>(siteId);
  useEffect(() => {
    siteRef.current = siteId;
  }, [siteId]);

  /** Fetch the live reading and the newest traces for the site being watched. */
  const refreshSite = useCallback(async (runId?: string) => {
    let site = siteRef.current;
    try {
      const list = await getTraces({ siteId: site, limit: 12 });
      const safe = Array.isArray(list) ? list : [];
      const forRun = runId ? safe.filter((tr) => tr.scenario_run_id === runId) : [];
      const feed = forRun.length > 0 ? forRun : safe;
      setTraces(feed.slice(0, 8));
      if (!site && feed[0]?.site_id) {
        site = feed[0].site_id;
        siteRef.current = site;
        setRunSiteId(site);
      }
    } catch {
      // the feed is optional; the reading below still updates
    }
    if (!site) return;
    try {
      const data = await getSiteLive(site);
      setLive(data);
      setLiveError(null);
    } catch (err) {
      setLiveError(errorMessage(err));
    }
  }, []);

  // Show the last known state of the site once it is known (before any replay).
  useEffect(() => {
    if (siteId && !run) void refreshSite();
  }, [siteId, run, refreshSite]);

  const runId = run?.run_id;
  const running = run?.status === 'running';

  useEffect(() => {
    if (!runId || !running) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const tick = async () => {
      try {
        const next = await getScenarioRun(runId);
        if (cancelled) return;
        setRun((prev) => ({ ...prev, ...next }));
      } catch (err) {
        if (cancelled) return;
        setRunError(errorMessage(err));
      }
      await refreshSite(runId);
      if (!cancelled) timer = setTimeout(tick, POLL_MS);
    };
    timer = setTimeout(tick, 300);
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [runId, running, refreshSite]);

  const startRun = async () => {
    if (!scenario) return;
    setStarting(true);
    setRunError(null);
    try {
      const started = await runScenario(scenario.id, speed);
      setRun({ ...started, total: started.total ?? scenarioSteps ?? undefined, step: started.step ?? 0 });
      try {
        window.sessionStorage.setItem('nadisaathi.lastRun', started.run_id);
      } catch {
        /* storage unavailable: the approvals filter is simply not offered */
      }
    } catch (err) {
      setRunError(`${t('live.runError')} ${errorMessage(err)}`);
    } finally {
      setStarting(false);
    }
  };

  const latest = live?.latest ?? null;
  const warnM = live?.warning_m ?? scenario?.warning_m ?? null;
  const dangerM = live?.danger_m ?? scenario?.danger_m ?? null;
  const overlay = mediaUrl(latest?.overlay_url ?? latest?.frame_url);
  const rate = latest?.rate_m_per_h;
  const flat = typeof rate !== 'number' || Math.abs(rate) < 0.05;
  const RateIcon = flat ? ArrowRight : (rate as number) > 0 ? ArrowUpRight : ArrowDownRight;
  const rateWord = flat ? t('live.steady') : (rate as number) > 0 ? t('live.rising') : t('live.falling');
  const stage = typeof latest?.stage_m === 'number' ? latest.stage_m : null;
  const level = levelFor(stage, warnM, dangerM, live?.agent?.mode);
  const levelClass = level === 'unknown' ? 'ok' : level;
  const pendingApprovals = run?.approval_ids?.length ?? 0;
  const total = (typeof run?.total === 'number' ? run.total : null) ?? scenarioSteps ?? 0;
  const seriesStages = (live?.series ?? []).filter((p) => p.usable !== false).map((p) => p.stage_m);

  let margin = '';
  if (typeof stage === 'number') {
    if (typeof warnM === 'number' && stage < warnM) margin = t('live.toWarning', { v: fmtNum(warnM - stage) });
    else if (typeof dangerM === 'number' && stage < dangerM) margin = t('live.toDanger', { v: fmtNum(dangerM - stage) });
    else if (typeof dangerM === 'number') margin = t('live.overDanger', { v: fmtNum(stage - dangerM) });
  }

  let runStatusText = '';
  if (starting) runStatusText = t('live.starting');
  else if (run?.status === 'running')
    runStatusText = total > 0 ? t('live.running', { step: run.step ?? 0, total }) : t('live.runningOpen', { step: run.step ?? 0 });
  else if (run?.status === 'done') runStatusText = t('live.done', { total: run.step ?? total });
  else if (run?.status === 'failed') runStatusText = t('live.failed', { error: run.error ?? t('common.unknown') });

  return (
    <div className="ns-control ns-dark">
      <div className="ns-control__inner">
        <div className="ns-live__head">
          <PageHeader eyebrow={t('live.eyebrow')} title={t('live.title')} subtitle={t('live.subtitle')} align="left" />
          {scenario && <ReplayKind scenario={scenario} />}
        </div>

        <section className="ns-console" aria-labelledby="live-controls">
          <h2 id="live-controls" className="sr-only">{t('live.scenario')}</h2>
          {scenarios === null && !scenarioError && <StateNotice kind="loading" message={t('common.loading')} />}
          {scenarioError && (
            <StateNotice kind="error" message={t('live.scenariosError')} detail={scenarioError} onRetry={() => void loadScenarios()} />
          )}
          {scenarios && scenarios.length === 0 && <StateNotice kind="empty" message={t('live.noScenarios')} />}
          {scenarios && scenarios.length > 0 && (
            <>
              <div className="ns-console__row">
                <div className="ns-console__group" role="group" aria-labelledby="live-scenario-label">
                  <span id="live-scenario-label" className="ns-eyebrow">{t('live.scenario')}</span>
                  <div className="ns-pills">
                    {scenarios.map((s) => (
                      <button
                        key={s.id}
                        type="button"
                        className="ns-pill"
                        aria-pressed={s.id === selectedId}
                        data-scenario={s.id}
                        title={s.title}
                        disabled={running}
                        onClick={() => {
                          setSelectedId(s.id);
                          setRunSiteId(null);
                        }}
                      >
                        {s.real && <span className="ns-dot ns-dot--accent" aria-hidden="true" />}
                        {shortTitle(s)}
                      </button>
                    ))}
                  </div>
                </div>
                <div className="ns-console__group" role="group" aria-labelledby="live-speed-label">
                  <span id="live-speed-label" className="ns-eyebrow">{t('live.speed')}</span>
                  <div className="ns-pills">
                    {SPEEDS.map((v) => (
                      <button key={v} type="button" className="ns-pill" aria-pressed={speed === v} data-speed={v} disabled={running} onClick={() => setSpeed(v)}>
                        {v}×
                      </button>
                    ))}
                  </div>
                </div>
                <button type="button" className="ns-btn ns-btn--primary ns-btn--lg" onClick={() => void startRun()} disabled={!scenario || starting || running}>
                  <Play className="w-4 h-4" aria-hidden="true" /> {t('live.run')}
                </button>
              </div>
              {scenario && (
                <div className="ns-console__about">
                  <p className="ns-console__title">{scenario.title}</p>
                  {scenario.description && <p className="ns-muted">{scenario.description}</p>}
                  <p className="ns-eyebrow">{scenario.real ? t('live.kindRealNote') : t('live.kindScenarioNote')}</p>
                  {scenario.events && scenario.events.length > 0 && (
                    <ul className="ns-events" aria-label={t('live.events')}>
                      <li className="ns-eyebrow" aria-hidden="true">
                        {t('live.events')}
                      </li>
                      {scenario.events.map((e) => (
                        <li key={`${e.tag}-${e.t_from_min}`}>
                          <Chip>
                            <span lang="en">{t('live.eventAt', { tag: e.tag, from: e.t_from_min, to: e.t_to_min })}</span>
                          </Chip>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
              <div aria-live="polite" className="ns-stack-sm">
                {runStatusText && <p className="ns-run-status">{runStatusText}</p>}
                {runError && <p className="ns-field-error">{runError}</p>}
              </div>
              {run && total > 0 && (
                <progress className="ns-progress" max={total} value={Math.min(run.step ?? 0, total)} aria-label={t('live.progress')} />
              )}
            </>
          )}
        </section>

        {pendingApprovals > 0 && (
          <div className="ns-callout" role="status">
            <ShieldAlert className="w-5 h-5 shrink-0" aria-hidden="true" />
            <span>{t('live.approvalsWaiting', { n: pendingApprovals })}</span>
            <Link to="/approvals" className="ns-btn ns-btn--primary ns-btn--sm">
              {t('live.goApprovals')}
            </Link>
          </div>
        )}

        {liveError && siteId && <StateNotice kind="error" message={t('live.liveError')} detail={liveError} onRetry={() => void refreshSite(runId)} />}

        <div className="ns-live-grid">
          <section className="ns-camera" aria-labelledby="live-frame-h">
            <div className="ns-camera__bar">
              <h2 id="live-frame-h" className="ns-eyebrow ns-eyebrow--accent">
                <span className={`ns-live-dot${running ? '' : ' ns-live-dot--idle'}`} aria-hidden="true" />
                {t('live.camera')} · {live?.site?.name ?? siteId ?? t('live.stage')}
              </h2>
              <span className="ns-eyebrow">{live?.site?.region ?? ''}</span>
            </div>
            {overlay ? (
              <figure className="ns-camera__frame">
                <img src={overlay} alt={t('live.overlayAlt')} className="ns-camera__img" />
                <figcaption className="ns-camera__bar ns-camera__bar--bottom">
                  <span className="ns-eyebrow">{running ? t('live.updating') : t('live.idle')}</span>
                  <span className="ns-eyebrow">{latest?.at ? t('live.lastUpdate', { time: fmtTime(latest.at) }) : null}</span>
                </figcaption>
              </figure>
            ) : (
              <div className="ns-camera__empty">
                <Camera className="w-6 h-6" aria-hidden="true" />
                <p>{t('live.noFrame')}</p>
              </div>
            )}
          </section>

          <section className={`ns-panel ns-readout ns-readout--${levelClass}`} aria-labelledby="live-reading-h">
            <div className="ns-readout__main">
              <div className="ns-row ns-wrap">
                <span className="ns-level">
                  <span className="ns-level__dot" aria-hidden="true" />
                  {t(LEVEL_KEY[level])}
                </span>
                <h2 id="live-reading-h" className="ns-eyebrow">
                  {t('live.stage')}
                </h2>
              </div>
              <div aria-live="polite" aria-atomic="true">
                {typeof stage === 'number' ? (
                  <p className="ns-figure">
                    {fmtNum(stage)}
                    <span className="ns-figure__unit">m</span>
                  </p>
                ) : (
                  <p className="ns-muted">{t('live.noReading')}</p>
                )}
              </div>
              <p className="ns-trend">
                <RateIcon className="w-4 h-4" aria-hidden="true" />
                <span>{typeof latest?.sigma_m === 'number' ? `± ${fmtNum(latest.sigma_m)} m · ` : ''}</span>
                <span>
                  {rateWord} {typeof rate === 'number' ? t('live.rateValue', { v: fmtSigned(rate) }) : ''}
                </span>
              </p>
            </div>
            <LevelGauge stage={stage} warn={warnM} danger={dangerM} series={seriesStages} />
            <div className="ns-readout__foot">
              <dl className="ns-rows">
                <div>
                  <dt>{t('live.warning')}</dt>
                  <dd>{fmtNum(warnM)} m</dd>
                </div>
                <div>
                  <dt>{t('live.danger')}</dt>
                  <dd>{fmtNum(dangerM)} m</dd>
                </div>
                {margin && (
                  <div>
                    <dt>{t('live.margin')}</dt>
                    <dd>{margin}</dd>
                  </div>
                )}
                <div>
                  <dt>{t('live.agent')}</dt>
                  <dd>
                    <ModeChip mode={live?.agent?.mode} />
                  </dd>
                </div>
                {typeof live?.agent?.cadence_s === 'number' && (
                  <div>
                    <dt>{t('live.nextCheck')}</dt>
                    <dd>
                      <Clock className="w-4 h-4 ns-inline-icon" aria-hidden="true" /> {t('live.cadence', { s: live.agent.cadence_s })}
                    </dd>
                  </div>
                )}
              </dl>
              {latest && (
                <div className="ns-row ns-wrap">
                  {latest.quality_ok === false ? (
                    <Chip tone="warn">{t('live.qualityBad')}</Chip>
                  ) : latest.quality_ok ? (
                    <Chip tone="ok">
                      <CheckCircle2 className="w-4 h-4" aria-hidden="true" /> {t('live.qualityOk')}
                    </Chip>
                  ) : null}
                  {latest.usable === false ? <Chip tone="warn">{t('live.notUsable')}</Chip> : latest.usable ? <Chip tone="ok">{t('live.usable')}</Chip> : null}
                  {(latest.quality_reasons ?? []).map((r) => (
                    <Chip key={r}>{r}</Chip>
                  ))}
                </div>
              )}
            </div>
          </section>
        </div>

        <section className="ns-card" aria-labelledby="live-chart-h">
          <h2 id="live-chart-h" className="ns-eyebrow">{t('live.chart')}</h2>
          <StageChart series={live?.series ?? []} warning={warnM} danger={dangerM} live={running} />
        </section>

        <section className="ns-card" aria-labelledby="live-feed-h">
          <h2 id="live-feed-h" className="ns-eyebrow">{t('live.feed')}</h2>
          {traces.length === 0 ? (
            <p className="ns-muted">{t('live.feedEmpty')}</p>
          ) : (
            <table className="ns-dtable ns-dtable--flat ns-feed">
              <thead>
                <tr>
                  <th scope="col">{t('common.time')}</th>
                  <th scope="col">{t('trace.colCycle')}</th>
                  <th scope="col">{t('trace.colSummary')}</th>
                  <th scope="col" className="ns-num">
                    <span className="sr-only">{t('live.openTrace')}</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {traces.map((tr) => (
                  <tr key={tr.trace_id}>
                    <td className="ns-mono ns-num" style={{ textAlign: 'left' }}>
                      <time dateTime={tr.started_at}>{fmtClock(tr.started_at)}</time>
                    </td>
                    <td className="ns-mono">{tr.cycle}</td>
                    <td>
                      <p className="ns-feed__summary">{tr.summary}</p>
                      {(tr.branches ?? []).length > 0 && (
                        <div className="ns-row ns-wrap ns-gap-sm">
                          {(tr.branches ?? []).map((b) => (
                            <BranchChip key={b} branch={b} showName />
                          ))}
                        </div>
                      )}
                    </td>
                    <td className="ns-num">
                      <Link to={`/traces/${encodeURIComponent(tr.trace_id)}`} className="ns-link">
                        {t('live.openTrace')}
                        <span className="sr-only"> {t('trace.cycle', { n: tr.cycle })}</span>
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      </div>
    </div>
  );
}
