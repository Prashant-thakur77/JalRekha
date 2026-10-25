import { describe, it, expect, beforeEach } from 'vitest';
import { dictionaries, translate, useLangStore, type Lang } from './i18n';

const LANGS: Lang[] = ['en', 'hi', 'ne'];
const placeholders = (s: string) => (s.match(/\{(\w+)\}/g) ?? []).sort();

describe('i18n dictionaries', () => {
  const enKeys = Object.keys(dictionaries.en).sort();

  it.each(LANGS)('%s has exactly the English keys', (lang) => {
    expect(Object.keys(dictionaries[lang]).sort()).toEqual(enKeys);
  });

  it.each(LANGS)('%s has no empty strings', (lang) => {
    const empty = Object.entries(dictionaries[lang]).filter(([, v]) => !v.trim());
    expect(empty).toEqual([]);
  });

  it.each(['hi', 'ne'] as Lang[])('%s keeps the same {placeholders} as English', (lang) => {
    const mismatched = enKeys.filter(
      (k) =>
        placeholders(dictionaries.en[k as keyof typeof dictionaries.en]).join() !==
        placeholders(dictionaries[lang][k as keyof typeof dictionaries.en]).join(),
    );
    expect(mismatched).toEqual([]);
  });

  it('interpolates variables', () => {
    expect(translate('en', 'nav.queue', { n: 3 })).toBe('Queue (3)');
    expect(translate('hi', 'nav.queue', { n: 3 })).toBe('कतार (3)');
  });
});

describe('language store', () => {
  beforeEach(() => useLangStore.getState().setLang('en'));

  it('sets document lang and persists the choice', () => {
    useLangStore.getState().setLang('ne');
    expect(document.documentElement.lang).toBe('ne');
    expect(window.localStorage.getItem('nadisaathi.lang')).toBe('ne');
    expect(useLangStore.getState().lang).toBe('ne');
  });
});
