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
import { useI18n } from '../i18n';
import { fmtNum, fmtSigned, fmtTime } from '../lib/format';
import { BranchChip, Chip, ModeChip, PageHeader, StateNotice } from '../components/ui';
import StageChart from '../components/StageChart';

const POLL_MS = 1500;

export default function Live() {
  const { t } = useI18n();
  const [scenarios, setScenarios] = useState<Scenario[] | null>(null);
  const [scenarioError, setScenarioError] = useState<string | null>(null);
  const [agentStates, setAgentStates] = useState<AgentState[]>([]);
  const [selectedId, setSelectedId] = useState('');
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
          setSelectedId((current) => current || list[0]?.id || '');
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
      const started = await runScenario(scenario.id, 1.0);
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
  const RateIcon = typeof rate !== 'number' || Math.abs(rate) < 0.05 ? ArrowRight : rate > 0 ? ArrowUpRight : ArrowDownRight;
  const rateWord = typeof rate !== 'number' || Math.abs(rate) < 0.05 ? t('live.steady') : rate > 0 ? t('live.rising') : t('live.falling');
  const stage = latest?.stage_m;
  const level =
    typeof stage === 'number' && typeof dangerM === 'number' && stage >= dangerM
      ? 'danger'
      : typeof stage === 'number' && typeof warnM === 'number' && stage >= warnM
        ? 'warn'
        : 'ok';
  const replayLabel = scenario?.label;
  const pendingApprovals = run?.approval_ids?.length ?? 0;
  const total = (typeof run?.total === 'number' ? run.total : null) ?? scenarioSteps ?? 0;

  let runStatusText = '';
  if (starting) runStatusText = t('live.starting');
  else if (run?.status === 'running')
    runStatusText = total > 0 ? t('live.running', { step: run.step ?? 0, total }) : t('live.runningOpen', { step: run.step ?? 0 });
  else if (run?.status === 'done') runStatusText = t('live.done', { total: run.step ?? total });
  else if (run?.status === 'failed') runStatusText = t('live.failed', { error: run.error ?? t('common.unknown') });

  return (
    <div className="ns-page">
      <PageHeader title={t('live.title')} subtitle={t('live.subtitle')} />

      <section className="ns-card" aria-labelledby="live-controls">
        <h3 id="live-controls" className="sr-only">{t('live.scenario')}</h3>
        {scenarios === null && !scenarioError && <StateNotice kind="loading" message={t('common.loading')} />}
        {scenarioError && (
          <StateNotice kind="error" message={t('live.scenariosError')} detail={scenarioError} onRetry={() => void loadScenarios()} />
        )}
        {scenarios && scenarios.length === 0 && <StateNotice kind="empty" message={t('live.noScenarios')} />}
        {scenarios && scenarios.length > 0 && (
          <div className="ns-stack">
            <div className="ns-controls">
              <div className="ns-field ns-grow">
                <label htmlFor="live-scenario">{t('live.scenario')}</label>
                <select
                  id="live-scenario"
                  className="ns-input"
                  value={selectedId}
                  onChange={(e) => {
                    setSelectedId(e.target.value);
                    setRunSiteId(null);
                  }}
                  disabled={running}
                >
                  {scenarios.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.title}
                    </option>
                  ))}
                </select>
              </div>
              <button type="button" className="ns-btn ns-btn--primary ns-btn--lg" onClick={() => void startRun()} disabled={!scenario || starting || running}>
                <Play className="w-5 h-5" aria-hidden="true" /> {t('live.run')}
              </button>
            </div>
            {scenario?.description && <p className="ns-muted">{scenario.description}</p>}
            {replayLabel && (
              <p className="ns-replay-banner">
                <Camera className="w-4 h-4" aria-hidden="true" /> {replayLabel}
              </p>
            )}
            <div aria-live="polite" className="ns-stack-sm">
              {runStatusText && <p className="ns-run-status">{runStatusText}</p>}
              {runError && <p className="ns-field-error">{runError}</p>}
            </div>
            {run && total > 0 && (
              <progress className="ns-progress" max={total} value={Math.min(run.step ?? 0, total)} aria-label={t('live.progress')} />
            )}
          </div>
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
        <section className="ns-card ns-card--flush" aria-labelledby="live-frame-h">
          <div className="ns-card__head">
            <h3 id="live-frame-h" className="ns-h3">{live?.site?.name ?? siteId ?? t('live.stage')}</h3>
            {replayLabel && <Chip tone="replay">{replayLabel}</Chip>}
          </div>
          {overlay ? (
            <figure className="ns-frame">
              <img src={overlay} alt={t('live.overlayAlt')} className="ns-frame__img" />
              <figcaption className="ns-hint">
                {latest?.at ? t('live.lastUpdate', { time: fmtTime(latest.at) }) : null}
              </figcaption>
            </figure>
          ) : (
            <div className="ns-frame ns-frame--empty">
              <Camera className="w-8 h-8" aria-hidden="true" />
              <p>{t('live.noFrame')}</p>
            </div>
          )}
        </section>

        <section className={`ns-card ns-reading ns-reading--${level}`} aria-labelledby="live-reading-h">
          <h3 id="live-reading-h" className="ns-label">{t('live.stage')}</h3>
          <div aria-live="polite" aria-atomic="true">
            {typeof stage === 'number' ? (
              <p className="ns-big">
                {fmtNum(stage)} m
                {typeof latest?.sigma_m === 'number' && <span className="ns-big__pm"> ± {fmtNum(latest.sigma_m)}</span>}
              </p>
            ) : (
              <p className="ns-muted">{t('live.noReading')}</p>
            )}
          </div>
          <dl className="ns-kv">
            <div>
              <dt>{t('live.rate')}</dt>
              <dd className="ns-rate">
                <RateIcon className="w-4 h-4" aria-hidden="true" />
                {typeof rate === 'number' ? t('live.rateValue', { v: fmtSigned(rate) }) : '–'}
                <span className="ns-hint"> ({rateWord})</span>
              </dd>
            </div>
            <div>
              <dt>{t('live.warning')} / {t('live.danger')}</dt>
              <dd>
                {fmtNum(warnM, 1)} m / {fmtNum(dangerM, 1)} m
              </dd>
            </div>
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
          <div className="ns-agent-box">
            <span className="ns-label">{t('live.agent')}</span>
            <div className="ns-row ns-wrap">
              <ModeChip mode={live?.agent?.mode} />
              {typeof live?.agent?.cadence_s === 'number' && (
                <span className="ns-row ns-gap-sm">
                  <Clock className="w-4 h-4" aria-hidden="true" /> {t('live.cadence', { s: live.agent.cadence_s })}
                </span>
              )}
            </div>
          </div>
        </section>
      </div>

      <section className="ns-card" aria-labelledby="live-chart-h">
        <h3 id="live-chart-h" className="ns-h3">{t('live.chart')}</h3>
        <StageChart series={live?.series ?? []} warning={warnM} danger={dangerM} />
      </section>

      <section className="ns-card" aria-labelledby="live-feed-h">
        <h3 id="live-feed-h" className="ns-h3">{t('live.feed')}</h3>
        {traces.length === 0 ? (
          <p className="ns-muted">{t('live.feedEmpty')}</p>
        ) : (
          <ol className="ns-feed">
            {traces.map((tr) => (
              <li key={tr.trace_id} className="ns-feed__item">
                <div className="ns-feed__meta">
                  <time dateTime={tr.started_at}>{fmtTime(tr.started_at)}</time>
                  <span>{t('trace.cycle', { n: tr.cycle })}</span>
                </div>
                <p className="ns-feed__summary">{tr.summary}</p>
                <div className="ns-row ns-wrap">
                  {(tr.branches ?? []).map((b) => (
                    <BranchChip key={b} branch={b} />
                  ))}
                  <Link to={`/traces/${encodeURIComponent(tr.trace_id)}`} className="ns-link">
                    {t('live.openTrace')}
                    <span className="sr-only"> {t('trace.cycle', { n: tr.cycle })}</span>
                  </Link>
                </div>
              </li>
            ))}
          </ol>
        )}
      </section>
    </div>
  );
}
