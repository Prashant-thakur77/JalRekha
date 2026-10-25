import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { ExternalLink } from 'lucide-react';
import {
  errorMessage,
  getCloudInsights,
  getCloudInsightsIndex,
  getCloudLogs,
  getCloudMetrics,
  getCloudServices,
  type CloudLogs,
  type CloudMetrics,
  type CloudService,
  type CloudServices,
  type InsightsResult,
} from '../api';
import { useI18n } from '../i18n';
import { fmtClock } from '../lib/format';
import { bytes, SERVICE_ORDER, serviceFacts, stageAverages } from '../lib/cloud';
import { BranchChip, PageHeader, StateNotice } from '../components/ui';
import '../styles/cloud.css';


function Spark({ points, label }: { points: Array<{ v: number }>; label: string }) {
  if (points.length < 2) return <span className="ns-muted">–</span>;
  const max = Math.max(...points.map((p) => p.v), 1);
  const d = points.map((p, i) => `${(i / (points.length - 1)) * 100},${30 - (p.v / max) * 28}`).join(' ');
  return (
    <svg className="ns-spark" viewBox="0 0 100 32" preserveAspectRatio="none" role="img" aria-label={label}>
      <polyline points={d} fill="none" stroke="currentColor" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

export default function Cloud() {
  const { t } = useI18n();
  const [services, setServices] = useState<CloudServices | null>(null);
  const [logs, setLogs] = useState<CloudLogs | null>(null);
  const [source, setSource] = useState<'cycles' | 'app'>('cycles');
  const [metrics, setMetrics] = useState<CloudMetrics | null>(null);
  const [queries, setQueries] = useState<Array<{ id: string; title: string; query: string }>>([]);
  const [queryId, setQueryId] = useState('opencv_stages');
  const [result, setResult] = useState<InsightsResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadLogs = useCallback(
    () => getCloudLogs(source).then(setLogs, (err: unknown) => setError(errorMessage(err))),
    [source],
  );

  useEffect(() => {
    getCloudServices().then(setServices, (err: unknown) => setError(errorMessage(err)));
    getCloudMetrics(3).then(setMetrics, () => setMetrics(null));
    getCloudInsightsIndex().then(setQueries, () => setQueries([]));
  }, []);

  useEffect(() => {
    void loadLogs();
    const timer = setInterval(() => void loadLogs(), 4000);
    return () => clearInterval(timer);
  }, [loadLogs]);

  useEffect(() => {
    let alive = true;
    getCloudInsights(queryId).then(
      (r) => alive && setResult(r),
      () => alive && setResult(null),
    );
    return () => {
      alive = false;
    };
  }, [queryId]);
  const running = result?.id !== queryId;

  const stages = useMemo(() => stageAverages(metrics), [metrics]);
  const stageMax = Math.max(...stages.map((s) => s.ms), 1);
  const total = metrics?.series['stage:total'] ?? [];
  const totalAvg = total.length ? total.reduce((a, p) => a + p.v, 0) / total.length : null;

  if (error && !services && !logs) {
    return (
      <div className="ns-control ns-dark">
        <div className="ns-control__inner">
          <PageHeader eyebrow="AWS" title={t('cloud.title')} subtitle={t('cloud.subtitle')} align="left" />
          <StateNotice kind="error" message={t('cloud.unavailable')} detail={error} />
        </div>
      </div>
    );
  }

  return (
    <div className="ns-control ns-dark">
      <div className="ns-control__inner">
        <PageHeader
          eyebrow={t('cloud.eyebrow', { region: services?.region ?? 'us-east-1' })}
          title={t('cloud.title')}
          subtitle={t('cloud.subtitle')}
          align="left"
          actions={
            services?.console_url ? (
              <a className="ns-btn ns-btn--secondary ns-btn--sm" href={services.console_url} target="_blank" rel="noreferrer">
                {t('cloud.openConsole')} <ExternalLink className="w-4 h-4" aria-hidden="true" />
              </a>
            ) : undefined
          }
        />

        <section aria-labelledby="cloud-services" className="ns-stack">
          <h2 id="cloud-services" className="ns-eyebrow">{t('cloud.services')}</h2>
          {!services && <StateNotice kind="loading" message={t('common.loading')} />}
          {services && (
            <ul className="ns-crossgrid ns-cloud-services">
              {SERVICE_ORDER.filter((id) => typeof services[id] === 'object').map((id) => {
                const s = services[id] as CloudService;
                return (
                  <li key={id} className="ns-cloud-svc" data-ok={s.ok ? 'yes' : 'no'}>
                    <p className="ns-cloud-svc__name">
                      <span className={`ns-dot ${s.ok ? 'ns-dot--accent' : 'ns-dot--danger'}`} aria-hidden="true" />
                      {t(`cloud.svc.${id}` as never)}
                    </p>
                    {s.ok ? (
                      serviceFacts(id, s).map((f) => (
                        <p key={f} className="ns-cloud-svc__fact">{f}</p>
                      ))
                    ) : (
                      <p className="ns-cloud-svc__fact">{t('cloud.err')}</p>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </section>

        <section aria-labelledby="cloud-logs" className="ns-console ns-cloud-log">
          <div className="ns-console__row">
            <div>
              <h2 id="cloud-logs" className="ns-eyebrow ns-eyebrow--accent">
                <span className="ns-live-dot" aria-hidden="true" /> {t('cloud.logs')} · {logs?.log_group ?? ''}
              </h2>
              <p className="ns-muted">{t('cloud.logsHint')}</p>
            </div>
            <div className="ns-pills" role="group">
              {(['cycles', 'app'] as const).map((src) => (
                <button key={src} type="button" className="ns-pill" aria-pressed={source === src} onClick={() => setSource(src)}>
                  {src === 'cycles' ? t('cloud.sourceCycles') : t('cloud.sourceApp')}
                </button>
              ))}
            </div>
          </div>
          {logs && logs.events.length === 0 && <StateNotice kind="empty" message={t('cloud.noEvents')} />}
          {logs && logs.events.length > 0 && source === 'cycles' && (
            <div className="ns-cloud-log__scroll">
              <table className="ns-dtable ns-dtable--flat">
                <thead>
                  <tr>
                    <th scope="col">{t('cloud.col.time')}</th>
                    <th scope="col">{t('cloud.col.site')}</th>
                    <th scope="col">{t('cloud.col.decision')}</th>
                    <th scope="col" className="ns-num">{t('cloud.col.stage')}</th>
                    <th scope="col" className="ns-num">{t('cloud.col.opencv')}</th>
                    <th scope="col">{t('cloud.col.align')}</th>
                    <th scope="col">{t('cloud.col.s3')}</th>
                  </tr>
                </thead>
                <tbody>
                  {logs.events.map((e) =>
                    e.event ? (
                      <tr key={`${e.event.trace_id}-${e.at}`}>
                        <td className="ns-mono ns-nowrap">{fmtClock(e.at)}</td>
                        <td className="ns-mono ns-nowrap">{e.event.site} #{e.event.cycle}</td>
                        <td>
                          <span className="ns-row ns-wrap ns-gap-sm">
                            {e.event.branches.map((b) => (
                              <BranchChip key={b} branch={b} />
                            ))}
                            <Link to={`/traces/${e.event.trace_id}`} className="ns-link ns-cloud-log__summary">
                              {e.event.summary}
                            </Link>
                          </span>
                        </td>
                        <td className="ns-num ns-mono">{e.event.stage_m == null ? '–' : `${e.event.stage_m.toFixed(2)} m`}</td>
                        <td className="ns-num ns-mono">{e.event.ms?.total == null ? '–' : `${e.event.ms.total.toFixed(0)} ms`}</td>
                        <td className="ns-mono ns-nowrap">
                          {e.event.registration ?? '–'}
                          {e.event.inliers ? ` · ${e.event.inliers}` : ''}
                        </td>
                        <td className="ns-mono ns-cloud-log__key">{e.event.s3_key ? `…/${e.event.s3_key.split('/').pop()}` : '–'}</td>
                      </tr>
                    ) : null,
                  )}
                </tbody>
              </table>
            </div>
          )}
          {logs && logs.events.length > 0 && source === 'app' && (
            <pre className="ns-cloud-log__raw">
              {logs.events.map((e) => `${fmtClock(e.at)}  ${(e.message ?? '').replace(/^\S+ \S+ \S+: /, '')}`).join('\n')}
            </pre>
          )}
          {logs?.console_url && (
            <a className="ns-link ns-mono" href={logs.console_url} target="_blank" rel="noreferrer">
              CloudWatch Logs <ExternalLink className="w-4 h-4 ns-inline-icon" aria-hidden="true" />
            </a>
          )}
        </section>

        <div className="ns-cloud-two">
          <section aria-labelledby="cloud-stages" className="ns-panel">
            <h2 id="cloud-stages" className="ns-eyebrow ns-eyebrow--accent">{t('cloud.stages')}</h2>
            <p className="ns-figure">
              {totalAvg == null ? '–' : totalAvg.toFixed(0)}
              <span className="ns-figure__unit">ms</span>
            </p>
            <p className="ns-muted">{t('cloud.stagesHint')}</p>
            <ul className="ns-cloud-bars">
              {stages.map((s) => (
                <li key={s.stage}>
                  <span className="ns-mono">{s.stage}</span>
                  <span className="ns-cloud-bars__track">
                    <span className="ns-cloud-bars__fill" style={{ width: `${(s.ms / stageMax) * 100}%` }} />
                  </span>
                  <span className="ns-mono ns-num">{s.ms.toFixed(1)}</span>
                </li>
              ))}
            </ul>
          </section>

          <section aria-labelledby="cloud-host" className="ns-console">
            <h2 id="cloud-host" className="ns-eyebrow">{t('cloud.host')}</h2>
            {[
              { key: 'cpu_percent', label: `${t('cloud.cpu')} %` },
              { key: 'mem_percent', label: `${t('cloud.mem')} %` },
              { key: 'agent_cycles', label: t('cloud.cycles') },
              { key: 'stage:total', label: 'OpenCV ms' },
            ].map(({ key, label }) => {
              const pts = metrics?.series[key] ?? [];
              const last = pts.length ? pts[pts.length - 1].v : null;
              return (
                <div key={key} className="ns-cloud-metric">
                  <span className="ns-eyebrow">{label}</span>
                  <Spark points={pts} label={label} />
                  <span className="ns-mono ns-num">{last == null ? '–' : last.toFixed(key === 'agent_cycles' ? 0 : 1)}</span>
                </div>
              );
            })}
            {metrics?.console_url && (
              <a className="ns-link ns-mono" href={metrics.console_url} target="_blank" rel="noreferrer">
                CloudWatch dashboard <ExternalLink className="w-4 h-4 ns-inline-icon" aria-hidden="true" />
              </a>
            )}
          </section>
        </div>

        <section aria-labelledby="cloud-insights" className="ns-console">
          <div>
            <h2 id="cloud-insights" className="ns-eyebrow">{t('cloud.insights')}</h2>
            <p className="ns-muted">{t('cloud.insightsHint')}</p>
          </div>
          <div className="ns-pills" role="group">
            {queries.map((q) => (
              <button key={q.id} type="button" className="ns-pill" aria-pressed={q.id === queryId} onClick={() => setQueryId(q.id)}>
                {q.title.replace(/, last 24 h$/, '')}
              </button>
            ))}
          </div>
          <pre className="ns-cloud-query">{queries.find((q) => q.id === queryId)?.query ?? ''}</pre>
          {running && <StateNotice kind="loading" message={t('common.loading')} />}
          {!running && result && result.rows.length === 0 && <StateNotice kind="empty" message={t('cloud.noRows')} />}
          {!running && result && result.rows.length > 0 && (
            <div className="ns-cloud-log__scroll">
              <table className="ns-dtable ns-dtable--flat">
                <thead>
                  <tr>
                    {Object.keys(result.rows[0]).map((k) => (
                      <th key={k} scope="col">{k}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {result.rows.map((r, i) => (
                    <tr key={i}>
                      {Object.entries(r).map(([k, v]) => (
                        <td key={k} className={/^-?[0-9.]+$/.test(v) ? 'ns-num ns-mono' : 'ns-mono'}>
                          {/^-?[0-9]+\.[0-9]{3,}$/.test(v) ? Number(v).toFixed(2) : v}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {!running && result && (
            <p className="ns-hint ns-mono">
              {t('cloud.scanned', { bytes: bytes(result.scanned_bytes), n: result.records_matched ?? 0, s: result.duration_s })}
            </p>
          )}
        </section>
      </div>
    </div>
  );
}
