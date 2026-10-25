import { create } from 'zustand';

export type ToastKind = 'info' | 'success' | 'error';

export interface Toast {
  id: number;
  kind: ToastKind;
  message: string;
}

interface ToastState {
  toasts: Toast[];
  push: (message: string, kind?: ToastKind) => void;
  dismiss: (id: number) => void;
}

let nextId = 1;

export const useToastStore = create<ToastState>((set, get) => ({
  toasts: [],
  push: (message, kind = 'info') => {
    const id = nextId++;
    set({ toasts: [...get().toasts.slice(-3), { id, kind, message }] });
    setTimeout(() => get().dismiss(id), kind === 'error' ? 8000 : 5000);
  },
  dismiss: (id) => set({ toasts: get().toasts.filter((t) => t.id !== id) }),
}));

/** Show a short, polite status message (announced via an aria-live region). */
export function toast(message: string, kind: ToastKind = 'info') {
  useToastStore.getState().push(message, kind);
}
