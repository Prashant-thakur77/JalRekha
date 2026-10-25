import { useCallback, useEffect, useState } from 'react';
import { Link, useLocation, useParams } from 'react-router-dom';
import { ArrowLeft, ArrowRight, Camera, Cpu, ShieldCheck, ShieldX, Zap } from 'lucide-react';
import { errorMessage, getTrace, mediaUrl, type TraceDecision, type TraceDetail as Trace, type TraceStep } from '../api';
import { useI18n } from '../i18n';
import { fmtDateTime, fmtNum, fmtSigned, fmtUsd, fmtValue } from '../lib/format';
import { BranchChip, Chip, PageHeader, StateNotice } from '../components/ui';

function KeyOutputs({ output }: { output?: Record<string, unknown> | null }) {
  if (!output || typeof output !== 'object') return null;
  const entries = Object.entries(output).slice(0, 8);
  if (entries.length === 0) return null;
  return (
    <dl className="ns-kv ns-kv--compact">
      {entries.map(([k, v]) => (
        <div key={k}>
          <dt>{k}</dt>
          <dd className="ns-mono">{fmtValue(v)}</dd>
        </div>
      ))}
    </dl>
  );
}

function DecisionBlock({ decision }: { decision: TraceDecision }) {
  const { t } = useI18n();
  const before = decision.before ?? {};
  const after = decision.after ?? {};
  const keys = Array.from(new Set([...Object.keys(before), ...Object.keys(after)]));
  return (
    <div className="ns-decision">
      <div className="ns-row ns-wrap">
        <span className="ns-label">{t('trace.decision')}</span>
        {decision.branch && <BranchChip branch={decision.branch} showName />}
      </div>
      {decision.reason && <p className="ns-decision__reason">{decision.reason}</p>}
      {keys.length > 0 && (
        <ul className="ns-diff">
          {keys.map((k) => (
            <li key={k}>
              <span className="ns-mono">{k}</span>: <span className="ns-mono">{fmtValue(before[k])}</span>
              <ArrowRight className="w-4 h-4 ns-inline-icon" aria-label="→" />
              <strong className="ns-mono">{fmtValue(after[k])}</strong>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function StepItem({ step }: { step: TraceStep }) {
  const { t } = useI18n();
  const changed = Boolean(step.decision?.branch);
  return (
    <li id={`step-${step.i}`} className={`ns-step${changed ? ' ns-step--changed' : ''}`} tabIndex={-1}>
      <div className="ns-step__marker" aria-hidden="true">
        {step.i}
      </div>
      <div className="ns-step__body">
        <div className="ns-row ns-wrap">
          <Chip>{step.kind}</Chip>
          {step.tool && <span className="ns-strong ns-mono">{step.tool}</span>}
          {changed && (
            <Chip tone="warn">
              <Zap className="w-4 h-4" aria-hidden="true" /> {t('trace.changed')}
            </Chip>
          )}
        </div>
        <dl className="ns-step__meta">
          <div>
            <dt>{t('trace.latency')}</dt>
            <dd>{typeof step.latency_ms === 'number' ? `${fmtNum(step.latency_ms, 1)} ms` : '–'}</dd>
          </div>
          <div>
            <dt>{t('trace.model')}</dt>
            <dd className="ns-mono">{step.model ?? t('trace.noModel')}</dd>
          </div>
          <div>
            <dt>{t('trace.cost')}</dt>
            <dd>{fmtUsd(step.cost_usd_est)}</dd>
          </div>
          {step.guard && (
            <div>
              <dt>{t('trace.guard')}</dt>
              <dd className={step.guard.accepted ? 'ns-ok-text' : 'ns-danger-text'}>
                {step.guard.accepted ? (
                  <ShieldCheck className="w-4 h-4 ns-inline-icon" aria-hidden="true" />
                ) : (
                  <ShieldX className="w-4 h-4 ns-inline-icon" aria-hidden="true" />
                )}
                {step.guard.accepted ? t('trace.accepted') : t('trace.rejected')}
                {step.guard.reason && step.guard.reason !== 'accepted' ? `: ${step.guard.reason}` : ''}
              </dd>
            </div>
          )}
        </dl>
        {step.output && Object.keys(step.output).length > 0 && (
          <div>
            <span className="ns-label">{t('trace.outputs')}</span>
            <KeyOutputs output={step.output} />
          </div>
        )}
        {step.decision && <DecisionBlock decision={step.decision} />}
      </div>
    </li>
  );
}

export default function TraceDetail() {
  const { traceId = '' } = useParams();
  const location = useLocation();
  const { t } = useI18n();
  const [trace, setTrace] = useState<Trace | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    () =>
      getTrace(traceId).then(
        (data) => {
          setTrace(data);
          setError(null);
        },
        (err: unknown) => setError(errorMessage(err)),
      ),
    [traceId],
  );

  useEffect(() => {
    void load();
  }, [load]);

  // Evidence links point at "#step-N": scroll to and focus that step once loaded.
  useEffect(() => {
    if (!trace || !location.hash) return;
    const el = document.getElementById(location.hash.slice(1));
    if (el) {
      if (typeof el.scrollIntoView === 'function') el.scrollIntoView({ block: 'center' });
      el.focus({ preventScroll: true });
    }
  }, [trace, location.hash]);

  const m = trace?.measurement;
  const overlay = mediaUrl(m?.overlay_url ?? m?.frame_url);
  const estimators = Object.entries(m?.estimators ?? {});

  return (
    <div className="ns-page">
      <Link to="/traces" className="ns-link ns-row ns-gap-sm">
        <ArrowLeft className="w-4 h-4" aria-hidden="true" /> {t('trace.back')}
      </Link>
      {error && <StateNotice kind="error" message={t('trace.notFound')} detail={error} onRetry={() => void load()} />}
      {!error && !trace && <StateNotice kind="loading" message={t('common.loading')} />}
      {trace && (
        <>
          <PageHeader
            title={`${trace.site_id} · ${t('trace.cycle', { n: trace.cycle })}`}
            subtitle={`${fmtDateTime(trace.started_at)} · ${trace.trace_id}`}
          />
          {trace.summary && <p className="ns-lead">{trace.summary}</p>}
          {(trace.branches ?? []).length > 0 && (
            <div className="ns-row ns-wrap">
              {trace.branches.map((b) => (
                <BranchChip key={b} branch={b} showName />
              ))}
            </div>
          )}

          {m && (
            <section className="ns-card" aria-labelledby="trace-m-h">
              <h3 id="trace-m-h" className="ns-h3">
                <Camera className="w-5 h-5 ns-inline-icon" aria-hidden="true" /> {t('trace.measurement')}
              </h3>
              <div className="ns-measure">
                {overlay && (
                  <figure className="ns-frame">
                    <img src={overlay} alt={t('trace.frame')} className="ns-frame__img" />
                  </figure>
                )}
                <div className="ns-stack">
                  <p className="ns-big">
                    {fmtNum(m.stage_m)} m{typeof m.sigma_m === 'number' && <span className="ns-big__pm"> ± {fmtNum(m.sigma_m)}</span>}
                  </p>
                  <dl className="ns-kv">
                    <div>
                      <dt>{t('live.rate')}</dt>
                      <dd>{t('live.rateValue', { v: fmtSigned(m.rate_m_per_h) })}</dd>
                    </div>
                    <div>
                      <dt>{t('trace.registration')}</dt>
                      <dd className="ns-mono">{m.registration ?? '–'}</dd>
                    </div>
                    <div>
                      <dt>{t('trace.processing')}</dt>
                      <dd>{typeof m.timings_ms?.total === 'number' ? `${fmtNum(m.timings_ms.total, 1)} ms` : '–'}</dd>
                    </div>
                  </dl>
                  <div className="ns-row ns-wrap">
                    {m.quality?.ok === false ? <Chip tone="warn">{t('live.qualityBad')}</Chip> : m.quality?.ok ? <Chip tone="ok">{t('live.qualityOk')}</Chip> : null}
                    {m.usable === false ? <Chip tone="warn">{t('live.notUsable')}</Chip> : m.usable ? <Chip tone="ok">{t('live.usable')}</Chip> : null}
                    {(m.quality?.reasons ?? []).map((r) => (
                      <Chip key={r}>{r}</Chip>
                    ))}
                  </div>
                  {estimators.length > 0 && (
                    <div className="ns-table-wrap">
                      <table className="ns-table">
                        <caption className="ns-label">
                          <Cpu className="w-4 h-4 ns-inline-icon" aria-hidden="true" /> {t('trace.estimators')}
                        </caption>
                        <thead>
                          <tr>
                            <th scope="col">{t('trace.estimator')}</th>
                            <th scope="col">{t('trace.value')}</th>
                            <th scope="col">{t('trace.diff')}</th>
                          </tr>
                        </thead>
                        <tbody>
                          {estimators.map(([name, value]) => (
                            <tr key={name}>
                              <th scope="row" className="ns-mono">{name}</th>
                              <td>{fmtNum(value)}</td>
                              <td>
                                {typeof value === 'number' && typeof m.stage_m === 'number'
                                  ? `${fmtSigned((value - m.stage_m) * 100, 0)} cm`
                                  : '–'}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              </div>
            </section>
          )}

          <section aria-labelledby="trace-steps-h" className="ns-stack">
            <h3 id="trace-steps-h" className="ns-h3">{t('trace.timeline')}</h3>
            <ol className="ns-timeline">
              {(trace.steps ?? []).map((step) => (
                <StepItem key={step.i} step={step} />
              ))}
            </ol>
          </section>
        </>
      )}
    </div>
  );
}
