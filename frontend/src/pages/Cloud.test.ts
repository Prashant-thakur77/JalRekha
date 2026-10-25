import { describe, expect, it, vi } from 'vitest';
import { serviceFacts, stageAverages } from '../lib/cloud';

// store.ts (source of API_BASE) opens IndexedDB on import; jsdom has none.
vi.mock('../lib/idb', () => ({
  attachmentToFile: vi.fn(),
  getPendingReports: vi.fn(async () => []),
  deleteReportOffline: vi.fn(),
  saveReportOffline: vi.fn(),
  toPendingAttachment: vi.fn(),
}));

describe('Cloud page helpers', () => {
  it('summarises each service from the live response', () => {
    expect(serviceFacts('ec2', { ok: true, instance_type: 'c8g.xlarge', architecture: 'arm64', ami: 'ami-1', zone: 'us-east-1a' })[0]).toBe(
      'c8g.xlarge · arm64',
    );
    expect(serviceFacts('s3', { ok: true, objects: { cycles: 86, cap: 1 }, lifecycle: 'cycle evidence kept 90 days' })[0]).toBe(
      '86 cycle files · 1 CAP',
    );
    expect(serviceFacts('budget', { ok: true, actual_usd: 3.5, limit_usd: 60 })[0]).toBe('$3.50 of $60 this month');
  });

  it('averages stage timings in pipeline order and drops empty stages', () => {
    const rows = stageAverages({
      hours: 3,
      period_s: 300,
      console_url: '',
      series: { 'stage:redact': [{ t: 'a', v: 30 }, { t: 'b', v: 40 }], 'stage:register': [{ t: 'a', v: 20 }], 'stage:fuse': [] },
    });
    expect(rows.map((r) => r.stage)).toEqual(['register', 'redact']);
    expect(rows[1].ms).toBe(35);
  });
});
