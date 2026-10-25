import type { CloudMetrics, CloudService } from '../api';

export const SERVICE_ORDER = ['ec2', 'cloudformation', 's3', 'cloudwatch_logs', 'cloudwatch_alarms', 'step_functions', 'sns', 'polly', 'api_gateway', 'claude', 'budget'];
const STAGE_ORDER = ['register', 'warp', 'quality', 'median', 'E1_edge', 'E2_temporal', 'E3_colour', 'fuse', 'redact', 'overlay'];

export function bytes(n?: number | null): string {
  if (!n) return '0 B';
  const units = ['B', 'kB', 'MB', 'GB'];
  let i = 0;
  let v = n;
  while (v >= 1000 && i < units.length - 1) {
    v /= 1000;
    i += 1;
  }
  return `${v.toFixed(v < 10 && i ? 1 : 0)} ${units[i]}`;
}

/** The facts worth one line for each service, all taken from the live response. */
export function serviceFacts(id: string, s: CloudService): string[] {
  const v = (k: string) => s[k] as never;
  switch (id) {
    case 'ec2':
      return [`${v('instance_type')} · ${v('architecture')}`, `${v('ami')}`, `${v('zone')}`];
    case 'cloudformation':
      return [`${v('status')}`, `${v('resources')} resources`];
    case 's3': {
      const o = (s.objects ?? {}) as Record<string, number>;
      return [`${o.cycles ?? 0} cycle files · ${o.cap ?? 0} CAP`, `${s.lifecycle ?? ''}`];
    }
    case 'cloudwatch_logs':
      return [`${v('group')}`, `${v('retention_days')} days · ${bytes(s.stored_bytes as number)}`];
    case 'cloudwatch_alarms': {
      const a = (s.alarms ?? []) as Array<{ name: string; state: string }>;
      return [`${a.length} alarms · ${s.in_alarm ?? 0} firing`, a.map((x) => x.name).slice(0, 3).join(', ')];
    }
    case 'step_functions': {
      const r = (s.recent ?? []) as Array<{ status: string }>;
      return [`${r.length} recent escalation runs`, r[0] ? `latest: ${r[0].status.toLowerCase()}` : 'none yet'];
    }
    case 'sns':
      return [`${v('subscriptions_confirmed')} confirmed subscribers`];
    case 'polly':
      return ((s.voices ?? []) as string[]).slice(0, 1);
    case 'api_gateway':
      return [`${v('kind')}`];
    case 'claude':
      return [`${v('model')}`];
    case 'budget':
      return [`$${Number(s.actual_usd ?? 0).toFixed(2)} of $${Number(s.limit_usd ?? 0).toFixed(0)} this month`];
    default:
      return [];
  }
}

/** Latest value of each per-stage series, in pipeline order. */
export function stageAverages(metrics: CloudMetrics | null): Array<{ stage: string; ms: number }> {
  if (!metrics) return [];
  return STAGE_ORDER.map((stage) => {
    const pts = metrics.series[`stage:${stage}`] ?? [];
    return { stage, ms: pts.length ? pts.reduce((a, p) => a + p.v, 0) / pts.length : 0 };
  }).filter((x) => x.ms > 0);
}

