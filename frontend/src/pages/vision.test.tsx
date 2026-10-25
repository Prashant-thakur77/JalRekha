import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import createFetchMock from 'vitest-fetch-mock';
import { cleanup, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import Vision from './Vision';
import { useLangStore } from '../i18n';
import { visionDictionaries } from '../content/vision';
import type { LabSite, VisionLab } from '../api';

vi.mock('../lib/idb', () => ({
  attachmentToFile: vi.fn(),
  getPendingReports: vi.fn(async () => []),
  deleteReportOffline: vi.fn(),
  saveReportOffline: vi.fn(),
  toPendingAttachment: vi.fn(),
}));

const fetchMocker = createFetchMock(vi);
const IMG = 'data:image/jpeg;base64,AAAA';
const ROWS = 20;
const axis = Array.from({ length: ROWS }, (_, i) => 6 - i * 0.1);
const step = (at: number) => Array.from({ length: ROWS }, (_, i) => (i < at ? 2 : 0.5));

const SITES: LabSite[] = [
  { site_id: 'koshi-chatara-cam', kind: 'scenario', name: 'Chatara river camera', cycles: 12, latest_trace_id: 'tr_fixture', latest_at: '2026-08-14T22:00:00Z' },
  { site_id: 'hancock-usgs-cam', kind: 'real', name: 'Hancock', cycles: 0, latest_trace_id: null, latest_at: null },
];

const LAB: VisionLab = {
  schema: 'jalrekha-vision-lab-v1',
  opencv_version: '5.0.0',
  summary: { stage_m: 5.12, sigma_m: 0.03, usable: true, frames: 5, overlay_image: IMG },
  quality: {
    ok: true,
    reasons: [],
    heatmap_image: IMG,
    metrics: [
      { key: 'blur_var', value: 372.8, threshold: 25, rule: 'min', pass: true, op: 'cv2.Laplacian(strip, CV_64F).var()' },
      { key: 'glare_frac', value: 0.31, threshold: 0.25, rule: 'max', pass: false, op: 'share of strip pixels at 250 or above' },
    ],
  },
  registration: {
    ok: true, method: 'orb', inliers: 607, residual_px: 0.748, drift_px: 5.17, ms: 133, tried: ['orb'], reference: 'calibration',
    matcher: 'orb', keypoints_current: 1500, keypoints_reference: 1500, matches: 678, inliers_drawn: 60,
    matches_image: IMG, compare_image: IMG,
  },
  strip: { rows: ROWS, width_px: 29, frames: 5, last_image: IMG, median_image: IMG },
  profiles: {
    rows: ROWS,
    axis_m: axis,
    warning_m: 5.5,
    danger_m: 6.4,
    metres_per_px: 0.01,
    estimators: [
      { name: 'E1_edge', row: 9, stage_m: 5.1, confidence: 0.92, separation: 3.86, used: true, weight: 0.32, op: 'cv2.Scharr', signal: step(9) },
      { name: 'E2_temporal', row: 10, stage_m: 5.0, confidence: 0.86, separation: 2.99, used: true, weight: 0.6, op: 'cv2.DISOpticalFlow', signal: step(10) },
      { name: 'E3_colour', row: 9, stage_m: 5.12, confidence: 0.5, separation: 1.4, used: true, weight: 0.5, op: 'cv2.cvtColor', signal: step(9) },
    ],
  },
  fusion: {
    per_estimator_m: { E1_edge: 5.1, E2_temporal: 5.0, E3_colour: 5.12 },
    fused_m: 5.12, sigma_m: 0.05, confidence: 0.8, spread_m: 0.12, used: ['E1_edge', 'E2_temporal', 'E3_colour'],
    agreeing: ['E1_edge', 'E3_colour'], tolerance_m: 0.1,
    consensus: { agreed: true, members: ['E1_edge', 'E3_colour'], sigma_m: 0.015 },
    kalman: { filtered_stage_m: 5.08, rate_m_per_h: 0.42 },
  },
  timing: {
    stages: [
      { name: 'register', ms: 133.0, start_ms: 0 },
      { name: 'warp', ms: 6.4, start_ms: 133 },
      { name: 'E2_temporal', ms: 5.1, start_ms: 139.4 },
    ],
    total_ms: 282.5,
    host: { machine: 'x86_64', opencv: '5.0.0', cpu_count: 20, cpu_features: ['Baseline: SSE SSE2 SSE3'], hal: ['Custom HAL: YES (ipp (ver 0.0.1))'], kleidicv: false },
    cycle_ms: { total: 290.1 },
  },
  privacy: { faces: 0, plates: 0, face_detector: 'yunet', plate_detector: 'lpd_yunet', mode: 'detect_and_blur' },
  source: { kind: 'scenario', title: 'Koshi', t_min: 245 },
  check: { recorded_stage_m: 5.12, rebuilt_stage_m: 5.12, match: true },
  trace: { trace_id: 'tr_fixture', site_id: 'koshi-chatara-cam', site_name: 'Chatara river camera', cycle: 7, started_at: '2026-08-14T22:05:00Z', truth_stage_m: 5.1 },
  neighbours: { prev: 'tr_before', next: null },
};

function respond(sites: LabSite[], lab: VisionLab | null) {
  fetchMocker.mockResponse((req) => {
    if (req.url.includes('/vision/lab/sites')) return JSON.stringify(sites);
    if (req.url.includes('/vision/lab/')) {
      return lab ? JSON.stringify(lab) : { status: 404, body: JSON.stringify({ detail: 'no agent cycles for this site yet; run a replay first' }) };
    }
    return JSON.stringify({});
  });
}

describe('Vision Lab page', () => {
  beforeEach(() => {
    fetchMocker.enableMocks();
    fetchMocker.resetMocks();
    useLangStore.getState().setLang('en');
  });
  afterEach(() => {
    cleanup();
    fetchMocker.disableMocks();
  });

  it('renders all six stages from a lab payload', async () => {
    respond(SITES, LAB);
    render(
      <MemoryRouter initialEntries={['/vision']}>
        <Vision />
      </MemoryRouter>,
    );
    expect(await screen.findByRole('heading', { name: /Quality gate/ })).toBeTruthy();
    const headings = screen.getAllByRole('heading').map((h) => h.textContent);
    ['Quality gate', 'Registration', 'Gauge strip', 'Waterline estimators', 'Fusion', 'Timing'].forEach((title, i) =>
      expect(headings).toContain(`Stage ${i + 1}: ${title}`),
    );
    // The latest cycle of the first camera with data was requested.
    expect(fetchMocker.requests().some((r) => r.url.includes('/vision/lab/latest?site_id=koshi-chatara-cam'))).toBe(true);
    // Quality: a failing metric is marked, thresholds are shown.
    expect(screen.getByText('Fail')).toBeTruthy();
    expect(screen.getByText('≥ 25.0')).toBeTruthy();
    // Registration numbers and the three profile charts with a lime waterline mark each.
    expect(screen.getByText('607')).toBeTruthy();
    expect(screen.getAllByRole('img', { name: /signal along the gauge from 6.00 m to 4.10 m/ })).toHaveLength(3);
    expect(document.querySelectorAll('.ns-profile__mark')).toHaveLength(3);
    expect(document.querySelectorAll('.ns-profile__fused')).toHaveLength(3);
    // Fusion verdict and the Kalman value from the trace.
    expect(screen.getByText('Agreed: E1 · edges, E3 · colour are within 10 cm.')).toBeTruthy();
    expect(screen.getByText('5.08 m, +0.42 m/h')).toBeTruthy();
    // Timing waterfall: one row per stage plus the total, bars scaled to the total.
    const rows = document.querySelectorAll('.ns-wf__row');
    expect(rows).toHaveLength(4);
    const bar = document.querySelector<HTMLElement>('.ns-wf__bar')!;
    expect(parseFloat(bar.style.width)).toBeCloseTo((133 / 282.5) * 100, 1);
    expect(screen.getByText('Same reading as the stored trace')).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Open agent trace' }).getAttribute('href')).toBe('/traces/tr_fixture');
  });

  it('asks for a replay when no camera has cycles yet', async () => {
    respond(SITES.map((s) => ({ ...s, cycles: 0, latest_trace_id: null })), null);
    render(
      <MemoryRouter initialEntries={['/vision']}>
        <Vision />
      </MemoryRouter>,
    );
    expect(await screen.findByText('Run a replay first.')).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Go to Live' }).getAttribute('href')).toBe('/live');
  });

  it('shows the single-frame note when a camera sends no burst', async () => {
    const single: VisionLab = {
      ...LAB,
      strip: { ...LAB.strip, frames: 1 },
      profiles: {
        ...LAB.profiles,
        estimators: LAB.profiles.estimators.map((e) => (e.name === 'E2_temporal' ? { ...e, row: null, stage_m: null, signal: null, used: false } : e)),
      },
    };
    respond(SITES, single);
    render(
      <MemoryRouter initialEntries={['/vision?trace=tr_fixture']}>
        <Vision />
      </MemoryRouter>,
    );
    expect(await screen.findByText(/This camera sends one frame per cycle/)).toBeTruthy();
    expect(screen.getAllByText('One frame, no burst').length).toBeGreaterThan(0);
  });
});

describe('Vision Lab strings', () => {
  const enKeys = Object.keys(visionDictionaries.en).sort();
  const holes = (s: string) => (s.match(/\{(\w+)\}/g) ?? []).sort().join();
  it.each(['hi', 'ne'] as const)('%s has every English key with the same placeholders', (lang) => {
    const dict = visionDictionaries[lang];
    expect(Object.keys(dict).sort()).toEqual(enKeys);
    const en = visionDictionaries.en as Record<string, string>;
    expect(enKeys.filter((k) => holes(en[k]) !== holes((dict as Record<string, string>)[k]) || !(dict as Record<string, string>)[k].trim())).toEqual([]);
  });
});
