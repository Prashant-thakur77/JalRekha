import { describe, it, expect, vi, beforeEach } from 'vitest';
import { useAppStore } from './store';
import * as idb from './lib/idb';
import type { PendingReport } from './lib/idb';

vi.mock('./lib/idb', async () => {
  return {
    attachmentToFile: vi.fn((attachment: { blob: Blob; name: string; type: string }, fallbackName: string) => (
      new File([attachment.blob], attachment.name || fallbackName, { type: attachment.type })
    )),
    getPendingReports: vi.fn(),
    deleteReportOffline: vi.fn(),
  };
});

describe('AppStore', () => {
  const fetchMock = vi.fn<typeof fetch>();
  const alertMock = vi.fn<typeof alert>();

  beforeEach(() => {
    vi.clearAllMocks();
    useAppStore.setState({ isOnline: true, queueCount: 0 });
    Object.defineProperty(globalThis, 'fetch', {
      configurable: true,
      writable: true,
      value: fetchMock,
    });
    Object.defineProperty(globalThis, 'alert', {
      configurable: true,
      writable: true,
      value: alertMock,
    });
  });

  it('flushQueue sends queued reports and deletes them', async () => {
    const mockReports: PendingReport[] = [
      {
        id: 1,
        site_id: 'test-site',
        reporter_name: 'Test',
        reporter_role: 'Role',
        transcript_text: 'Text',
        photo_attachment: {
          blob: new Blob(['photo-bytes'], { type: 'image/jpeg' }),
          name: 'flood.jpg',
          type: 'image/jpeg',
        },
        audio_attachment: {
          blob: new Blob(['audio-bytes'], { type: 'audio/mpeg' }),
          name: 'note.mp3',
          type: 'audio/mpeg',
        },
        offline_created: true,
        createdAt: 123,
      },
    ];

    vi.mocked(idb.getPendingReports).mockResolvedValue(mockReports);
    
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => ({ id: 1 }),
    } as Response);

    await useAppStore.getState().flushQueue();

    expect(fetchMock).toHaveBeenCalledTimes(2);
    const reportCall = fetchMock.mock.calls[0];
    expect(reportCall[0]).toContain('/api/reports');

    const formData = reportCall[1]?.body as FormData;
    expect(formData.get('site_id')).toBe('test-site');
    expect(formData.get('transcript_text')).toBe('Text');
    expect(formData.get('offline_created')).toBe('true');
    expect(formData.get('photo')).toBeInstanceOf(File);
    expect((formData.get('photo') as File).name).toBe('flood.jpg');
    expect(formData.get('audio')).toBeInstanceOf(File);
    expect((formData.get('audio') as File).name).toBe('note.mp3');
    expect(fetchMock.mock.calls[1][0]).toContain('/api/sync/flush');
    expect(idb.deleteReportOffline).toHaveBeenCalledWith(1);
  });

  it('flushQueue does nothing if offline', async () => {
    useAppStore.setState({ isOnline: false });
    await useAppStore.getState().flushQueue();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(alertMock).toHaveBeenCalledWith('Cannot flush queue while offline');
  });

  it('flushQueue forwards webm audio blob with correct filename and type', async () => {
    const webmBlob = new Blob([new Uint8Array([1, 2, 3, 4])], { type: 'audio/webm' });
    const mockReports: PendingReport[] = [
      {
        id: 7,
        site_id: 'site-mic',
        reporter_name: 'Voz',
        reporter_role: 'Community Member',
        transcript_text: 'Nota grabada',
        audio_attachment: {
          blob: webmBlob,
          name: 'note.webm',
          type: 'audio/webm',
        },
        offline_created: false,
        createdAt: 456,
      },
    ];

    vi.mocked(idb.getPendingReports).mockResolvedValue(mockReports);

    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => ({ id: 7 }),
    } as Response);

    await useAppStore.getState().flushQueue();

    const reportCall = fetchMock.mock.calls[0];
    const formData = reportCall[1]?.body as FormData;
    const audioEntry = formData.get('audio');
    expect(audioEntry).toBeInstanceOf(File);
    expect((audioEntry as File).name).toBe('note.webm');
    expect((audioEntry as File).type).toBe('audio/webm');
    expect(idb.deleteReportOffline).toHaveBeenCalledWith(7);
  });

  it('fetches and updates per-site experimental settings', async () => {
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          site_id: 'test-site',
          historical_context_enabled: false,
          forecast_enabled: true,
          forecast_horizon_minutes: 60,
          forecast_critical_threshold: 0.8,
          updated_at: '2026-05-18T10:00:00',
        }),
      } as Response)
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          site_id: 'test-site',
          historical_context_enabled: true,
          forecast_enabled: true,
          forecast_horizon_minutes: 60,
          forecast_critical_threshold: 0.8,
          updated_at: '2026-05-18T10:01:00',
        }),
      } as Response);

    await useAppStore.getState().fetchSiteExperimentalSettings('test-site');
    expect(fetchMock.mock.calls[0][0]).toContain('/api/sites/test-site/experimental-settings');
    expect(useAppStore.getState().siteSettings['test-site'].historical_context_enabled).toBe(false);

    await useAppStore.getState().updateSiteExperimentalSettings('test-site', {
      historical_context_enabled: true,
    });
    expect(fetchMock.mock.calls[1][1]?.method).toBe('PUT');
    expect(useAppStore.getState().siteSettings['test-site'].historical_context_enabled).toBe(true);
  });

  it('fetches historical context and forecast for a site', async () => {
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          hits: [
            {
              id: 3,
              source: 'manual',
              title: 'Bridge threshold',
              summary: 'Close access road at 0.7.',
              threshold_level: 0.7,
              jurisdiction: 'municipal',
              rank: 0.91,
            },
          ],
        }),
      } as Response)
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          forecast: {
            horizon_minutes: 60,
            expected_level: 0.82,
            trend_per_hour: 0.2,
            acceleration_per_hour2: 0.01,
            risk: 'high',
            status: 'ok',
            confidence: 0.7,
            critical_threshold: 0.8,
            minutes_to_threshold: 48,
            projected_points: [{ minute: 0, level: 0.6 }, { minute: 60, level: 0.82 }],
            uncertainty_band: [{ minute: 0, low: 0.6, high: 0.6 }, { minute: 60, low: 0.76, high: 0.88 }],
          },
        }),
      } as Response);

    const hits = await useAppStore.getState().fetchSiteHistoricalContext('test-site', {
      waterLevel: 0.68,
      query: 'bridge',
    });
    expect(hits[0].id).toBe(3);
    expect(String(fetchMock.mock.calls[0][0])).toContain('water_level=0.68');
    expect(useAppStore.getState().siteHistoricalContext['test-site'][0].rank).toBe(0.91);

    const forecast = await useAppStore.getState().fetchSiteForecast('test-site');
    expect(forecast?.expected_level).toBe(0.82);
    expect(useAppStore.getState().siteForecasts['test-site'].minutes_to_threshold).toBe(48);
  });
});
