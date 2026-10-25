import { create } from 'zustand';
import { ApiError, clearStoredPin, setStoredPin } from '../api';

export interface PinPromptOptions {
  title: string;
  confirmLabel: string;
  tone?: 'primary' | 'danger';
  askOperator?: boolean;
  askNote?: boolean;
  /** Optional extra text field, e.g. the relief team name. */
  extra?: { label: string; defaultValue?: string };
  /** Error shown when the dialog opens (e.g. after a wrong PIN). */
  error?: string;
}

export interface PinPromptResult {
  pin: string;
  operator: string;
  note: string;
  extra: string;
}

interface PendingPrompt {
  id: number;
  options: PinPromptOptions;
  resolve: (result: PinPromptResult | null) => void;
}

interface PinPromptState {
  pending: PendingPrompt | null;
  open: (options: PinPromptOptions) => Promise<PinPromptResult | null>;
  settle: (result: PinPromptResult | null) => void;
}

let nextId = 1;

export const usePinPromptStore = create<PinPromptState>((set, get) => ({
  pending: null,
  open: (options) =>
    new Promise((resolve) => {
      get().pending?.resolve(null);
      set({ pending: { id: nextId++, options, resolve } });
    }),
  settle: (result) => {
    const pending = get().pending;
    set({ pending: null });
    pending?.resolve(result);
  },
}));

export function askPin(options: PinPromptOptions) {
  return usePinPromptStore.getState().open(options);
}

/**
 * Ask for the operator PIN, run `call`, and re-ask (up to 3 times) if the
 * server says the PIN is wrong. Resolves to null if the person cancels.
 */
export async function withOperatorPin<T>(
  options: PinPromptOptions,
  call: (answer: PinPromptResult) => Promise<T>,
  wrongPinMessage: string,
): Promise<T | null> {
  let opts = options;
  for (let attempt = 0; attempt < 3; attempt++) {
    const answer = await askPin(opts);
    if (!answer) return null;
    setStoredPin(answer.pin);
    try {
      return await call(answer);
    } catch (err) {
      if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
        clearStoredPin();
        opts = { ...options, error: wrongPinMessage };
        continue;
      }
      throw err;
    }
  }
  return null;
}
