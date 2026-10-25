export type Level = 'unknown' | 'ok' | 'watch' | 'warn' | 'danger';

/** Danger and warning come from the measured stage; "watch" is the agent's own fast-rise mode. */
export function levelFor(
  stage: number | null | undefined,
  warn: number | null | undefined,
  danger: number | null | undefined,
  mode?: string | null,
): Level {
  if (typeof stage !== 'number' || !Number.isFinite(stage)) return 'unknown';
  if (typeof danger === 'number' && stage >= danger) return 'danger';
  if (typeof warn === 'number' && stage >= warn) return 'warn';
  if (mode === 'watch' || mode === 'alert') return 'watch';
  return 'ok';
}
