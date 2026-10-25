import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { AlertTriangle, Inbox, Loader2, RefreshCw } from 'lucide-react';
import { useI18n } from '../i18n';

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <div className="ns-page-header">
      <div className="min-w-0">
        <h2 className="ns-h2">{title}</h2>
        {subtitle && <p className="ns-muted">{subtitle}</p>}
      </div>
      {actions && <div className="ns-row">{actions}</div>}
    </div>
  );
}

/** Loading / empty / error notice. Never blank, always says what to do next. */
export function StateNotice({
  kind,
  message,
  detail,
  onRetry,
}: {
  kind: 'loading' | 'empty' | 'error';
  message: string;
  detail?: string;
  onRetry?: () => void;
}) {
  const { t } = useI18n();
  const Icon = kind === 'loading' ? Loader2 : kind === 'error' ? AlertTriangle : Inbox;
  return (
    <div className={`ns-notice ns-notice--${kind}`} role="status">
      <Icon className={`w-5 h-5 shrink-0${kind === 'loading' ? ' ns-spin' : ''}`} aria-hidden="true" />
      <div className="min-w-0">
        <p className="ns-notice__msg">{message}</p>
        {kind === 'error' && <p className="ns-hint">{detail ? `${detail}. ` : ''}{t('common.serverHint')}</p>}
        {kind !== 'error' && detail && <p className="ns-hint">{detail}</p>}
      </div>
      {onRetry && kind === 'error' && (
        <button type="button" className="ns-btn ns-btn--secondary ns-btn--sm" onClick={onRetry}>
          <RefreshCw className="w-4 h-4" aria-hidden="true" /> {t('common.retry')}
        </button>
      )}
    </div>
  );
}

export function Chip({ tone = 'neutral', children, title }: { tone?: 'neutral' | 'info' | 'ok' | 'warn' | 'danger' | 'replay'; children: ReactNode; title?: string }) {
  return (
    <span className={`ns-chip ns-chip--${tone}`} title={title}>
      {children}
    </span>
  );
}

const BRANCH_TONE: Record<string, 'info' | 'ok' | 'warn' | 'danger'> = {
  D1: 'warn',
  D2: 'info',
  D3: 'info',
  D4: 'warn',
  D5: 'warn',
  D6: 'danger',
  D7: 'danger',
  D8: 'warn',
  D9: 'ok',
};

/** A decision-branch chip (D1–D9). Its plain-language name is visible or available to screen readers. */
export function BranchChip({ branch, to, showName = false }: { branch: string; to?: string; showName?: boolean }) {
  const { td } = useI18n();
  const name = td(`branch.${branch}`, branch);
  const content = (
    <>
      <span className="ns-branch__id">{branch}</span>
      {showName ? <span className="ns-branch__name">{name}</span> : <span className="sr-only">: {name}</span>}
    </>
  );
  const className = `ns-branch ns-chip ns-chip--${BRANCH_TONE[branch] ?? 'neutral'}`;
  if (to) {
    return (
      <Link to={to} className={className} title={name}>
        {content}
      </Link>
    );
  }
  return (
    <span className={className} title={name}>
      {content}
    </span>
  );
}

export function ModeChip({ mode }: { mode?: string | null }) {
  const { td, t } = useI18n();
  if (!mode) return <Chip>{t('common.unknown')}</Chip>;
  const tone = mode === 'alert' ? 'danger' : mode === 'watch' ? 'warn' : mode === 'degraded' ? 'neutral' : 'ok';
  return <Chip tone={tone}>{td(`mode.${mode}`, mode)}</Chip>;
}
