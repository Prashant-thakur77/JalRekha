import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import createFetchMock from 'vitest-fetch-mock';
import { cleanup, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import Credits from './Credits';
import { useLangStore } from '../i18n';
import { resetPhotoCache } from '../lib/photos';

vi.mock('../lib/idb', () => ({
  attachmentToFile: vi.fn(),
  getPendingReports: vi.fn(async () => []),
  deleteReportOffline: vi.fn(),
  saveReportOffline: vi.fn(),
  toPendingAttachment: vi.fn(),
}));

const fetchMocker = createFetchMock(vi);

const PHOTOS = [
  {
    id: 'a',
    title: 'Flooded road in Amritsar',
    place: 'Amritsar',
    kind: 'flooded-road',
    alt_en: 'A flooded road.',
    author: 'Nitin Chandra',
    license: 'CC0',
    license_url: 'https://creativecommons.org/publicdomain/zero/1.0/',
    source_url: 'https://commons.wikimedia.org/wiki/File:A.jpg',
    web: { large: '/images/india/a-1600.webp', small: '/images/india/a-800.webp' },
  },
  {
    id: 'b',
    title: 'Koshi Barrage at golden hour',
    kind: 'river',
    alt_en: 'The barrage at sunset.',
    author: 'Khan Anas333',
    license: 'CC BY-SA 4.0',
    license_url: 'https://creativecommons.org/licenses/by-sa/4.0',
    source_url: 'https://commons.wikimedia.org/wiki/File:B.jpg',
    web: { large: '/images/india/b-1600.webp' },
  },
];

describe('Credits page', () => {
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

  it('lists every photo with author, licence link and source', async () => {
    fetchMocker.mockResponse((req) => (req.url.includes('credits.json') ? JSON.stringify(PHOTOS) : '[]'));
    render(
      <MemoryRouter>
        <Credits />
      </MemoryRouter>,
    );
    expect(await screen.findByText('Flooded road in Amritsar')).toBeTruthy();
    expect(screen.getByText('Koshi Barrage at golden hour')).toBeTruthy();
    expect(screen.getByText('Photo: Nitin Chandra')).toBeTruthy();
    expect(screen.getByText('Photo: Khan Anas333')).toBeTruthy();
    expect(screen.getByRole('link', { name: 'CC0' }).getAttribute('href')).toBe(PHOTOS[0].license_url);
    expect(screen.getByRole('link', { name: 'CC BY-SA 4.0' }).getAttribute('href')).toBe(PHOTOS[1].license_url);
    const originals = screen.getAllByRole('link', { name: /original/i }).map((a) => a.getAttribute('href'));
    expect(originals).toEqual([PHOTOS[0].source_url, PHOTOS[1].source_url]);
    expect(screen.getByRole('link', { name: 'CC BY 4.0' }).getAttribute('href')).toBe('https://creativecommons.org/licenses/by/4.0/');
  });

  it('says so when the photo list cannot be read', async () => {
    fetchMocker.mockReject(new Error('offline'));
    render(
      <MemoryRouter>
        <Credits />
      </MemoryRouter>,
    );
    expect(await screen.findByText('The photo list could not be loaded.')).toBeTruthy();
  });
});
