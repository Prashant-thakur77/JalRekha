import { useEffect, useState } from 'react';

/**
 * Photo credits for the Indian flood photographs in public/images/india/.
 * The list is read at runtime from credits.json so the app still builds and
 * runs before (or without) the photos; pages fall back to a plain backdrop.
 */

export const PHOTO_DIR = '/images/india/';
export const CREDITS_URL = `${PHOTO_DIR}credits.json`;

export interface PhotoCredit {
  id: string;
  title: string;
  place?: string;
  kind?: string;
  alt_en: string;
  alt_hi?: string;
  author: string;
  license: string;
  license_url?: string;
  source_url?: string;
  web: { large: string; small?: string };
}

function str(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

/** Resolve a path from credits.json: absolute URLs and root paths pass through, bare names live in PHOTO_DIR. */
export function photoSrc(path?: string | null): string | null {
  const p = str(path);
  if (!p) return null;
  if (/^(https?:)?\/\//i.test(p) || p.startsWith('/') || p.startsWith('data:')) return p;
  return `${PHOTO_DIR}${p.replace(/^\.?\//, '')}`;
}

/** Accept the documented shape, tolerating `web` given as flat "web.large" keys. Drops unusable rows. */
export function normalizePhotos(data: unknown): PhotoCredit[] {
  const rows = Array.isArray(data)
    ? data
    : data && typeof data === 'object' && Array.isArray((data as { photos?: unknown }).photos)
      ? (data as { photos: unknown[] }).photos
      : [];
  const out: PhotoCredit[] = [];
  for (const row of rows) {
    if (!row || typeof row !== 'object') continue;
    const r = row as Record<string, unknown>;
    const web = (r.web && typeof r.web === 'object' ? r.web : {}) as Record<string, unknown>;
    const large = photoSrc(str(web.large) || str(r['web.large']));
    if (!large) continue;
    const small = photoSrc(str(web.small) || str(r['web.small'])) ?? undefined;
    out.push({
      id: str(r.id) || large,
      title: str(r.title),
      place: str(r.place) || undefined,
      kind: str(r.kind) || undefined,
      alt_en: str(r.alt_en) || str(r.title),
      alt_hi: str(r.alt_hi) || undefined,
      author: str(r.author) || 'Unknown',
      license: str(r.license),
      license_url: str(r.license_url) || undefined,
      source_url: str(r.source_url) || undefined,
      web: { large, small },
    });
  }
  return out;
}

let cache: PhotoCredit[] | null = null;
let inflight: Promise<PhotoCredit[]> | null = null;

export function loadPhotos(): Promise<PhotoCredit[]> {
  if (cache) return Promise.resolve(cache);
  if (!inflight) {
    inflight = fetch(CREDITS_URL, { headers: { Accept: 'application/json' } })
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json() as Promise<unknown>;
      })
      .then((data) => {
        const list = normalizePhotos(data);
        cache = list;
        return list;
      })
      .finally(() => {
        inflight = null;
      });
  }
  return inflight;
}

/** For tests. */
export function resetPhotoCache() {
  cache = null;
  inflight = null;
}

/** null while loading, [] when there are none or the list could not be read. */
export function usePhotos(): { photos: PhotoCredit[] | null; error: boolean } {
  const [state, setState] = useState<{ photos: PhotoCredit[] | null; error: boolean }>(() => ({
    photos: cache,
    error: false,
  }));
  useEffect(() => {
    if (cache) return;
    let alive = true;
    loadPhotos().then(
      (photos) => alive && setState({ photos, error: false }),
      () => alive && setState({ photos: [], error: true }),
    );
    return () => {
      alive = false;
    };
  }, []);
  return state;
}

const HERO_HINT = /hero|flood|river|embankment|boat/i;

/** Order photos for use on a page: a likely hero first, then the rest, without repeats. */
export function orderPhotos(list: PhotoCredit[]): PhotoCredit[] {
  const heroIdx = list.findIndex((p) => /hero/i.test(p.kind ?? ''));
  const idx = heroIdx >= 0 ? heroIdx : list.findIndex((p) => HERO_HINT.test(`${p.kind ?? ''} ${p.title}`));
  if (idx <= 0) return list;
  return [list[idx], ...list.slice(0, idx), ...list.slice(idx + 1)];
}

/** Pick photos by id in the given order, skipping ids that are not in the list. */
export function pickPhotos(list: PhotoCredit[] | null, ids: string[]): PhotoCredit[] {
  if (!list) return [];
  return ids.map((id) => list.find((p) => p.id === id)).filter((p): p is PhotoCredit => Boolean(p));
}
