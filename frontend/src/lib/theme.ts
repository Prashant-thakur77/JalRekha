import { create } from 'zustand';

/**
 * Light / dark theme. With no saved choice the page follows the system
 * preference (prefers-color-scheme) through CSS alone; once the person picks a
 * theme it is saved in localStorage and written to <html data-theme="...">.
 * Every storage access is wrapped: private windows and sandboxed frames throw.
 */

export type Theme = 'light' | 'dark';

export const THEME_STORAGE_KEY = 'nadisaathi.theme';

function isTheme(value: unknown): value is Theme {
  return value === 'light' || value === 'dark';
}

export function readStoredTheme(): Theme | null {
  try {
    const value = window.localStorage.getItem(THEME_STORAGE_KEY);
    return isTheme(value) ? value : null;
  } catch {
    return null;
  }
}

export function systemTheme(): Theme {
  try {
    return typeof window !== 'undefined' && window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  } catch {
    return 'light';
  }
}

function applyTheme(theme: Theme | null) {
  if (typeof document === 'undefined') return;
  const root = document.documentElement;
  if (theme) root.setAttribute('data-theme', theme);
  else root.removeAttribute('data-theme');
  const resolved = theme ?? systemTheme();
  const meta = document.querySelector('meta[name="theme-color"]:not([media])');
  if (meta) meta.setAttribute('content', resolved === 'dark' ? '#121211' : '#f3f2ee');
}

interface ThemeState {
  /** The person's explicit choice, or null to follow the system. */
  choice: Theme | null;
  /** The theme actually shown. */
  theme: Theme;
  setTheme: (theme: Theme) => void;
  toggle: () => void;
  /** Re-read the system preference (used when it changes and there is no choice). */
  syncSystem: () => void;
}

const initialChoice = typeof window === 'undefined' ? null : readStoredTheme();
applyTheme(initialChoice);

export const useThemeStore = create<ThemeState>((set, get) => ({
  choice: initialChoice,
  theme: initialChoice ?? (typeof window === 'undefined' ? 'light' : systemTheme()),
  setTheme: (theme) => {
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, theme);
    } catch {
      // storage blocked: the choice still applies until the tab closes
    }
    applyTheme(theme);
    set({ choice: theme, theme });
  },
  toggle: () => get().setTheme(get().theme === 'dark' ? 'light' : 'dark'),
  syncSystem: () => {
    if (get().choice) return;
    set({ theme: systemTheme() });
  },
}));

/** Keep the resolved theme in step with the OS while there is no explicit choice. */
export function watchSystemTheme(): () => void {
  try {
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const onChange = () => useThemeStore.getState().syncSystem();
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  } catch {
    return () => undefined;
  }
}
