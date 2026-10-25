/** Formatting helpers shared by the new pages. All tolerate missing values. */

export function fmtNum(value: number | null | undefined, digits = 2): string {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(digits) : '–';
}

export function fmtSigned(value: number | null | undefined, digits = 2): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '–';
  return `${value > 0 ? '+' : value < 0 ? '−' : ''}${Math.abs(value).toFixed(digits)}`;
}

export function fmtTime(iso?: string | null): string {
  if (!iso) return '–';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

export function fmtDateTime(iso?: string | null): string {
  if (!iso) return '–';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' });
}

export function fmtHours(value: number | null | undefined): string {
  return typeof value === 'number' && Number.isFinite(value) ? (Math.round(value * 10) / 10).toString() : '–';
}

export function fmtUsd(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '–';
  if (value === 0) return '$0';
  return value < 0.01 ? `$${value.toFixed(4)}` : `$${value.toFixed(2)}`;
}

/** Compact, readable rendering of an arbitrary JSON-ish value. */
export function fmtValue(value: unknown, max = 80): string {
  if (value === null || value === undefined) return '–';
  if (typeof value === 'number') return Number.isInteger(value) ? String(value) : value.toFixed(3).replace(/0+$/, '').replace(/\.$/, '');
  if (typeof value === 'string') return value.length > max ? `${value.slice(0, max - 1)}…` : value;
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  let text: string;
  try {
    text = JSON.stringify(value);
  } catch {
    text = String(value);
  }
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}
