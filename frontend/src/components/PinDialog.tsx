import { useEffect, useId, useRef, useState, type FormEvent, type KeyboardEvent } from 'react';
import { KeyRound } from 'lucide-react';
import { clearStoredPin, getStoredPin } from '../api';
import { usePinPromptStore, type PinPromptOptions, type PinPromptResult } from '../lib/pinPrompt';
import { useI18n } from '../i18n';

const OPERATOR_KEY = 'nadisaathi.operatorName';

function readOperator(): string {
  try {
    return window.localStorage.getItem(OPERATOR_KEY) ?? '';
  } catch {
    return '';
  }
}

function saveOperator(name: string) {
  try {
    window.localStorage.setItem(OPERATOR_KEY, name);
  } catch {
    // ignore
  }
}

/** Mounted once in the Layout; renders the operator dialog when something asks for a PIN. */
export default function PinDialogHost() {
  const pending = usePinPromptStore((s) => s.pending);
  const settle = usePinPromptStore((s) => s.settle);
  if (!pending) return null;
  return <PinDialog key={pending.id} options={pending.options} onDone={settle} />;
}

function PinDialog({ options, onDone }: { options: PinPromptOptions; onDone: (r: PinPromptResult | null) => void }) {
  const { t } = useI18n();
  const ids = useId();
  const [pin, setPin] = useState(() => (options.error ? '' : getStoredPin() ?? ''));
  const [operator, setOperator] = useState(readOperator);
  const [note, setNote] = useState('');
  const [extra, setExtra] = useState(options.extra?.defaultValue ?? '');
  const [error, setError] = useState(options.error ?? '');
  const boxRef = useRef<HTMLDivElement>(null);
  const firstFieldRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    firstFieldRef.current?.focus();
    return () => {
      if (previous && typeof previous.focus === 'function') previous.focus();
    };
  }, []);

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Escape') {
      event.preventDefault();
      onDone(null);
      return;
    }
    if (event.key !== 'Tab' || !boxRef.current) return;
    const focusables = Array.from(
      boxRef.current.querySelectorAll<HTMLElement>('input, textarea, button, select, [href], [tabindex]:not([tabindex="-1"])'),
    ).filter((el) => !el.hasAttribute('disabled'));
    if (focusables.length === 0) return;
    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!pin.trim()) {
      setError(t('pin.required'));
      return;
    }
    if (options.askOperator) saveOperator(operator.trim());
    onDone({ pin: pin.trim(), operator: operator.trim(), note: note.trim(), extra: extra.trim() });
  };

  const operatorField = options.askOperator ? (
    <div className="ns-field">
      <label htmlFor={`${ids}-op`}>{t('pin.operator')}</label>
      <input
        id={`${ids}-op`}
        ref={firstFieldRef}
        className="ns-input"
        value={operator}
        onChange={(e) => setOperator(e.target.value)}
        autoComplete="name"
        placeholder="Rakesh (DDMA Supaul)"
      />
    </div>
  ) : null;

  return (
    <div className="ns-modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onDone(null)}>
      <div
        ref={boxRef}
        className="ns-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby={`${ids}-title`}
        aria-describedby={`${ids}-help`}
        onKeyDown={onKeyDown}
      >
        <form onSubmit={submit} className="ns-stack">
          <h2 id={`${ids}-title`} className="ns-modal__title">
            <KeyRound className="w-5 h-5" aria-hidden="true" /> {options.title}
          </h2>
          {operatorField}
          {options.extra && (
            <div className="ns-field">
              <label htmlFor={`${ids}-extra`}>{options.extra.label}</label>
              <input id={`${ids}-extra`} className="ns-input" value={extra} onChange={(e) => setExtra(e.target.value)} />
            </div>
          )}
          {options.askNote && (
            <div className="ns-field">
              <label htmlFor={`${ids}-note`}>{t('pin.note')}</label>
              <textarea id={`${ids}-note`} className="ns-input" rows={2} value={note} onChange={(e) => setNote(e.target.value)} />
            </div>
          )}
          <div className="ns-field">
            <label htmlFor={`${ids}-pin`}>{t('pin.label')}</label>
            <input
              id={`${ids}-pin`}
              ref={options.askOperator ? undefined : firstFieldRef}
              className="ns-input ns-input--pin"
              type="password"
              inputMode="numeric"
              autoComplete="off"
              value={pin}
              onChange={(e) => {
                setPin(e.target.value);
                setError('');
              }}
              aria-invalid={error ? true : undefined}
              aria-describedby={`${ids}-help${error ? ` ${ids}-err` : ''}`}
            />
            <p id={`${ids}-help`} className="ns-hint">{t('pin.help')}</p>
            {error && (
              <p id={`${ids}-err`} className="ns-field-error" role="alert">
                {error}
              </p>
            )}
          </div>
          <div className="ns-row ns-row--end">
            {getStoredPin() && (
              <button
                type="button"
                className="ns-btn ns-btn--ghost"
                onClick={() => {
                  clearStoredPin();
                  setPin('');
                }}
              >
                {t('pin.forget')}
              </button>
            )}
            <button type="button" className="ns-btn ns-btn--secondary" onClick={() => onDone(null)}>
              {t('common.cancel')}
            </button>
            <button type="submit" className={`ns-btn ${options.tone === 'danger' ? 'ns-btn--danger' : 'ns-btn--primary'}`}>
              {options.confirmLabel}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
