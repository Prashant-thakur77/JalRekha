import { useCallback, useEffect, useRef, useState, type FormEvent, type MouseEvent } from 'react';
import { Link } from 'react-router-dom';
import { Camera, CheckCircle2, Copy, Crosshair, Home, LocateFixed, Route, Send, Truck, X } from 'lucide-react';
import {
  createReliefRequest,
  decideReliefRequest,
  errorMessage,
  getReliefRequests,
  getRoutes,
  getShelters,
  mediaUrl,
  photoCheck,
  type PhotoCheckResult,
  type ReliefNeed,
  type ReliefRequest,
  type ReliefRequestInput,
  type RouteStatus,
  type Shelter,
} from '../api';
import { messageLangName, useI18n } from '../i18n';
import { fmtDateTime, fmtNum } from '../lib/format';
import { toast } from '../lib/toast';
import { withOperatorPin } from '../lib/pinPrompt';
import { Chip, PageHeader, StateNotice } from '../components/ui';
import Photo from '../components/Photo';
import { pickPhotos, usePhotos } from '../lib/photos';

const NEEDS: ReliefNeed[] = ['rescue', 'food', 'water', 'medical', 'shelter', 'other'];
const REQUEST_LANGS: ReliefRequestInput['lang'][] = ['hi', 'ne', 'mai', 'bho', 'en'];

function urgencyTone(u: string) {
  return u === 'critical' ? 'danger' : u === 'high' ? 'warn' : u === 'medium' ? 'info' : 'neutral';
}

// ── Relief requests ───────────────────────────────────────────────────────

function RequestsPanel() {
  const { t, td } = useI18n();
  const [text, setText] = useState('');
  const [lang, setLang] = useState<ReliefRequestInput['lang']>('hi');
  const [need, setNeed] = useState<ReliefNeed | ''>('');
  const [people, setPeople] = useState('');
  const [lat, setLat] = useState('');
  const [lng, setLng] = useState('');
  const [formError, setFormError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [items, setItems] = useState<ReliefRequest[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    () =>
      getReliefRequests().then(
        (list) => {
          const safe = Array.isArray(list) ? [...list] : [];
          const open = (r: ReliefRequest) => (r.status === 'pending_approval' || r.status === 'pending' ? 0 : 1);
          safe.sort((a, b) => open(a) - open(b) || (b.priority ?? 0) - (a.priority ?? 0));
          setItems(safe);
          setError(null);
        },
        (err: unknown) => setError(errorMessage(err)),
      ),
    [],
  );

  useEffect(() => {
    void load();
  }, [load]);

  const fillLocation = () => {
    if (!('geolocation' in navigator)) {
      toast(t('relief.locationError'), 'error');
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setLat(pos.coords.latitude.toFixed(5));
        setLng(pos.coords.longitude.toFixed(5));
      },
      () => toast(t('relief.locationError'), 'error'),
      { timeout: 8000 },
    );
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!text.trim()) {
      setFormError(t('relief.textRequired'));
      return;
    }
    setFormError('');
    setSubmitting(true);
    const num = (v: string) => (v.trim() && Number.isFinite(Number(v)) ? Number(v) : null);
    try {
      const created = await createReliefRequest({
        text: text.trim(),
        lang,
        lat: num(lat),
        lng: num(lng),
        site_id: null,
        channel: 'app',
        people: num(people),
        ...(need ? { need } : {}),
      });
      toast(t('relief.submitted', { p: fmtNum(created.priority, 2) }), 'success');
      setText('');
      setPeople('');
      setNeed('');
      await load();
    } catch (err) {
      toast(`${t('relief.submitError')} ${errorMessage(err)}`, 'error');
    } finally {
      setSubmitting(false);
    }
  };

  const decide = async (item: ReliefRequest, decision: 'approve' | 'reject') => {
    try {
      const result = await withOperatorPin(
        {
          title: t('relief.dispatchTitle', { id: item.id }),
          confirmLabel: decision === 'approve' ? t('relief.dispatch') : t('relief.rejectReq'),
          tone: decision === 'approve' ? 'primary' : 'danger',
          askOperator: true,
          extra: decision === 'approve' ? { label: t('relief.team'), defaultValue: item.team ?? '' } : undefined,
        },
        (answer) =>
          decideReliefRequest(
            item.id,
            { decision, operator: answer.operator || 'operator', ...(answer.extra ? { team: answer.extra } : {}) },
            answer.pin,
          ),
        t('pin.wrong'),
      );
      if (result) {
        toast(t('relief.dispatched', { id: item.id }), 'success');
        await load();
      }
    } catch (err) {
      toast(`${t('appr.failed')} ${errorMessage(err)}`, 'error');
    }
  };

  return (
    <section className="ns-card ns-stack" aria-labelledby="relief-req-h">
      <h2 id="relief-req-h" className="ns-h3">{t('relief.requests')}</h2>
      <form onSubmit={submit} className="ns-stack" noValidate>
        <h3 className="ns-label">{t('relief.newRequest')}</h3>
        <div className="ns-field">
          <label htmlFor="rr-text">{t('relief.text')}</label>
          <textarea
            id="rr-text"
            className="ns-input"
            rows={3}
            value={text}
            lang={lang}
            onChange={(e) => setText(e.target.value)}
            aria-invalid={formError ? true : undefined}
            aria-describedby={formError ? 'rr-text-err' : undefined}
          />
          {formError && (
            <p id="rr-text-err" className="ns-field-error">
              {formError}
            </p>
          )}
        </div>
        <div className="ns-form-grid">
          <div className="ns-field">
            <label htmlFor="rr-lang">{t('relief.lang')}</label>
            <select id="rr-lang" className="ns-input" value={lang} onChange={(e) => setLang(e.target.value as ReliefRequestInput['lang'])}>
              {REQUEST_LANGS.map((l) => (
                <option key={l} value={l}>
                  {messageLangName(l)}
                </option>
              ))}
            </select>
          </div>
          <div className="ns-field">
            <label htmlFor="rr-need">{t('relief.need')}</label>
            <select id="rr-need" className="ns-input" value={need} onChange={(e) => setNeed(e.target.value as ReliefNeed | '')}>
              <option value="">{t('relief.needAuto')}</option>
              {NEEDS.map((n) => (
                <option key={n} value={n}>
                  {td(`need.${n}`, n)}
                </option>
              ))}
            </select>
          </div>
          <div className="ns-field">
            <label htmlFor="rr-people">{t('relief.people')}</label>
            <input id="rr-people" className="ns-input" type="number" min="0" inputMode="numeric" value={people} onChange={(e) => setPeople(e.target.value)} />
          </div>
          <div className="ns-field">
            <label htmlFor="rr-lat">{t('relief.lat')}</label>
            <input id="rr-lat" className="ns-input" type="number" step="any" inputMode="decimal" value={lat} onChange={(e) => setLat(e.target.value)} />
          </div>
          <div className="ns-field">
            <label htmlFor="rr-lng">{t('relief.lng')}</label>
            <input id="rr-lng" className="ns-input" type="number" step="any" inputMode="decimal" value={lng} onChange={(e) => setLng(e.target.value)} />
          </div>
          <div className="ns-field ns-field--end">
            <button type="button" className="ns-btn ns-btn--secondary" onClick={fillLocation}>
              <LocateFixed className="w-4 h-4" aria-hidden="true" /> {t('relief.useLocation')}
            </button>
          </div>
        </div>
        <p className="ns-hint" id="relief-consent">{t('relief.consent')}</p>
        <button type="submit" className="ns-btn ns-btn--primary" disabled={submitting}>
          <Send className="w-4 h-4" aria-hidden="true" /> {t('relief.submit')}
        </button>
      </form>

      <h3 className="ns-label">{t('relief.list')}</h3>
      {error && <StateNotice kind="error" message={t('relief.loadError')} detail={error} onRetry={() => void load()} />}
      {!error && items === null && <StateNotice kind="loading" message={t('common.loading')} />}
      {!error && items?.length === 0 && <StateNotice kind="empty" message={t('relief.empty')} />}
      {items && items.length > 0 && (
        <ul className="ns-list">
          {items.map((r) => {
            const open = r.status === 'pending_approval' || r.status === 'pending';
            return (
              <li key={r.id} className="ns-list__item ns-stack-sm">
                <div className="ns-row ns-wrap">
                  <span className="ns-strong">#{r.id}</span>
                  <Chip tone={urgencyTone(r.urgency)}>{td(`urgency.${r.urgency}`, r.urgency)}</Chip>
                  <Chip>{td(`need.${r.need}`, r.need)}</Chip>
                  <span className="ns-hint">{t('relief.priority', { p: fmtNum(r.priority, 2) })}</span>
                  {typeof r.people === 'number' && <span className="ns-hint">{t('relief.peopleCount', { n: r.people })}</span>}
                  {r.duplicate_of != null && (
                    <Chip tone="warn">
                      <Copy className="w-4 h-4" aria-hidden="true" /> {t('relief.duplicate', { id: r.duplicate_of })}
                    </Chip>
                  )}
                </div>
                {r.text && <p lang={r.lang}>{r.text}</p>}
                <div className="ns-row ns-wrap ns-hint">
                  <span>{r.status}</span>
                  {r.team && <span>· {r.team}</span>}
                  {r.created_at && <span>· {fmtDateTime(r.created_at)}</span>}
                  {r.parsed_by && <span>· {r.parsed_by}</span>}
                </div>
                {open && (
                  <div className="ns-row ns-wrap">
                    <button type="button" className="ns-btn ns-btn--primary ns-btn--sm" onClick={() => void decide(r, 'approve')}>
                      <Truck className="w-4 h-4" aria-hidden="true" /> {t('relief.dispatch')}
                      <span className="sr-only"> #{r.id}</span>
                    </button>
                    <button type="button" className="ns-btn ns-btn--secondary ns-btn--sm" onClick={() => void decide(r, 'reject')}>
                      <X className="w-4 h-4" aria-hidden="true" /> {t('relief.rejectReq')}
                      <span className="sr-only"> #{r.id}</span>
                    </button>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

// ── Photo check ───────────────────────────────────────────────────────────

function RoadExamples() {
  const { t } = useI18n();
  const { photos } = usePhotos();
  const examples = pickPhotos(photos, ['amritsar-flooded-road-2013', 'mathura-underpass-bus-2016']);
  if (examples.length === 0) return null;
  return (
    <div className="ns-stack-sm">
      <p className="ns-hint">{t('relief.examples')}</p>
      <div className="ns-photo-pair">
        {examples.map((p) => (
          <Photo key={p.id} photo={p} credit="below" caption={<span lang="en">{p.title}. </span>} />
        ))}
      </div>
    </div>
  );
}

interface Pt {
  x: number;
  y: number;
  px: number;
  py: number;
}

function PhotoPanel() {
  const { t } = useI18n();
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [points, setPoints] = useState<Pt[]>([]);
  const [refHeight, setRefHeight] = useState('1.0');
  const [routeId, setRouteId] = useState('');
  const [routeList, setRouteList] = useState<RouteStatus[]>([]);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<PhotoCheckResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const previewRef = useRef<string | null>(null);

  useEffect(() => {
    getRoutes().then(
      (list) => setRouteList(Array.isArray(list) ? list : []),
      () => setRouteList([]),
    );
  }, []);

  useEffect(
    () => () => {
      if (previewRef.current) URL.revokeObjectURL(previewRef.current);
    },
    [],
  );

  const onFile = (f: File | null) => {
    if (previewRef.current) URL.revokeObjectURL(previewRef.current);
    const url = f ? URL.createObjectURL(f) : null;
    previewRef.current = url;
    setFile(f);
    setPreview(url);
    setPoints([]);
    setResult(null);
    setError(null);
  };

  const onImageClick = (event: MouseEvent<HTMLImageElement>) => {
    const img = event.currentTarget;
    const rect = img.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return;
    const fx = (event.clientX - rect.left) / rect.width;
    const fy = (event.clientY - rect.top) / rect.height;
    const pt = { x: fx * (img.naturalWidth || rect.width), y: fy * (img.naturalHeight || rect.height), px: fx * 100, py: fy * 100 };
    setPoints((prev) => (prev.length >= 2 ? [pt] : [...prev, pt]));
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const h = Number(refHeight);
      const res = await photoCheck({
        photo: file,
        refTop: points[0] ?? null,
        refBottom: points[1] ?? null,
        refHeightM: Number.isFinite(h) && h > 0 ? h : 1.0,
        routeId: routeId || null,
      });
      setResult(res);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const overlay = mediaUrl(result?.overlay_url);
  const verdict = result?.passable === 'yes' ? 'passable' : result?.passable === 'no' ? 'blocked' : 'unknown';

  return (
    <section className="ns-card ns-stack" aria-labelledby="relief-photo-h">
      <h2 id="relief-photo-h" className="ns-h3">
        <Camera className="w-5 h-5 ns-inline-icon" aria-hidden="true" /> {t('relief.photo')}
      </h2>
      <p className="ns-muted" id="photo-help">{t('relief.photoHelp')}</p>
      <RoadExamples />
      <form onSubmit={submit} className="ns-stack">
        <div className="ns-field">
          <label htmlFor="pc-file">{t('relief.photoFile')}</label>
          <input
            id="pc-file"
            className="ns-input"
            type="file"
            accept="image/*"
            capture="environment"
            aria-describedby="photo-help"
            onChange={(e) => onFile(e.target.files?.[0] ?? null)}
          />
        </div>
        {preview && (
          <div className="ns-stack-sm">
            <div className="ns-photo">
              <img src={preview} alt={t('relief.photoPreview')} onClick={onImageClick} className="ns-photo__img" />
              {points.map((p, i) => (
                <span key={i} className="ns-photo__pt" style={{ left: `${p.px}%`, top: `${p.py}%` }} aria-hidden="true">
                  {i === 0 ? '▲' : '▼'}
                </span>
              ))}
            </div>
            <div className="ns-row ns-wrap">
              <span className="ns-hint" aria-live="polite">
                <Crosshair className="w-4 h-4 ns-inline-icon" aria-hidden="true" /> {t('relief.points', { n: points.length })}
              </span>
              {points.length > 0 && (
                <button type="button" className="ns-btn ns-btn--ghost ns-btn--sm" onClick={() => setPoints([])}>
                  {t('relief.clearPoints')}
                </button>
              )}
            </div>
          </div>
        )}
        <div className="ns-field">
          <label htmlFor="pc-h">{t('relief.refHeight')}</label>
          <input id="pc-h" className="ns-input" type="number" min="0.1" step="0.05" inputMode="decimal" value={refHeight} onChange={(e) => setRefHeight(e.target.value)} />
        </div>
        <div className="ns-field">
          <label htmlFor="pc-route">{t('relief.road')}</label>
          <select id="pc-route" className="ns-input" value={routeId} onChange={(e) => setRouteId(e.target.value)}>
            <option value="">{t('relief.roadNone')}</option>
            {routeList.map((r) => (
              <option key={r.id} value={r.id}>{r.name}</option>
            ))}
          </select>
        </div>
        <button type="submit" className="ns-btn ns-btn--primary" disabled={!file || busy}>
          {busy ? t('relief.checking') : t('relief.check')}
        </button>
      </form>
      <div aria-live="polite">
        {error && <StateNotice kind="error" message={t('relief.photoError')} detail={error} />}
        {result && (
          <div className="ns-stack">
            <h3 className="ns-label">{t('relief.result')}</h3>
            {overlay && (
              <figure className="ns-frame">
                <img src={overlay} alt={t('relief.overlayAlt')} className="ns-frame__img" />
              </figure>
            )}
            <dl className="ns-kv">
              <div>
                <dt>{t('relief.verdict')}</dt>
                <dd>
                  <Chip tone={verdict === 'passable' ? 'ok' : verdict === 'blocked' ? 'danger' : 'neutral'}>{t(`route.${verdict}`)}</Chip>
                </dd>
              </div>
              <div>
                <dt>{t('relief.depth')}</dt>
                <dd className="ns-strong">
                  {typeof result.est_depth_m === 'number'
                    ? `${fmtNum(result.est_depth_m)} m${typeof result.depth_pm_m === 'number' ? ` ± ${fmtNum(result.depth_pm_m)}` : ''}`
                    : '–'}
                </dd>
              </div>
              <div>
                <dt>{t('relief.confidence')}</dt>
                <dd>{typeof result.confidence === 'number' ? `${Math.round(result.confidence * 100)}%` : '–'}</dd>
              </div>
            </dl>
            {result.needs_review !== false && <p className="ns-callout ns-callout--warn">{t('relief.needsReview')}</p>}
            {typeof result.approval_id === 'number' && (
              <p className="ns-callout">
                {t('relief.routeDrafted')} <Link to="/approvals">#{result.approval_id}</Link>
              </p>
            )}
            {typeof result.faces_blurred === 'number' && result.faces_blurred > 0 && (
              <p className="ns-hint">{t('relief.facesBlurred', { n: result.faces_blurred })}</p>
            )}
          </div>
        )}
      </div>
    </section>
  );
}

// ── Route board and shelters ──────────────────────────────────────────────

function BoardPanel() {
  const { t, td } = useI18n();
  const [routes, setRoutes] = useState<RouteStatus[] | null>(null);
  const [routesError, setRoutesError] = useState<string | null>(null);
  const [region, setRegion] = useState('');
  const [shelters, setShelters] = useState<Shelter[] | null>(null);
  const [sheltersError, setSheltersError] = useState<string | null>(null);

  const loadRoutes = useCallback(
    () =>
      getRoutes().then(
        (list) => {
          setRoutes(Array.isArray(list) ? list : []);
          setRoutesError(null);
        },
        (err: unknown) => setRoutesError(errorMessage(err)),
      ),
    [],
  );

  const loadShelters = useCallback(
    (r: string) =>
      getShelters(r || null).then(
        (list) => {
          setShelters(Array.isArray(list) ? list : []);
          setSheltersError(null);
        },
        (err: unknown) => setSheltersError(errorMessage(err)),
      ),
    [],
  );

  useEffect(() => {
    void loadRoutes();
  }, [loadRoutes]);
  useEffect(() => {
    void loadShelters(region);
  }, [loadShelters, region]);

  return (
    <div className="ns-stack">
      <section className="ns-card ns-stack" aria-labelledby="relief-routes-h">
        <h2 id="relief-routes-h" className="ns-h3">
          <Route className="w-5 h-5 ns-inline-icon" aria-hidden="true" /> {t('relief.routes')}
        </h2>
        {routesError && <StateNotice kind="error" message={t('relief.loadError')} detail={routesError} onRetry={() => void loadRoutes()} />}
        {!routesError && routes === null && <StateNotice kind="loading" message={t('common.loading')} />}
        {!routesError && routes?.length === 0 && <StateNotice kind="empty" message={t('relief.routesEmpty')} />}
        {routes && routes.length > 0 && (
          <table className="ns-dtable ns-dtable--flat">
            <thead>
              <tr>
                <th scope="col">{t('relief.colRoad')}</th>
                <th scope="col">{t('relief.colStatus')}</th>
                <th scope="col" className="ns-num">{t('relief.colUpdated')}</th>
              </tr>
            </thead>
            <tbody>
              {routes.map((r) => {
                const tone = r.status === 'passable' ? 'ok' : r.status === 'blocked' ? 'danger' : 'neutral';
                return (
                  <tr key={r.id}>
                    <td>
                      <span className="ns-strong">{r.name}</span>
                      {r.source && <span className="ns-hint ns-block">{r.source}</span>}
                    </td>
                    <td>
                      <span className="ns-row ns-wrap ns-gap-sm">
                        <Chip tone={tone}>{td(`route.${r.status}`, r.status)}</Chip>
                        {r.verified ? (
                          <Chip tone="ok">
                            <CheckCircle2 className="w-4 h-4" aria-hidden="true" /> {t('relief.verified')}
                          </Chip>
                        ) : (
                          <Chip>{t('relief.unverified')}</Chip>
                        )}
                      </span>
                    </td>
                    <td className="ns-num">{fmtDateTime(r.updated_at)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </section>

      <section className="ns-card ns-stack" aria-labelledby="relief-shelters-h">
        <div className="ns-card__head">
          <h2 id="relief-shelters-h" className="ns-h3">
            <Home className="w-5 h-5 ns-inline-icon" aria-hidden="true" /> {t('relief.shelters')}
          </h2>
          <div className="ns-field ns-field--inline">
            <label htmlFor="sh-region">{t('relief.region')}</label>
            <select id="sh-region" className="ns-input" value={region} onChange={(e) => setRegion(e.target.value)}>
              <option value="">{t('relief.allRegions')}</option>
              <option value="np">{t('country.NP')}</option>
              <option value="in">{t('country.IN')}</option>
            </select>
          </div>
        </div>
        {sheltersError && <StateNotice kind="error" message={t('relief.loadError')} detail={sheltersError} onRetry={() => void loadShelters(region)} />}
        {!sheltersError && shelters === null && <StateNotice kind="loading" message={t('common.loading')} />}
        {!sheltersError && shelters?.length === 0 && <StateNotice kind="empty" message={t('relief.sheltersEmpty')} />}
        {shelters && shelters.length > 0 && (
          <table className="ns-dtable ns-dtable--flat">
            <thead>
              <tr>
                <th scope="col">{t('relief.colShelter')}</th>
                <th scope="col" className="ns-num">{t('relief.colPlaces')}</th>
              </tr>
            </thead>
            <tbody>
              {shelters.map((s) => {
                const cap = typeof s.capacity === 'number' ? s.capacity : null;
                const occ = typeof s.occupancy === 'number' ? s.occupancy : null;
                const pct = cap && occ !== null ? Math.min(100, Math.round((occ / cap) * 100)) : null;
                return (
                  <tr key={s.id}>
                    <td>
                      <span className="ns-strong">{s.name}</span>
                      <span className="ns-hint ns-block">
                        {s.admin_unit}
                        {s.region_id ? ` · ${td(`country.${s.region_id.toUpperCase()}`, s.region_id)}` : ''}
                      </span>
                    </td>
                    <td className="ns-num">
                      {cap !== null && occ !== null ? (
                        <>
                          {occ} / {cap}
                          <meter className="ns-meter" min={0} max={cap} low={cap * 0.7} high={cap * 0.9} optimum={0} value={occ} aria-label={t('relief.occupancy', { occ, cap })}>
                            {pct}%
                          </meter>
                        </>
                      ) : (
                        '–'
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}

function ReliefPhotos() {
  const { t } = useI18n();
  const { photos } = usePhotos();
  const shown = pickPhotos(photos, ['bihar-ndrf-rescue-2008', 'kerala-rescue-boats-2018']);
  if (shown.length === 0) return null;
  return (
    <section className="ns-relief-photos" aria-label={t('relief.inTheField')}>
      {shown.map((p) => (
        <Photo key={p.id} photo={p} credit="below" caption={<span lang="en">{p.title}{p.place ? `, ${p.place}` : ''}. </span>} />
      ))}
      <p className="ns-relief-photos__note">{t('relief.inTheField')}</p>
    </section>
  );
}

export default function Relief() {
  const { t } = useI18n();
  return (
    <div className="ns-page">
      <PageHeader title={t('relief.title')} subtitle={t('relief.subtitle')} />
      <ReliefPhotos />
      <div className="ns-relief-grid">
        <RequestsPanel />
        <div className="ns-stack">
          <PhotoPanel />
          <BoardPanel />
        </div>
      </div>
    </div>
  );
}
