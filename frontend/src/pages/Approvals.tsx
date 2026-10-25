import { useCallback, useEffect, useId, useState, type KeyboardEvent } from 'react';
import { Link } from 'react-router-dom';
import { Check, Clock, FileCode2, RefreshCw, Users, Volume2, X } from 'lucide-react';
import {
  decideApproval,
  errorMessage,
  getApprovals,
  mediaUrl,
  parseTraceSource,
  type Approval,
} from '../api';
import { messageLangName, useI18n } from '../i18n';
import { smsInfo } from '../lib/sms';
import { fmtDateTime, fmtHours } from '../lib/format';
import { toast } from '../lib/toast';
import { withOperatorPin } from '../lib/pinPrompt';
import { Chip, PageHeader, StateNotice } from '../components/ui';

type Tab = 'pending' | 'decided';

function traceHref(source?: string | null): string | null {
  const parsed = parseTraceSource(source);
  if (!parsed) return null;
  return `/traces/${encodeURIComponent(parsed.traceId)}${parsed.step !== null ? `#step-${parsed.step}` : ''}`;
}

function MessageEditor({
  lang,
  value,
  original,
  onChange,
  readOnly,
}: {
  lang: string;
  value: string;
  original: string;
  onChange: (text: string) => void;
  readOnly: boolean;
}) {
  const { t } = useI18n();
  const id = useId();
  const info = smsInfo(value);
  const langName = messageLangName(lang);
  return (
    <div className="ns-field">
      <label htmlFor={id} className="ns-row ns-gap-sm">
        {t('appr.messageFor', { lang: langName })}
        {value !== original && <Chip tone="info">{t('appr.edited')}</Chip>}
      </label>
      <textarea
        id={id}
        lang={lang}
        className="ns-input ns-message"
        rows={4}
        value={value}
        readOnly={readOnly}
        onChange={(e) => onChange(e.target.value)}
        aria-describedby={`${id}-count`}
      />
      <p id={`${id}-count`} className="ns-hint ns-counter">
        {t('appr.chars', { n: info.chars })} · {t('appr.segments', { n: info.segments })} · {info.encoding}
      </p>
    </div>
  );
}

function ApprovalCard({ item, onDecided }: { item: Approval; onDecided: () => void }) {
  const { t, td } = useI18n();
  const messages = item.payload?.messages ?? [];
  const [drafts, setDrafts] = useState<Record<string, string>>(() =>
    Object.fromEntries(messages.map((m) => [m.lang, m.text])),
  );
  const [busy, setBusy] = useState(false);
  const pending = item.status === 'pending';
  const eta = item.payload?.eta;
  const audio = item.payload?.audio ?? [];

  const decide = async (decision: 'approve' | 'reject') => {
    const edited = messages
      .filter((m) => (drafts[m.lang] ?? m.text) !== m.text)
      .map((m) => ({ lang: m.lang, text: drafts[m.lang] }));
    setBusy(true);
    try {
      const result = await withOperatorPin(
        {
          title: t(decision === 'approve' ? 'appr.approveTitle' : 'appr.rejectTitle', { title: item.title }),
          confirmLabel: t(decision === 'approve' ? 'appr.approve' : 'appr.reject'),
          tone: decision === 'approve' ? 'primary' : 'danger',
          askOperator: true,
          askNote: true,
        },
        (answer) =>
          decideApproval(
            item.id,
            {
              decision,
              operator: answer.operator || 'operator',
              note: answer.note,
              ...(edited.length > 0 ? { edited_messages: edited } : {}),
            },
            answer.pin,
          ),
        t('pin.wrong'),
      );
      if (result) {
        toast(`${t('appr.saved')} ${result.title ?? ''}`.trim(), 'success');
        onDecided();
      }
    } catch (err) {
      toast(`${t('appr.failed')} ${errorMessage(err)}`, 'error');
    } finally {
      setBusy(false);
    }
  };

  const statusTone = item.status === 'approved' ? 'ok' : item.status === 'rejected' ? 'danger' : 'warn';
  const statusText =
    item.status === 'approved' ? t('appr.approved') : item.status === 'rejected' ? t('appr.rejected') : t('appr.pending');

  return (
    <article className={`ns-card ns-approval${pending ? ' ns-approval--pending' : ''}`} aria-labelledby={`appr-${item.id}-title`}>
      <header className="ns-stack-sm">
        <div className="ns-row ns-wrap ns-hint">
          <Chip tone={statusTone}>{statusText}</Chip>
          <Chip>{td(`appr.action.${item.action}`, item.action.replace(/_/g, ' '))}</Chip>
          {(item.role_label || item.role) && <span>{item.role_label || item.role}</span>}
          <time dateTime={item.created_at}>{fmtDateTime(item.created_at)}</time>
        </div>
        <h2 id={`appr-${item.id}-title`} className="ns-h3 ns-approval__title">
          {item.title}
        </h2>
      </header>

      {item.rationale && (
        <div>
          <span className="ns-label">{t('appr.rationale')}</span>
          <p>{item.rationale}</p>
        </div>
      )}

      <dl className="ns-kv">
        {eta && (
          <div>
            <dt>
              <Clock className="w-4 h-4 ns-inline-icon" aria-hidden="true" /> {t('appr.eta')}
            </dt>
            <dd className="ns-strong">
              {t('common.etaBand', { min: fmtHours(eta.min), max: fmtHours(eta.max), typ: fmtHours(eta.typ) })}
            </dd>
          </div>
        )}
        {item.payload?.recipients && (
          <div>
            <dt>
              <Users className="w-4 h-4 ns-inline-icon" aria-hidden="true" /> {t('appr.recipients')}
            </dt>
            <dd>{item.payload.recipients}</dd>
          </div>
        )}
      </dl>

      {(item.evidence ?? []).length > 0 && (
        <div>
          <span className="ns-label">{t('appr.evidence')}</span>
          <table className="ns-dtable ns-dtable--flat ns-evidence">
            <tbody>
              {(item.evidence ?? []).map((ev, i) => {
                const href = traceHref(ev.source);
                return (
                  <tr key={`${ev.label}-${i}`}>
                    <th scope="row">
                      {ev.label}
                      {href ? (
                        <span className="ns-block">
                          <Link to={href} className="ns-link ns-mono">
                            {ev.source}
                          </Link>
                        </span>
                      ) : ev.source ? (
                        <span className="ns-hint ns-mono ns-block">{ev.source}</span>
                      ) : null}
                    </th>
                    <td className="ns-num">{ev.value}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {messages.length > 0 && (
        <div className="ns-stack">
          <span className="ns-label">{t('appr.messages')}</span>
          {messages.map((m) => (
            <MessageEditor
              key={m.lang}
              lang={m.lang}
              original={m.text}
              value={drafts[m.lang] ?? m.text}
              readOnly={!pending}
              onChange={(text) => setDrafts((d) => ({ ...d, [m.lang]: text }))}
            />
          ))}
        </div>
      )}

      {audio.length > 0 && (
        <div className="ns-stack-sm">
          {audio.map((a) => {
            const src = mediaUrl(a.url);
            const label = t('appr.audio', { lang: messageLangName(a.lang) });
            return (
              <div key={a.url} className="ns-audio">
                <span className="ns-row ns-gap-sm ns-label">
                  <Volume2 className="w-4 h-4" aria-hidden="true" /> {label}
                </span>
                {src && <audio controls preload="none" src={src} aria-label={label} />}
              </div>
            );
          })}
        </div>
      )}

      {item.payload?.cap_xml && (
        <details className="ns-details">
          <summary>
            <FileCode2 className="w-4 h-4 ns-inline-icon" aria-hidden="true" /> {t('appr.cap')}
          </summary>
          <pre className="ns-pre">{item.payload.cap_xml}</pre>
        </details>
      )}

      {item.trace_id && (
        <Link to={`/traces/${encodeURIComponent(item.trace_id)}`} className="ns-link">
          {t('appr.openTrace')}
        </Link>
      )}

      {!pending && (
        <div className="ns-stack-sm ns-hint">
          {item.decided_by && (
            <p>
              {t('appr.decidedBy', { who: item.decided_by })}
              {item.decided_at ? ` · ${fmtDateTime(item.decided_at)}` : ''}
            </p>
          )}
          {item.decision_note && <p>“{item.decision_note}”</p>}
          {item.dispatch && Object.keys(item.dispatch).length > 0 && (
            <p>
              {t('appr.dispatch')}:{' '}
              {Object.entries(item.dispatch)
                .map(([ch, st]) => `${ch}: ${typeof st === 'string' ? st : JSON.stringify(st)}`)
                .join(' · ')}
            </p>
          )}
        </div>
      )}

      {pending && (
        <div className="ns-actions">
          <button type="button" className="ns-btn ns-btn--secondary ns-btn--lg" disabled={busy} onClick={() => void decide('reject')}>
            <X className="w-5 h-5" aria-hidden="true" /> {t('appr.reject')}
          </button>
          <button type="button" className="ns-btn ns-btn--primary ns-btn--lg" disabled={busy} onClick={() => void decide('approve')}>
            <Check className="w-5 h-5" aria-hidden="true" /> {t('appr.approve')}
          </button>
        </div>
      )}
    </article>
  );
}

export default function Approvals() {
  const { t } = useI18n();
  const [tab, setTab] = useState<Tab>('pending');
  const [items, setItems] = useState<Approval[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const lastRun = (() => {
    try {
      return window.sessionStorage.getItem('nadisaathi.lastRun');
    } catch {
      return null;
    }
  })();
  const [onlyMine, setOnlyMine] = useState<boolean>(Boolean(lastRun));

  const load = useCallback(
    (which: Tab) =>
      getApprovals(which === 'pending' ? 'pending' : 'all').then(
        (list) => {
          const safe = Array.isArray(list) ? list : [];
          setItems(which === 'pending' ? safe.filter((a) => a.status === 'pending') : safe.filter((a) => a.status !== 'pending'));
          setError(null);
        },
        (err: unknown) => setError(errorMessage(err)),
      ),
    [],
  );

  useEffect(() => {
    void load(tab);
  }, [load, tab]);

  const shown = items && onlyMine && lastRun ? items.filter((a) => a.scenario_run_id === lastRun) : items;

  const tabs: Tab[] = ['pending', 'decided'];
  const onTabKey = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (event.key !== 'ArrowRight' && event.key !== 'ArrowLeft') return;
    event.preventDefault();
    const next = tab === 'pending' ? 'decided' : 'pending';
    setItems(null);
    setTab(next);
    document.getElementById(`appr-tab-${next}`)?.focus();
  };

  return (
    <div className="ns-page ns-page--narrow">
      <PageHeader
        title={t('appr.title')}
        subtitle={t('appr.subtitle')}
        actions={
          <button type="button" className="ns-btn ns-btn--secondary" onClick={() => void load(tab)}>
            <RefreshCw className="w-4 h-4" aria-hidden="true" /> {t('common.refresh')}
          </button>
        }
      />
      <div role="tablist" aria-label={t('appr.tabs')} className="ns-tabs">
        {tabs.map((name) => (
          <button
            key={name}
            id={`appr-tab-${name}`}
            type="button"
            role="tab"
            aria-selected={tab === name}
            aria-controls="appr-panel"
            tabIndex={tab === name ? 0 : -1}
            className={`ns-tab${tab === name ? ' ns-tab--active' : ''}`}
            onClick={() => {
              if (name !== tab) {
                setItems(null);
                setTab(name);
              }
            }}
            onKeyDown={onTabKey}
          >
            {name === 'pending' ? t('appr.pending') : t('appr.decided')}
          </button>
        ))}
      </div>
      {lastRun && (
        <label className="ns-row ns-hint" htmlFor="appr-mine">
          <input id="appr-mine" type="checkbox" checked={onlyMine} onChange={(e) => setOnlyMine(e.target.checked)} />{' '}
          {t('appr.onlyMine')}
        </label>
      )}
      <div id="appr-panel" role="tabpanel" aria-labelledby={`appr-tab-${tab}`} className="ns-stack">
        {error && <StateNotice kind="error" message={t('appr.loadError')} detail={error} onRetry={() => void load(tab)} />}
        {!error && shown === null && <StateNotice kind="loading" message={t('common.loading')} />}
        {!error && shown?.length === 0 && (
          <StateNotice kind="empty" message={tab === 'pending' ? t('appr.empty') : t('appr.emptyDecided')} />
        )}
        {shown?.map((item) => (
          <ApprovalCard key={`${item.id}-${item.status}`} item={item} onDecided={() => void load(tab)} />
        ))}
      </div>
    </div>
  );
}
