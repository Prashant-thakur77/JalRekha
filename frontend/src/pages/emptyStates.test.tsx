import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import createFetchMock from 'vitest-fetch-mock';
import { cleanup, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import Live from './Live';
import Approvals from './Approvals';
import { useLangStore } from '../i18n';

// store.ts (source of API_BASE) opens IndexedDB on import; jsdom has none.
vi.mock('../lib/idb', () => ({
  attachmentToFile: vi.fn(),
  getPendingReports: vi.fn(async () => []),
  deleteReportOffline: vi.fn(),
  saveReportOffline: vi.fn(),
  toPendingAttachment: vi.fn(),
}));

const fetchMocker = createFetchMock(vi);

function renderAt(ui: React.ReactElement) {
  return render(<MemoryRouter>{ui}</MemoryRouter>);
}

describe('new pages degrade gracefully', () => {
  beforeEach(() => {
    fetchMocker.enableMocks();
    fetchMocker.resetMocks();
    useLangStore.getState().setLang('en');
  });
  afterEach(() => {
    cleanup();
    fetchMocker.disableMocks();
  });

  it('Live shows an error state when the network fails', async () => {
    fetchMocker.mockReject(new Error('network down'));
    renderAt(<Live />);
    expect(await screen.findByText('Could not load scenarios.')).toBeTruthy();
    expect(screen.getByRole('button', { name: /try again/i })).toBeTruthy();
    // The rest of the page still renders its empty states.
    expect(screen.getByText('No replay running. Start one to see the agent work.')).toBeTruthy();
    expect(screen.getByText('No decisions yet. Start a replay to see them here.')).toBeTruthy();
  });

  it('Live shows an empty state when there are no scenarios', async () => {
    fetchMocker.mockResponse(JSON.stringify([]));
    renderAt(<Live />);
    expect(await screen.findByText('No scenarios are available yet.')).toBeTruthy();
  });

  it('Live treats a 404 (backend not deployed yet) as an error, not a crash', async () => {
    fetchMocker.mockResponse(JSON.stringify({ detail: 'Not Found' }), { status: 404 });
    renderAt(<Live />);
    expect(await screen.findByText('Could not load scenarios.')).toBeTruthy();
    expect(screen.getByText(/Not Found/)).toBeTruthy();
  });

  it('Approvals shows an error state when the network fails', async () => {
    fetchMocker.mockReject(new Error('network down'));
    renderAt(<Approvals />);
    expect(await screen.findByText('Could not load approvals.')).toBeTruthy();
    expect(screen.getByRole('tab', { name: 'Pending' }).getAttribute('aria-selected')).toBe('true');
  });

  it('Approvals shows an empty inbox', async () => {
    fetchMocker.mockResponse(JSON.stringify([]));
    renderAt(<Approvals />);
    expect(await screen.findByText('No alerts are waiting for approval.')).toBeTruthy();
  });

  it('Approvals renders a pending card with SMS counts', async () => {
    fetchMocker.mockResponse(
      JSON.stringify([
        {
          id: 7,
          created_at: '2026-08-12T16:00:00Z',
          status: 'pending',
          action: 'send_sms',
          title: 'Koshi rise: Birpur in ~4.6 h',
          rationale: 'Fast rise upstream.',
          trace_id: 'tr_abc',
          payload: {
            messages: [{ lang: 'hi', text: 'क'.repeat(71) }],
            eta: { min: 3.1, typ: 4.6, max: 6.8 },
          },
          evidence: [{ label: 'Upstream stage', value: '4.21 m ± 0.03', source: 'tr_abc#2' }],
        },
      ]),
    );
    renderAt(<Approvals />);
    expect(await screen.findByText('Koshi rise: Birpur in ~4.6 h')).toBeTruthy();
    expect(screen.getByText(/71 characters · 2 SMS · UCS-2/)).toBeTruthy();
    expect(screen.getByRole('link', { name: 'tr_abc#2' }).getAttribute('href')).toBe('/traces/tr_abc#step-2');
    expect(screen.getByRole('button', { name: /approve/i })).toBeTruthy();
  });
});
