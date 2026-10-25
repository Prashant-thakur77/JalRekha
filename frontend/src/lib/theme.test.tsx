import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import ThemeToggle from '../components/ThemeToggle';
import { readStoredTheme, THEME_STORAGE_KEY, useThemeStore } from './theme';
import { useLangStore } from '../i18n';

function resetTheme() {
  try {
    window.localStorage.removeItem(THEME_STORAGE_KEY);
  } catch {
    /* ignore */
  }
  document.documentElement.removeAttribute('data-theme');
  useThemeStore.setState({ choice: null, theme: 'light' });
}

describe('theme toggle', () => {
  beforeEach(() => {
    resetTheme();
    useLangStore.getState().setLang('en');
  });
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it('switches to dark, persists the choice and labels the next action', () => {
    render(<ThemeToggle />);
    const button = screen.getByRole('button', { name: 'Switch to dark theme' });
    fireEvent.click(button);
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe('dark');
    expect(readStoredTheme()).toBe('dark');
    expect(screen.getByRole('button', { name: 'Switch to light theme' })).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Switch to light theme' }));
    expect(document.documentElement.getAttribute('data-theme')).toBe('light');
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe('light');
  });

  it('still works when storage throws (private mode)', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    render(<ThemeToggle />);
    expect(() => fireEvent.click(screen.getByRole('button', { name: 'Switch to dark theme' }))).not.toThrow();
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
    expect(useThemeStore.getState().theme).toBe('dark');
    expect(readStoredTheme()).toBeNull();
  });

  it('ignores invalid stored values', () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, 'sepia');
    expect(readStoredTheme()).toBeNull();
  });
});
