/**
 * SMS length and segment counting (3GPP TS 23.038).
 *
 * GSM-7: 160 septets in a single SMS, 153 per part when concatenated.
 *        Characters from the extension table (e.g. € [ ] { } ~ ^ \ |) take
 *        two septets (escape + char).
 * UCS-2: used as soon as any character is outside GSM-7 (all Devanagari).
 *        70 UTF-16 code units in a single SMS, 67 per part when concatenated.
 */

const GSM7_BASIC =
  '@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !"#¤%&\'()*+,-./0123456789:;<=>?' +
  '¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà';
const GSM7_EXTENDED = '\f^{}\\[~]|€';

const BASIC = new Set(Array.from(GSM7_BASIC));
const EXTENDED = new Set(Array.from(GSM7_EXTENDED));

export type SmsEncoding = 'GSM-7' | 'UCS-2';

export interface SmsInfo {
  encoding: SmsEncoding;
  /** Length in encoding units: septets for GSM-7, UTF-16 code units for UCS-2. */
  units: number;
  /** Characters as a person counts them (Unicode code points). */
  chars: number;
  segments: number;
  /** Units allowed per segment at the current segment count. */
  perSegment: number;
  /** Units left before another segment is needed. */
  remaining: number;
}

export function isGsm7(text: string): boolean {
  for (const ch of text) {
    if (!BASIC.has(ch) && !EXTENDED.has(ch)) return false;
  }
  return true;
}

export function smsInfo(text: string): SmsInfo {
  const chars = Array.from(text).length;
  if (isGsm7(text)) {
    let units = 0;
    for (const ch of text) units += EXTENDED.has(ch) ? 2 : 1;
    return finish('GSM-7', units, chars, 160, 153);
  }
  // UCS-2 counts UTF-16 code units; characters outside the BMP take two.
  return finish('UCS-2', text.length, chars, 70, 67);
}

function finish(
  encoding: SmsEncoding,
  units: number,
  chars: number,
  single: number,
  multi: number,
): SmsInfo {
  if (units === 0) {
    return { encoding, units, chars, segments: 0, perSegment: single, remaining: single };
  }
  if (units <= single) {
    return { encoding, units, chars, segments: 1, perSegment: single, remaining: single - units };
  }
  const segments = Math.ceil(units / multi);
  return { encoding, units, chars, segments, perSegment: multi, remaining: segments * multi - units };
}

export function smsSegments(text: string): number {
  return smsInfo(text).segments;
}
