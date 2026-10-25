import { X } from 'lucide-react';
import { useToastStore } from '../lib/toast';
import { useI18n } from '../i18n';

/** Polite live region for short status messages. Always mounted so screen readers pick it up. */
export default function Toasts() {
  const toasts = useToastStore((s) => s.toasts);
  const dismiss = useToastStore((s) => s.dismiss);
  const { t } = useI18n();
  return (
    <div className="ns-toasts" role="status" aria-live="polite" aria-atomic="false">
      {toasts.map((item) => (
        <div key={item.id} className={`ns-toast ns-toast--${item.kind}`}>
          <span className="ns-toast__text">{item.message}</span>
          <button
            type="button"
            className="ns-icon-btn ns-icon-btn--light"
            onClick={() => dismiss(item.id)}
            aria-label={t('common.dismiss')}
          >
            <X className="w-4 h-4" aria-hidden="true" />
          </button>
        </div>
      ))}
    </div>
  );
}
