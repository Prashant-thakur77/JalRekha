import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { ArrowLeft, ArrowRight, CheckCircle2, Cpu, ShieldCheck } from 'lucide-react';
import { errorMessage, getLab, getLabLatest, getLabSites, type LabSite, type VisionLab } from '../api';
import { useVisionText, type VisionKey } from '../content/vision';
import { fmtDateTime, fmtNum, fmtSigned } from '../lib/format';
import { Chip, PageHeader, StateNotice } from '../components/ui';
import ProfileChart from '../components/ProfileChart';

type Load = { key: string; lab: VisionLab | null; error: string | null };

function StageHead({ n, title, body, id }: { n: number; title: string; body: string; id: string }) {
  const t = useVisionText();
  return (
    <header className="ns-lab-stage__head">
      <p className="ns-lab-stage__n" aria-hidden="true">
        {String(n).padStart(2, '0')}
      </p>
      <h2 id={id} className="ns-h3 ns-lab-stage__title">
        <span className="sr-only">{t('stageN', { n })}: </span>
        {title}
      </h2>
      <p className="ns-lab-stage__body">{body}</p>
    </header>
  );
}

function LabImage({ src, alt, caption, className = '' }: { src: string | null | undefined; alt: string; caption?: string; className?: string }) {
  if (!src) return null;
  return (
    <figure className={`ns-lab-img ${className}`}>
      <div className="ns-lab-img__frame">
        <img src={src} alt={alt} loading="lazy" />
      </div>
      {caption && <figcaption className="ns-hint">{caption}</figcaption>}
    </figure>
  );
}

function fmtMetric(key: string, v: number): string {
  if (key === 'clipped_frac' || key === 'glare_frac') return `${fmtNum(v * 100, 1)} %`;
  return fmtNum(v, 1);
}

function Waterfall({ lab }: { lab: VisionLab }) {
  const t = useVisionText();
  const total = Math.max(lab.timing.total_ms, 1e-6);
  return (
    <ol className="ns-wf" aria-label={t('timingLabel', { t: fmtNum(lab.timing.total_ms, 1) })}>
      {lab.timing.stages.map((s) => (
        <li key={s.name} className="ns-wf__row">
          <span className="ns-wf__name">{s.name}</span>
          <span className="ns-wf__track" aria-hidden="true">
            <span
              className="ns-wf__bar"
              style={{ left: `${(s.start_ms / total) * 100}%`, width: `${Math.max((s.ms / total) * 100, 0.4)}%` }}
            />
          </span>
          <span className="ns-wf__ms">{fmtNum(s.ms, 1)} ms</span>
        </li>
      ))}
      <li className="ns-wf__row ns-wf__row--total">
        <span className="ns-wf__name">{t('total')}</span>
        <span className="ns-wf__track" aria-hidden="true" />
        <span className="ns-wf__ms">{fmtNum(lab.timing.total_ms, 1)} ms</span>
      </li>
    </ol>
  );
}

function LabBody({ lab }: { lab: VisionLab }) {
  const t = useVisionText();
  const reg = lab.registration;
  const fu = lab.fusion;
  const est = lab.profiles.estimators;
  const agreed = fu.consensus?.agreed ?? fu.agreeing.length >= 2;
  const members = fu.consensus?.members ?? fu.agreeing;
  const host = lab.timing.host;
  const cycleTotal = lab.timing.cycle_ms?.total;
  const priv = lab.privacy;
  const privValue =
    priv.faces === null || priv.plates === null
      ? t('unavailable')
      : t('privacyValue', { faces: priv.faces, plates: priv.plates });
  const qualityText = lab.quality.ok ? t('qualityOk') : t('qualityBad', { r: lab.quality.reasons.join(', ') });

  return (
    <>
      <div className="ns-live-grid">
        <section className="ns-camera" aria-label={t('reading')}>
          <div className="ns-camera__bar">
            <span className="ns-eyebrow ns-eyebrow--accent">
              {lab.trace.site_name} · {t('cycleOf', { n: lab.trace.cycle, time: fmtDateTime(lab.trace.started_at) })}
            </span>
            <span className="ns-eyebrow">{lab.source?.kind === 'real' ? t('kindReal') : t('kindScenario')}</span>
          </div>
          {lab.summary.overlay_image && (
            <figure className="ns-camera__frame">
              <img src={lab.summary.overlay_image} alt={t('overlayAlt')} className="ns-camera__img" />
            </figure>
          )}
        </section>
        <section className="ns-panel ns-dark ns-lab-summary" aria-labelledby="lab-reading-h">
          <h2 id="lab-reading-h" className="ns-eyebrow ns-eyebrow--accent">
            {t('reading')}
          </h2>
          <p className="ns-figure">
            {fmtNum(lab.summary.stage_m)}
            <span className="ns-figure__unit">m</span>
          </p>
          <p className="ns-muted">± {fmtNum(lab.summary.sigma_m)} m</p>
          <dl className="ns-rows">
            <div>
              <dt>{t('quality')}</dt>
              <dd>{qualityText}</dd>
            </div>
            <div>
              <dt>{t('registration')}</dt>
              <dd>{reg.ok ? reg.method : t('failed')}</dd>
            </div>
            <div>
              <dt>{t('frames')}</dt>
              <dd>{lab.summary.frames}</dd>
            </div>
            <div>
              <dt>{t('opencvTime')}</dt>
              <dd>{fmtNum(lab.timing.total_ms, 1)} ms</dd>
            </div>
            <div>
              <dt>{t('privacy')}</dt>
              <dd>{privValue}</dd>
            </div>
            {typeof lab.trace.truth_stage_m === 'number' && (
              <div>
                <dt>{t('truth')}</dt>
                <dd>{fmtNum(lab.trace.truth_stage_m)} m</dd>
              </div>
            )}
          </dl>
          {lab.check &&
            (lab.check.match ? (
              <p className="ns-lab-check">
                <CheckCircle2 className="w-4 h-4 ns-inline-icon" aria-hidden="true" /> {t('checkMatch')}
              </p>
            ) : (
              <p className="ns-lab-check ns-muted">{t('checkDiff', { v: fmtNum(lab.check.recorded_stage_m) })}</p>
            ))}
        </section>
      </div>

      {/* 1. Quality */}
      <section className="ns-card ns-lab-stage" aria-labelledby="lab-s1">
        <StageHead n={1} id="lab-s1" title={t('s1Title')} body={t('s1Body')} />
        <div className="ns-lab-split">
          <LabImage src={lab.quality.heatmap_image} alt={t('s1Heat')} caption={t('s1Heat')} />
          <div className="ns-table-wrap">
            <table className="ns-dtable ns-dtable--flat">
              <thead>
                <tr>
                  <th scope="col">{t('colMetric')}</th>
                  <th scope="col" className="ns-num">{t('colValue')}</th>
                  <th scope="col" className="ns-num">{t('colLimit')}</th>
                  <th scope="col">{t('colResult')}</th>
                </tr>
              </thead>
              <tbody>
                {lab.quality.metrics.map((m) => (
                  <tr key={m.key}>
                    <th scope="row">
                      {t(`m.${m.key}` as VisionKey)}
                      <span className="ns-lab-op">{m.op}</span>
                    </th>
                    <td className="ns-num">{fmtMetric(m.key, m.value)}</td>
                    <td className="ns-num">{t(m.rule === 'min' ? 'atLeast' : 'atMost', { v: fmtMetric(m.key, m.threshold) })}</td>
                    <td>{m.pass ? <Chip tone="ok">{t('pass')}</Chip> : <Chip tone="warn">{t('fail')}</Chip>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      {/* 2. Registration */}
      <section className="ns-card ns-lab-stage" aria-labelledby="lab-s2">
        <StageHead n={2} id="lab-s2" title={t('s2Title')} body={t('s2Body')} />
        {reg.reference ? (
          <>
            <LabImage src={reg.matches_image} alt={t('s2Matches')} caption={t('s2Matches')} />
            <div className="ns-lab-split">
              <LabImage src={reg.compare_image} alt={t('s2Compare')} caption={t('s2Compare')} />
              <dl className="ns-rows ns-lab-rows">
                <div>
                  <dt>{t('method')}</dt>
                  <dd>{reg.ok ? reg.method : `${t('failed')} (${reg.matcher ?? '–'})`}</dd>
                </div>
                <div>
                  <dt>{t('inliers')}</dt>
                  <dd>{reg.inliers}</dd>
                </div>
                <div>
                  <dt>{t('residual')}</dt>
                  <dd>{fmtNum(reg.residual_px)} px</dd>
                </div>
                <div>
                  <dt>{t('drift')}</dt>
                  <dd>{fmtNum(reg.drift_px, 1)} px</dd>
                </div>
                <div>
                  <dt>{t('keypoints')}</dt>
                  <dd>
                    {reg.keypoints_current} / {reg.keypoints_reference}
                  </dd>
                </div>
                <div>
                  <dt>{t('matches')}</dt>
                  <dd>{reg.matches}</dd>
                </div>
                <div>
                  <dt>{t('tried')}</dt>
                  <dd>{reg.tried.join(' → ') || '–'}</dd>
                </div>
                <div>
                  <dt>{t('time')}</dt>
                  <dd>{fmtNum(reg.ms, 1)} ms</dd>
                </div>
              </dl>
            </div>
          </>
        ) : (
          <p className="ns-muted">{t('s2None')}</p>
        )}
      </section>

      {/* 3. Gauge strip */}
      <section className="ns-card ns-lab-stage" aria-labelledby="lab-s3">
        <StageHead n={3} id="lab-s3" title={t('s3Title')} body={t('s3Body')} />
        <div className="ns-lab-split ns-lab-split--strip">
          <div className="ns-lab-strips">
            <LabImage className="ns-lab-img--strip" src={lab.strip.last_image} alt={t('s3Last')} caption={t('s3Last')} />
            <LabImage
              className="ns-lab-img--strip"
              src={lab.strip.median_image}
              alt={lab.strip.frames > 1 ? t('s3Median', { n: lab.strip.frames }) : t('s3Single')}
              caption={lab.strip.frames > 1 ? t('s3Median', { n: lab.strip.frames }) : t('s3Single')}
            />
          </div>
          <div className="ns-stack">
            <dl className="ns-rows ns-lab-rows">
              <div>
                <dt>{t('stripSize')}</dt>
                <dd>{t('s3Size', { w: lab.strip.width_px, h: lab.strip.rows })}</dd>
              </div>
              <div>
                <dt>{t('frames')}</dt>
                <dd>{lab.strip.frames}</dd>
              </div>
              <div>
                <dt>{t('mPerPx')}</dt>
                <dd>{fmtNum(lab.profiles.metres_per_px * 100, 2)} cm</dd>
              </div>
            </dl>
            {lab.strip.transform && (
              <div className="ns-lab-build">
                <p className="ns-eyebrow">{t('matrix')}</p>
                <pre className="ns-lab-pre">{lab.strip.transform.map((r) => r.map((v) => fmtNum(v, 3).padStart(9)).join(' ')).join('\n')}</pre>
              </div>
            )}
          </div>
        </div>
      </section>

      {/* 4. Estimator profiles */}
      <section className="ns-card ns-dark ns-lab-stage" aria-labelledby="lab-s4">
        <StageHead n={4} id="lab-s4" title={t('s4Title')} body={t('s4Body')} />
        <div className="ns-lab-profiles">
          {est.map((e) => (
            <div key={e.name} className="ns-lab-est">
              <div className="ns-row ns-wrap ns-lab-est__head">
                <h3 className="ns-strong">{t(`e.${e.name}` as VisionKey)}</h3>
                {e.used ? <Chip tone="ok">{t('used')}</Chip> : <Chip>{t('notUsed')}</Chip>}
              </div>
              <p className="ns-hint">{t(`d.${e.name}` as VisionKey)}</p>
              <ProfileChart estimator={e} axisM={lab.profiles.axis_m} fusedM={fu.fused_m} />
              <dl className="ns-rows">
                <div>
                  <dt>{t('colStage')}</dt>
                  <dd>{e.stage_m === null ? t('noRow') : `${fmtNum(e.stage_m)} m`}</dd>
                </div>
                <div>
                  <dt>{t('confidence')}</dt>
                  <dd>{fmtNum(e.confidence)}</dd>
                </div>
                <div>
                  <dt>{t('separation')}</dt>
                  <dd>{fmtNum(e.separation)}</dd>
                </div>
              </dl>
              {e.op && <p className="ns-lab-op">{e.op}</p>}
            </div>
          ))}
        </div>
      </section>

      {/* 5. Fusion */}
      <section className="ns-card ns-lab-stage" aria-labelledby="lab-s5">
        <StageHead n={5} id="lab-s5" title={t('s5Title')} body={t('s5Body')} />
        <div className="ns-lab-split ns-lab-split--fusion">
          <div className="ns-panel ns-dark">
            <p className="ns-eyebrow ns-eyebrow--accent">{t('fused')}</p>
            <p className="ns-figure">
              {fmtNum(fu.fused_m)}
              <span className="ns-figure__unit">m</span>
            </p>
            <dl className="ns-rows">
              <div>
                <dt>{t('sigma')}</dt>
                <dd>± {fmtNum(fu.consensus?.sigma_m ?? fu.sigma_m)} m</dd>
              </div>
              <div>
                <dt>{t('kalman')}</dt>
                <dd>
                  {typeof fu.kalman?.filtered_stage_m === 'number'
                    ? t('kalmanValue', { v: fmtNum(fu.kalman.filtered_stage_m), r: fmtSigned(fu.kalman.rate_m_per_h) })
                    : t('kalmanNone')}
                </dd>
              </div>
            </dl>
          </div>
          <div className="ns-stack">
            <div className="ns-table-wrap">
              <table className="ns-dtable ns-dtable--flat">
                <thead>
                  <tr>
                    <th scope="col">{t('colEstimator')}</th>
                    <th scope="col" className="ns-num">{t('colStage')}</th>
                    <th scope="col" className="ns-num ns-lab-hide-sm">{t('colFromFused')}</th>
                    <th scope="col" className="ns-num">{t('colWeight')}</th>
                    <th scope="col">{t('colAgrees')}</th>
                  </tr>
                </thead>
                <tbody>
                  {est.map((e) => (
                    <tr key={e.name}>
                      <th scope="row">{t(`e.${e.name}` as VisionKey)}</th>
                      <td className="ns-num">{e.stage_m === null ? '–' : `${fmtNum(e.stage_m)} m`}</td>
                      <td className="ns-num ns-lab-hide-sm">
                        {e.stage_m !== null && fu.fused_m !== null ? `${fmtSigned((e.stage_m - fu.fused_m) * 100, 0)} cm` : '–'}
                      </td>
                      <td className="ns-num">{e.weight === null ? '–' : fmtNum(e.weight)}</td>
                      <td>{members.includes(e.name) ? <Chip tone="ok">{t('yes')}</Chip> : <Chip>{t('no')}</Chip>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="ns-lead ns-lab-verdict">
              {agreed
                ? t('agreeYes', { list: members.map((m) => t(`e.${m}` as VisionKey)).join(', ') })
                : fu.consensus?.recorded?.snapshot_temporal_vote
                  ? t('agreeSnapshot')
                  : t('agreeNo')}
            </p>
          </div>
        </div>
      </section>

      {/* 6. Timing */}
      <section className="ns-card ns-dark ns-lab-stage" aria-labelledby="lab-s6">
        <StageHead n={6} id="lab-s6" title={t('s6Title')} body={t('s6Body')} />
        <div className="ns-lab-split ns-lab-split--timing">
          <Waterfall lab={lab} />
          <dl className="ns-rows ns-lab-rows">
            <div>
              <dt>{t('rebuilt')}</dt>
              <dd>{fmtNum(lab.timing.total_ms, 1)} ms</dd>
            </div>
            {typeof cycleTotal === 'number' && (
              <div>
                <dt>{t('recorded')}</dt>
                <dd>{fmtNum(cycleTotal, 1)} ms</dd>
              </div>
            )}
            <div>
              <dt>{t('machine')}</dt>
              <dd>
                {host.machine}
                {host.cpu_count ? ` · ${host.cpu_count} CPU` : ''}
              </dd>
            </div>
            <div>
              <dt>{t('opencv')}</dt>
              <dd>{host.opencv}</dd>
            </div>
            <div>
              <dt>{t('kleidicv')}</dt>
              <dd>{host.kleidicv ? t('yes') : t('no')}</dd>
            </div>
          </dl>
        </div>
        <div className="ns-lab-build">
          <p className="ns-eyebrow">
            <Cpu className="w-4 h-4 ns-inline-icon" aria-hidden="true" /> cv2.getBuildInformation()
          </p>
          <pre className="ns-lab-pre">{[...host.cpu_features, ...host.hal].join('\n')}</pre>
        </div>
      </section>

      <p className="ns-hint ns-row ns-gap-sm">
        <ShieldCheck className="w-4 h-4 shrink-0" aria-hidden="true" /> {t('privacyNote')}
      </p>
    </>
  );
}

export default function Vision() {
  const t = useVisionText();
  const [params, setParams] = useSearchParams();
  const traceParam = params.get('trace');
  const siteParam = params.get('site');
  const [sites, setSites] = useState<LabSite[] | null>(null);
  const [sitesError, setSitesError] = useState<string | null>(null);
  const [load, setLoad] = useState<Load>({ key: '', lab: null, error: null });

  const loadSites = useCallback(
    () =>
      getLabSites().then(
        (list) => {
          setSites(Array.isArray(list) ? list : []);
          setSitesError(null);
        },
        (err: unknown) => setSitesError(errorMessage(err)),
      ),
    [],
  );

  useEffect(() => {
    void loadSites();
  }, [loadSites]);

  // What to show: an explicit trace, else the newest cycle of the chosen (or first non-empty) site.
  const defaultSite = useMemo(() => sites?.find((s) => s.cycles > 0)?.site_id ?? null, [sites]);
  const siteId = siteParam ?? (traceParam ? null : defaultSite);
  const selectedSite = sites?.find((s) => s.site_id === (siteId ?? load.lab?.trace.site_id)) ?? null;
  const siteEmpty = !traceParam && selectedSite !== null && selectedSite.cycles === 0;
  const key = traceParam ? `trace:${traceParam}` : siteId && !siteEmpty ? `site:${siteId}` : '';

  const fetchLab = useCallback((k: string) => {
    const [kind, id] = [k.slice(0, k.indexOf(':')), k.slice(k.indexOf(':') + 1)];
    return (kind === 'trace' ? getLab(id) : getLabLatest(id)).then(
      (lab) => setLoad({ key: k, lab, error: null }),
      (err: unknown) => setLoad({ key: k, lab: null, error: errorMessage(err) }),
    );
  }, []);

  useEffect(() => {
    if (key) void fetchLab(key);
  }, [key, fetchLab]);

  const loading = key !== '' && load.key !== key;
  const lab = load.key === key ? load.lab : null;
  const error = load.key === key ? load.error : null;
  const activeSite = lab?.trace.site_id ?? siteId;
  const noCyclesAnywhere = sites !== null && sites.length > 0 && sites.every((s) => s.cycles === 0) && !traceParam;

  return (
    <div className="ns-page ns-lab">
      <PageHeader
        eyebrow={t('eyebrow', { v: lab?.opencv_version ?? '5' })}
        title={t('title')}
        subtitle={t('subtitle')}
        align="left"
      />

      <div className="ns-lab-toolbar">
        <div className="ns-console__group" role="group" aria-labelledby="lab-site-label">
          <span id="lab-site-label" className="ns-eyebrow">
            {t('camera')}
          </span>
          <div className="ns-pills">
            {(sites ?? []).map((s) => (
              <button
                key={s.site_id}
                type="button"
                className="ns-pill"
                aria-pressed={s.site_id === activeSite}
                onClick={() => setParams({ site: s.site_id })}
              >
                {s.kind === 'real' && <span className="ns-dot ns-dot--accent" aria-hidden="true" />}
                {s.kind === 'real' ? t('siteReal') : t('siteScenario')}
                {s.cycles === 0 && <span className="sr-only"> ({t('noCycles')})</span>}
              </button>
            ))}
          </div>
        </div>
        {lab && (
          <div className="ns-row ns-wrap ns-lab-nav">
            <button
              type="button"
              className="ns-btn ns-btn--secondary ns-btn--sm"
              disabled={!lab.neighbours?.prev}
              onClick={() => lab.neighbours?.prev && setParams({ trace: lab.neighbours.prev })}
            >
              <ArrowLeft className="w-4 h-4" aria-hidden="true" /> {t('prev')}
            </button>
            <button
              type="button"
              className="ns-btn ns-btn--secondary ns-btn--sm"
              disabled={!lab.neighbours?.next}
              onClick={() => lab.neighbours?.next && setParams({ trace: lab.neighbours.next })}
            >
              {t('next')} <ArrowRight className="w-4 h-4" aria-hidden="true" />
            </button>
            <Link to={`/traces/${encodeURIComponent(lab.trace.trace_id)}`} className="ns-link">
              {t('openTrace')}
            </Link>
          </div>
        )}
      </div>

      {sitesError && !traceParam && <StateNotice kind="error" message={t('error')} detail={sitesError} onRetry={() => void loadSites()} />}
      {(noCyclesAnywhere || siteEmpty) && (
        <div className="ns-lab-empty">
          <StateNotice kind="empty" message={t('emptyTitle')} detail={noCyclesAnywhere ? t('emptyBody') : t('emptySite')} />
          <Link to="/live" className="ns-btn ns-btn--primary">
            {t('emptyCta')}
          </Link>
        </div>
      )}
      {loading && <StateNotice kind="loading" message={t('loading')} />}
      {error && !loading && <StateNotice kind="error" message={t('error')} detail={error} onRetry={() => void fetchLab(key)} />}
      {lab && !loading && <LabBody lab={lab} />}
    </div>
  );
}
