import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import createFetchMock from 'vitest-fetch-mock';
import { cleanup, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import Home from './Home';
import { useLangStore } from '../i18n';
import { resetPhotoCache } from '../lib/photos';
import { barWidths, datasetKind, showValue } from '../lib/evidence';

// store.ts (source of API_BASE) opens IndexedDB on import; jsdom has none.
vi.mock('../lib/idb', () => ({
  attachmentToFile: vi.fn(),
  getPendingReports: vi.fn(async () => []),
  deleteReportOffline: vi.fn(),
  saveReportOffline: vi.fn(),
  toPendingAttachment: vi.fn(),
}));

const fetchMocker = createFetchMock(vi);

const EVIDENCE = {
  generated_from: ['eval/results/a.json', 'eval/results/b.json'],
  items: [
    {
      key: 'real_full_mae',
      label: 'Stage error on real USGS staff-gauge cameras',
      value: 10.61,
      unit: 'cm',
      baseline: { name: 'original PIL heuristic', value: 99.25 },
      dataset: 'REAL, 115 in-range frames, 2 sites',
    },
    {
      key: 'guard_catch',
      label: 'Bad VLM replies caught',
      value: 1.0,
      unit: 'fraction',
      baseline: null,
      dataset: 'SYNTHETIC danger-level burst',
    },
  ],
};

const PHOTOS = [
  {
    id: 'bihar-kosi-flood-2008',
    title: 'Flooded farmland in northern Bihar during the 2008 Kosi flood',
    place: 'Northern Bihar, Kosi basin',
    kind: 'flood-scene',
    alt_en: 'Electricity pylons stand in wide floodwater.',
    alt_hi: 'बाढ़ के पानी में खड़े बिजली के टावर।',
    author: 'Manoj nav',
    license: 'CC BY 3.0',
    license_url: 'https://creativecommons.org/licenses/by/3.0',
    source_url: 'https://commons.wikimedia.org/wiki/File:Flooded_Bihar.JPG',
    web: { large: '/images/india/bihar-kosi-flood-2008-1600.webp', small: '/images/india/bihar-kosi-flood-2008-800.webp' },
  },
];

function respond(url: string) {
  if (url.includes('/images/india/credits.json')) return JSON.stringify(PHOTOS);
  if (url.includes('/evidence')) return JSON.stringify(EVIDENCE);
  return JSON.stringify([]);
}

function renderHome() {
  return render(
    <MemoryRouter>
      <Home />
    </MemoryRouter>,
  );
}

describe('Home page', () => {
  beforeEach(() => {
    fetchMocker.enableMocks();
    fetchMocker.resetMocks();
    resetPhotoCache();
    useLangStore.getState().setLang('en');
  });
  afterEach(() => {
    cleanup();
    fetchMocker.disableMocks();
  });

  it('explains the product and links to the replay and the story', async () => {
    fetchMocker.mockResponse((req) => respond(req.url));
    renderHome();
    expect(screen.getByRole('heading', { level: 1 }).textContent).toMatch(/The Koshi reaches Bihar\s+hours\s+after Nepal sees it rise\./);
    expect(screen.getAllByRole('link', { name: /watch a replay/i })[0].getAttribute('href')).toBe('/live');
    expect(screen.getAllByRole('link', { name: /read the story/i })[0].getAttribute('href')).toBe('/story');
    expect(screen.getByRole('heading', { name: 'Reads the gauge' })).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Decides what to check next' })).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Approves every alert' })).toBeTruthy();
    // The dark statement is present in full for screen readers and reduced motion.
    expect(screen.getByText(/661,295/).closest('p')?.textContent).toContain('The water had passed Chatara hours earlier.');
  });

  it('shows live evidence numbers with their baselines', async () => {
    fetchMocker.mockResponse((req) => respond(req.url));
    renderHome();
    expect(await screen.findByText('Stage error on real USGS staff-gauge cameras')).toBeTruthy();
    expect(screen.getByText('10.6')).toBeTruthy();
    expect(screen.getByText('99.3 cm')).toBeTruthy();
    expect(screen.getByText('(original PIL heuristic)')).toBeTruthy();
    expect(screen.getByText('100')).toBeTruthy();
    expect(screen.getByText('No baseline for this result.')).toBeTruthy();
    expect(screen.getByText('Real data')).toBeTruthy();
    expect(screen.getByText('From 2 result files on the server.')).toBeTruthy();
  });

  it('shows the hero photo with a visible credit linking to /credits', async () => {
    fetchMocker.mockResponse((req) => respond(req.url));
    renderHome();
    const img = await screen.findByAltText('Electricity pylons stand in wide floodwater.');
    expect(img.getAttribute('src')).toBe('/images/india/bihar-kosi-flood-2008-1600.webp');
    const credit = screen.getByRole('link', { name: 'Kosi flood, Bihar, 2008 · Photo Manoj nav · CC BY 3.0' });
    expect(credit.getAttribute('href')).toBe('/credits');
  });

  it('stays useful when the evidence API fails', async () => {
    fetchMocker.mockReject(new Error('network down'));
    renderHome();
    expect(await screen.findByText('The server did not send the results.')).toBeTruthy();
    expect(screen.getByRole('button', { name: /try again/i })).toBeTruthy();
    // The headline and calls to action do not depend on the API.
    expect(screen.getByRole('heading', { level: 1 })).toBeTruthy();
    expect(screen.getAllByRole('link', { name: /watch a replay/i }).length).toBeGreaterThan(0);
  });

  it('treats an HTTP error from the evidence API as an error state', async () => {
    fetchMocker.mockResponse((req) =>
      req.url.includes('/evidence') ? { body: JSON.stringify({ detail: 'Not Found' }), status: 404 } : respond(req.url),
    );
    renderHome();
    expect(await screen.findByText('The server did not send the results.')).toBeTruthy();
    expect(screen.getByText(/Not Found/)).toBeTruthy();
  });
});

describe('evidence formatting', () => {
  it('converts units for readers', () => {
    expect(showValue(8.03, 'cm')).toEqual({ value: '8.0', unit: 'cm' });
    expect(showValue(1, 'fraction')).toEqual({ value: '100', unit: '%' });
    expect(showValue(510, 'min')).toEqual({ value: '8.5', unit: 'h' });
    expect(showValue(0.4458, 'USD')).toEqual({ value: '$0.45', unit: '' });
    expect(showValue(36, 'runs')).toEqual({ value: '36', unit: 'runs' });
  });

  it('scales the comparison bars to the larger value', () => {
    expect(barWidths({ key: 'k', label: 'l', value: 10, baseline: { name: 'b', value: 40 } })).toEqual({ self: 25, base: 100 });
    expect(barWidths({ key: 'k', label: 'l', value: 0, baseline: { name: 'b', value: 0 } })).toEqual({ self: 0, base: 0 });
    expect(barWidths({ key: 'k', label: 'l', value: 3 })).toBeNull();
  });

  it('labels real and synthetic datasets', () => {
    expect(datasetKind('REAL USGS gauge pairs')).toBe('real');
    expect(datasetKind('SYNTHETIC test seeds')).toBe('synthetic');
    expect(datasetKind('other')).toBeNull();
  });
});
