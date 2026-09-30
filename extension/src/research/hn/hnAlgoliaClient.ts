export interface HnAlgoliaHit {
  objectID: string;
  title?: string;
  story_title?: string;
  url?: string;
  author?: string;
  points?: number;
  num_comments?: number;
  created_at_i?: number;
  comment_text?: string;
  story_id?: number;
}

const MAX_QUERY_CHARS = 240;
const ONE_YEAR_SECONDS = 60 * 60 * 24 * 365;

interface CachedResponse {
  hits: HnAlgoliaHit[];
  etag?: string;
  fetchedAt: number;
}

/**
 * Lightweight session-scoped cache for Algolia GETs. Reuses
 * `chrome.storage.session` when available, falls back to an in-memory map
 * outside the extension context. ETag is sent on the next request when the
 * server returned one, so the cache stays warm across short-term reuse.
 */
const memoryCache = new Map<string, CachedResponse>();

async function readCache(key: string): Promise<CachedResponse | undefined> {
  const fromMemory = memoryCache.get(key);
  if (fromMemory) return fromMemory;
  if (typeof chrome === 'undefined' || !chrome.storage?.session) return undefined;
  try {
    const got = await chrome.storage.session.get(key);
    const entry = got[key] as CachedResponse | undefined;
    if (entry) memoryCache.set(key, entry);
    return entry;
  } catch {
    return undefined;
  }
}

async function writeCache(key: string, value: CachedResponse): Promise<void> {
  memoryCache.set(key, value);
  if (typeof chrome === 'undefined' || !chrome.storage?.session) return;
  try {
    await chrome.storage.session.set({ [key]: value });
  } catch {
    // session storage may be unavailable; in-memory wins.
  }
}

export async function searchHn(query: string, tags = 'story,comment', hitsPerPage = 12): Promise<HnAlgoliaHit[]> {
  const trimmed = query.slice(0, MAX_QUERY_CHARS);
  if (!trimmed.trim()) return [];
  const url = new URL('https://hn.algolia.com/api/v1/search');
  url.searchParams.set('query', trimmed);
  url.searchParams.set('tags', tags);
  url.searchParams.set('hitsPerPage', String(Math.min(50, hitsPerPage)));
  // Last-365d cap — older HN posts are noise for current signal mining.
  url.searchParams.set('numericFilters', `created_at_i>${Math.floor(Date.now() / 1000) - ONE_YEAR_SECONDS}`);

  const cacheKey = `hn:${url.toString()}`;
  const cached = await readCache(cacheKey);
  // 15-minute soft TTL — HN signal is real-time-ish; longer would miss bursts.
  if (cached && Date.now() - cached.fetchedAt < 15 * 60 * 1000) return cached.hits;

  const headers: Record<string, string> = { Accept: 'application/json' };
  if (cached?.etag) headers['If-None-Match'] = cached.etag;

  const response = await fetch(url.toString(), { headers });
  if (response.status === 304 && cached) {
    await writeCache(cacheKey, { ...cached, fetchedAt: Date.now() });
    return cached.hits;
  }
  if (!response.ok) return cached?.hits ?? [];
  const json = await response.json();
  const hits = Array.isArray(json?.hits) ? (json.hits as HnAlgoliaHit[]) : [];
  await writeCache(cacheKey, {
    hits,
    etag: response.headers.get('etag') ?? undefined,
    fetchedAt: Date.now(),
  });
  return hits;
}
