import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  errorMessage,
  getEta,
  getEvidence,
  getSiteLive,
  getTraces,
  mediaUrl,
  type EtaResult,
  type EvidenceItem,
  type SiteLive,
  type TraceSummary,
} from '../api';
import { useI18n, type MsgKey } from '../i18n';
import { datasetKind, showValue } from '../lib/evidence';
import { fmtHours, fmtNum, fmtSigned, fmtTime } from '../lib/format';
import { levelFor, type Level } from '../lib/level';
import { pickPhotos, orderPhotos, usePhotos } from '../lib/photos';
import Photo, { PhotoCreditLine } from '../components/Photo';
import ScrollStatement from '../components/ScrollStatement';
import { BranchChip, StateNotice } from '../components/ui';

const SITE = 'koshi-chatara-cam';
const LEVEL_KEY: Record<Level, MsgKey> = {
  unknown: 'live.levelUnknown',
  ok: 'live.levelNormal',
  watch: 'live.levelWatch',
  warn: 'live.levelWarning',
  danger: 'live.levelDanger',
};
const BASIN = 'koshi';
const FROM_NODE = 'chatara';

/** The Hindi SMS the agent would draft from a reading (an example; real drafts are in Approvals). */
function hindiSms(stage: number, rate: number | null | undefined, min: number | null, max: number | null): string {
  const r = typeof rate === 'number' ? rate : 0;
  const trend =
    r > 0.05
      ? `और ${fmtNum(r)} मीटर प्रति घंटे की दर से बढ़ रही है।`
      : r < -0.05
        ? `और ${fmtNum(Math.abs(r))} मीटर प्रति घंटे की दर से घट रही है।`
        : 'और स्थिर है।';
  const eta = min !== null && max !== null ? ` बीरपुर में पानी ${Math.round(min)} से ${Math.round(max)} घंटे में पहुँच सकता है।` : '';
  return `कोसी चतरा पर ${fmtNum(stage)} मीटर पर है ${trend}${eta}`;
}

/** "4.64 m, +1.53 m/h, watch" -> numbers for the table; tolerant of other summaries. */
function parseSummary(summary: string): { stage: string | null; rate: string | null } {
  const stage = /(\d+\.\d+)\s*m\b(?!\/)/.exec(summary);
  const rate = /([+\-−]\d+\.\d+)\s*m\/h/.exec(summary);
  return { stage: stage ? `${stage[1]} m` : null, rate: rate ? rate[1] : null };
}

function EvidenceWall() {
  const { t } = useI18n();
  const [items, setItems] = useState<EvidenceItem[] | null>(null);
  const [files, setFiles] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    () =>
      getEvidence().then(
        (data) => {
          const list = Array.isArray(data?.items) ? data.items.filter((i) => i && typeof i.value === 'number') : [];
          setItems(list);
          setFiles(Array.isArray(data?.generated_from) ? data.generated_from.length : 0);
          setError(null);
        },
        (err: unknown) => {
          setItems(null);
          setError(errorMessage(err));
        },
      ),
    [],
  );

  useEffect(() => {
    void load();
  }, [load]);

  const loading = items === null && !error;

  return (
    <section className="ns-section" aria-labelledby="home-evidence-h" aria-busy={loading}>
      <header className="ns-section__head">
        <p className="ns-kicker">{t('home.evidenceEyebrow')}</p>
        <h2 id="home-evidence-h" className="ns-h2">
          {t('home.evidenceTitle')}
        </h2>
        <p className="ns-section__lede">{t('home.evidenceLede')}</p>
      </header>
      {error && <StateNotice kind="error" message={t('home.evidenceError')} detail={error} onRetry={() => void load()} />}
      {loading && (
        <p className="ns-hint ns-center" role="status">
          {t('common.loading')}
        </p>
      )}
      {items && items.length === 0 && <StateNotice kind="empty" message={t('home.evidenceEmpty')} />}
      {items && items.length > 0 && (
        <>
          <ul className="ns-crossgrid ns-stats">
            {items.map((item) => {
              const shown = showValue(item.value, item.unit);
              const base = item.baseline ? showValue(item.baseline.value, item.unit) : null;
              const kind = datasetKind(item.dataset);
              const note = (item as EvidenceItem & { note?: string | null }).note;
              return (
                <li key={item.key} className="ns-stat">
                  {kind && (
                    <span className={`ns-tag ns-tag--${kind}`}>
                      <span className="ns-dot" aria-hidden="true" />
                      {kind === 'real' ? t('home.real') : t('home.synthetic')}
                    </span>
                  )}
                  <p className="ns-stat__value">
                    {shown.value}
                    {shown.unit && <span className="ns-stat__unit">{shown.unit}</span>}
                  </p>
                  <p className="ns-stat__label" lang="en">
                    {item.label}
                  </p>
                  {item.baseline && base ? (
                    <p className="ns-stat__base">
                      {t('home.baseline')}:{' '}
                      <strong>
                        {base.value}
                        {base.unit ? ` ${base.unit}` : ''}
                      </strong>{' '}
                      <span lang="en">({item.baseline.name})</span>
                    </p>
                  ) : (
                    <p className="ns-stat__base">{t('home.noBaseline')}</p>
                  )}
                  {note && (
                    <p className="ns-stat__note" lang="en">
                      {note}
                    </p>
                  )}
                </li>
              );
            })}
          </ul>
          {files > 0 && (
            <div className="ns-stats__foot">
              <p className="ns-hint">{t('home.generatedFrom', { n: files })}</p>
              <Link to="/traces" className="ns-link">
                {t('nav.traces')} →
              </Link>
            </div>
          )}
        </>
      )}
    </section>
  );
}

export default function Home() {
  const { t, td, lang } = useI18n();
  const { photos } = usePhotos();
  const ordered = photos ? orderPhotos(photos) : [];
  const hero = pickPhotos(photos, ['bihar-kosi-flood-2008'])[0] ?? ordered[0] ?? null;
  const barrage = pickPhotos(photos, ['koshi-barrage-sunset-2015', 'koshi-barrage-2018'])[0] ?? null;

  const [live, setLive] = useState<SiteLive | null>(null);
  const [eta, setEta] = useState<EtaResult | null>(null);
  const [traces, setTraces] = useState<TraceSummary[]>([]);

  useEffect(() => {
    let alive = true;
    getSiteLive(SITE).then(
      (d) => alive && setLive(d && typeof d === 'object' && !Array.isArray(d) ? d : null),
      () => undefined,
    );
    getEta(BASIN, FROM_NODE).then(
      (d) => alive && setEta(d && Array.isArray(d.downstream) ? d : null),
      () => undefined,
    );
    getTraces({ siteId: SITE, limit: 3 }).then(
      (d) => alive && setTraces(Array.isArray(d) ? d.slice(0, 3) : []),
      () => undefined,
    );
    return () => {
      alive = false;
    };
  }, []);

  const latest = live?.latest ?? null;
  const stage = typeof latest?.stage_m === 'number' ? latest.stage_m : null;
  const rate = latest?.rate_m_per_h;
  const warnM = live?.warning_m ?? null;
  const dangerM = live?.danger_m ?? null;
  const level = levelFor(stage, warnM, dangerM, live?.agent?.mode);
  const overlay = mediaUrl(latest?.overlay_url ?? latest?.frame_url);
  const birpur = eta?.downstream.find((d) => d.node_id === 'birpur') ?? null;
  const borderTitle = birpur
    ? t('home.borderTitleBand', { min: Math.round(birpur.eta_h.min), max: Math.round(birpur.eta_h.max) })
    : t('home.borderTitle');
  const rateWord =
    typeof rate !== 'number' || Math.abs(rate) < 0.05 ? t('live.steady') : rate > 0 ? t('live.rising') : t('live.falling');
  const sms = stage !== null ? hindiSms(stage, rate, birpur?.eta_h.min ?? null, birpur?.eta_h.max ?? null) : null;

  return (
    <div className="ns-home">
      <section className="ns-hero" aria-labelledby="home-title">
        {hero ? (
          <div className="ns-hero__media">
            <Photo photo={hero} eager credit="none" />
          </div>
        ) : (
          <div className="ns-hero__fallback" aria-hidden="true" />
        )}
        <div className="ns-hero__inner">
          <p className="ns-eyebrow ns-eyebrow--light">{t('home.kicker')}</p>
          <h1 id="home-title" className="ns-display">
            {t('home.titleA')} <em>{t('home.titleB')}</em> {t('home.titleC')}
          </h1>
          <p className="ns-hero__lede">{t('home.lede')}</p>
          <div className="ns-actions-row">
            <Link to="/live" className="ns-btn ns-btn--primary">
              {t('home.ctaLive')}
            </Link>
            <Link to="/story" className="ns-btn ns-btn--secondary">
              {t('home.ctaStory')}
            </Link>
          </div>
        </div>
        {hero && <PhotoCreditLine photo={hero} text={hero.id === 'bihar-kosi-flood-2008' ? t('home.photoCredit') : undefined} />}
      </section>

      <ScrollStatement text={t('home.statement')} lang={lang}>
        <p className="ns-statement__source">
          <Link to="/story">{t('home.statementSource')}</Link>
        </p>
      </ScrollStatement>

      <section className="ns-section" aria-labelledby="home-how-h">
        <header className="ns-section__head">
          <p className="ns-kicker">{t('home.howEyebrow')}</p>
          <h2 id="home-how-h" className="ns-h2">
            {t('home.howTitle')}
          </h2>
        </header>
        <ol className="ns-howcards">
          <li className="ns-tile">
            <p className="ns-eyebrow">{t('home.step1Tag')}</p>
            <h3 className="ns-h3">{t('home.step1Title')}</h3>
            <p className="ns-tile__body">{t('home.step1Body')}</p>
            <div className="ns-shot ns-shot--frame">
              {overlay ? <img src={overlay} alt={t('live.overlayAlt')} loading="lazy" /> : <span className="ns-eyebrow">{t('live.noReading')}</span>}
            </div>
            <Link to="/live" className="ns-btn ns-btn--tertiary ns-btn--block">
              {t('home.step1Cta')}
            </Link>
          </li>
          <li className="ns-tile">
            <p className="ns-eyebrow">{t('home.step2Tag')}</p>
            <h3 className="ns-h3">{t('home.step2Title')}</h3>
            <p className="ns-tile__body">{t('home.step2Body')}</p>
            <div className="ns-shot ns-shot--list ns-dark">
              {['D4', 'D3', 'D5'].map((b) => (
                <span key={b} className="ns-shot__row">
                  <BranchChip branch={b} />
                  <span>{td(`branch.${b}`, b)}</span>
                </span>
              ))}
            </div>
            <Link to="/traces" className="ns-btn ns-btn--tertiary ns-btn--block">
              {t('home.step2Cta')}
            </Link>
          </li>
          <li className="ns-tile">
            <p className="ns-eyebrow">{t('home.step3Tag')}</p>
            <h3 className="ns-h3">{t('home.step3Title')}</h3>
            <p className="ns-tile__body">{t('home.step3Body')}</p>
            <div className="ns-shot ns-shot--sms">
              <span className="ns-eyebrow">{t('home.step3Image')}</span>
              <p lang="hi">{sms ?? hindiSms(4.38, 1.4, 4.3, 9.9)}</p>
            </div>
            <Link to="/approvals" className="ns-btn ns-btn--tertiary ns-btn--block">
              {t('home.step3Cta')}
            </Link>
          </li>
        </ol>

        <div className="ns-split">
          <div className="ns-dtable-card">
            <table className="ns-dtable">
              <caption className="ns-dtable__caption">{t('home.decisionsLabel')}</caption>
              <thead>
                <tr>
                  <th scope="col">{t('common.time')}</th>
                  <th scope="col">{t('home.colDecision')}</th>
                  <th scope="col" className="ns-num">
                    {t('home.colStage')}
                  </th>
                  <th scope="col" className="ns-num">
                    {t('home.colRate')}
                  </th>
                </tr>
              </thead>
              <tbody>
                {traces.length === 0 ? (
                  <tr>
                    <td colSpan={4} className="ns-hint">
                      {t('live.feedEmpty')}
                    </td>
                  </tr>
                ) : (
                  traces.map((tr) => {
                    const p = parseSummary(tr.summary);
                    return (
                      <tr key={tr.trace_id}>
                        <td className="ns-mono">{fmtTime(tr.started_at).slice(0, 5)}</td>
                        <td>
                          <span className="ns-row ns-wrap ns-gap-sm">
                            {(tr.branches ?? []).slice(0, 2).map((b) => (
                              <BranchChip key={b} branch={b} />
                            ))}
                            <Link to={`/traces/${encodeURIComponent(tr.trace_id)}`} className="ns-dtable__link">
                              {tr.summary}
                            </Link>
                          </span>
                        </td>
                        <td className="ns-num">{p.stage ?? '–'}</td>
                        <td className="ns-num">{p.rate ?? '–'}</td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
            {sms && (
              <div className="ns-sms">
                <p className="ns-eyebrow">{t('home.smsLabel')}</p>
                <p lang="hi">{sms}</p>
              </div>
            )}
          </div>

          <section className="ns-panel ns-dark" aria-labelledby="home-live-h">
            <h2 id="home-live-h" className="ns-eyebrow ns-eyebrow--accent">
              <span className="ns-live-dot" aria-hidden="true" /> {t('home.liveEyebrow')}
            </h2>
            {stage !== null ? (
              <>
                <p className="ns-figure">
                  {fmtNum(stage)}
                  <span className="ns-figure__unit">m</span>
                </p>
                <p className="ns-readline">
                  {typeof latest?.sigma_m === 'number' ? `± ${fmtNum(latest.sigma_m)} m · ` : ''}
                  {rateWord} {typeof rate === 'number' ? `${fmtSigned(rate)} m/h` : ''}
                </p>
              </>
            ) : (
              <p className="ns-muted">{t('home.liveEmpty')}</p>
            )}
            <dl className="ns-rows">
              <div>
                <dt>{t('live.warning')}</dt>
                <dd>{fmtNum(warnM)} m</dd>
              </div>
              <div>
                <dt>{t('live.danger')}</dt>
                <dd>{fmtNum(dangerM)} m</dd>
              </div>
              {birpur && (
                <div>
                  <dt>
                    {birpur.name}, {td(`country.${birpur.country}`, birpur.country)}
                  </dt>
                  <dd className="ns-accent-text">
                    {fmtHours(birpur.eta_h.min)}–{fmtHours(birpur.eta_h.max)} h
                  </dd>
                </div>
              )}
            </dl>
            <div className="ns-panel__foot">
              <span className="ns-levels" role="img" aria-label={t(LEVEL_KEY[level])}>
                {(['ok', 'watch', 'warn', 'danger'] as const).map((l) => (
                  <span key={l} className={`ns-levels__dot ns-levels__dot--${l}${l === level ? ' is-on' : ''}`} />
                ))}
              </span>
              <Link to="/live" className="ns-btn ns-btn--primary">
                {t('home.liveCta')}
              </Link>
            </div>
          </section>
        </div>
      </section>

      <EvidenceWall />

      <section className="ns-section" aria-labelledby="home-border-h">
        <div className="ns-border">
          {barrage && <Photo photo={barrage} className="ns-notch-left" />}
          <div className="ns-border__body">
            <p className="ns-eyebrow">{t('home.borderIndex')}</p>
            <h2 id="home-border-h" className="ns-h2 ns-h2--left">
              {borderTitle}
            </h2>
            <p className="ns-lead">{t('home.borderBody')}</p>
            {eta && eta.downstream.length > 0 && (
              <table className="ns-dtable ns-dtable--flat">
                <thead>
                  <tr>
                    <th scope="col">{t('home.etaPlace')}</th>
                    <th scope="col" className="ns-num">
                      {t('home.etaWindow')}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {eta.downstream.map((d) => (
                    <tr key={d.node_id}>
                      <td>
                        <span className="ns-row ns-gap-sm">
                          <span className="ns-badge" title={td(`country.${d.country}`, d.country)}>
                            {d.country}
                          </span>
                          {d.name}
                        </span>
                      </td>
                      <td className="ns-num">
                        {fmtHours(d.eta_h.min)}–{fmtHours(d.eta_h.max)} h
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            <div>
              <Link to="/rivers" className="ns-btn ns-btn--secondary">
                {t('home.borderCta')}
              </Link>
            </div>
          </div>
        </div>
      </section>

      <section className="ns-section ns-section--closing" aria-labelledby="home-closing-h">
        <header className="ns-section__head">
          <h2 id="home-closing-h" className="ns-h2">
            {t('home.closingTitle')}
          </h2>
          <p className="ns-section__lede">{t('home.closingBody')}</p>
        </header>
        <div className="ns-actions-row ns-actions-row--center">
          <Link to="/live" className="ns-btn ns-btn--primary">
            {t('home.ctaLive')}
          </Link>
          <Link to="/story" className="ns-btn ns-btn--secondary">
            {t('home.ctaStory')}
          </Link>
        </div>
      </section>
    </div>
  );
}
