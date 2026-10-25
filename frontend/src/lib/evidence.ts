import type { EvidenceItem } from '../api';

export interface ShownValue {
  value: string;
  unit: string;
}

function trim(n: number, digits: number): string {
  return n.toFixed(digits).replace(/\.0+$/, '').replace(/(\.\d*?)0+$/, '$1');
}

/** Present an evidence number in the unit a reader expects (fractions as %, minutes as hours, USD as $). */
export function showValue(value: number | null | undefined, unit?: string): ShownValue {
  if (typeof value !== 'number' || !Number.isFinite(value)) return { value: '–', unit: unit ?? '' };
  switch ((unit ?? '').toLowerCase()) {
    case 'fraction':
      return { value: trim(value * 100, 1), unit: '%' };
    case 'min':
      return { value: trim(value / 60, 1), unit: 'h' };
    case 'usd':
      return { value: `$${value.toFixed(2)}`, unit: '' };
    case 'cm':
      return { value: value.toFixed(1), unit: 'cm' };
    case 'runs':
      return { value: String(Math.round(value)), unit: unit ?? '' };
    default:
      return { value: trim(value, 2), unit: unit ?? '' };
  }
}

/** Bar widths for "this result" against its baseline, on a shared scale. */
export function barWidths(item: EvidenceItem): { self: number; base: number } | null {
  if (!item.baseline || typeof item.baseline.value !== 'number') return null;
  const max = Math.max(Math.abs(item.value), Math.abs(item.baseline.value));
  if (!Number.isFinite(max) || max <= 0) return { self: 0, base: 0 };
  return { self: (Math.abs(item.value) / max) * 100, base: (Math.abs(item.baseline.value) / max) * 100 };
}

export function datasetKind(dataset?: string): 'real' | 'synthetic' | null {
  if (!dataset) return null;
  if (/^\s*real/i.test(dataset)) return 'real';
  if (/^\s*synthetic/i.test(dataset)) return 'synthetic';
  return null;
}
