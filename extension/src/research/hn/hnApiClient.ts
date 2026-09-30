export interface HnItem {
  id: number;
  type?: 'job' | 'story' | 'comment' | 'poll' | 'pollopt';
  by?: string;
  time?: number;
  text?: string;
  kids?: number[];
  url?: string;
  score?: number;
  title?: string;
  descendants?: number;
}

const HN_BASE = 'https://hacker-news.firebaseio.com/v0';

export async function fetchHnItem(id: number): Promise<HnItem | null> {
  const response = await fetch(`${HN_BASE}/item/${id}.json`);
  if (!response.ok) return null;
  return response.json() as Promise<HnItem | null>;
}

export async function fetchHnUser(username: string): Promise<{ id: string; karma?: number; created?: number; submitted?: number[] } | null> {
  const response = await fetch(`${HN_BASE}/user/${encodeURIComponent(username)}.json`);
  if (!response.ok) return null;
  return response.json();
}

export async function fetchHnStoryIds(kind: 'top' | 'new' | 'best' | 'ask' | 'show' | 'job', limit = 30): Promise<number[]> {
  const path = kind === 'ask' ? 'askstories' : kind === 'show' ? 'showstories' : kind === 'job' ? 'jobstories' : `${kind}stories`;
  const response = await fetch(`${HN_BASE}/${path}.json`);
  if (!response.ok) return [];
  const ids = await response.json() as number[];
  return ids.slice(0, limit);
}

export async function fetchStoryWithComments(id: number, commentLimit = 20): Promise<{ story: HnItem | null; comments: HnItem[] }> {
  const story = await fetchHnItem(id);
  const comments = await Promise.all((story?.kids ?? []).slice(0, commentLimit).map(fetchHnItem));
  return { story, comments: comments.filter(Boolean) as HnItem[] };
}
