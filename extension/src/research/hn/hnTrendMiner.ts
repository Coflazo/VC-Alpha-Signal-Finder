import type { HnCommentRecord, HnStoryRecord } from '../../lib/types';
import { hashString, makeId, nowIso } from '../../lib/utils';
import { searchHn } from './hnAlgoliaClient';
import { matchLexicon, PAIN_LEXICON, PRODUCT_LEXICON, recencyDecay } from './lexicons';
import { isShowHnTitle } from './showHnDetector';

function htmlToText(value = ''): string {
  return value.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim();
}

const dedupCache = new Map<string, { stories: HnStoryRecord[]; comments: HnCommentRecord[]; ts: number }>();
const DEDUP_TTL_MS = 10 * 60 * 1000;

export async function mineHnSignals(query: string): Promise<{ stories: HnStoryRecord[]; comments: HnCommentRecord[] }> {
  if (!query.trim()) return { stories: [], comments: [] };
  const key = hashString(query.toLowerCase().trim());
  const cached = dedupCache.get(key);
  if (cached && Date.now() - cached.ts < DEDUP_TTL_MS) {
    return { stories: cached.stories, comments: cached.comments };
  }

  const [storyHits, commentHits] = await Promise.all([
    searchHn(query, 'story', 15),
    searchHn(query, 'comment', 25),
  ]);
  const retrievedAt = nowIso();
  const stories: HnStoryRecord[] = storyHits.map((hit) => {
    const createdAt = hit.created_at_i ? new Date(hit.created_at_i * 1000).toISOString() : '';
    const isShow = isShowHnTitle(hit.title ?? '');
    return {
      id: makeId('hn_story'),
      hnId: Number(hit.objectID),
      type: isShow ? 'show_hn' : 'story',
      title: hit.title ?? hit.story_title ?? 'Untitled HN story',
      url: hit.url || `https://news.ycombinator.com/item?id=${hit.objectID}`,
      author: hit.author ?? 'unknown',
      score: Math.round((hit.points ?? 0) * recencyDecay(createdAt)),
      commentCount: hit.num_comments ?? 0,
      createdAt,
      retrievedAt,
      tags: [isShow ? 'show_hn' : '', query].filter(Boolean),
      relatedCompanyIds: [],
      relatedPersonIds: [],
    };
  });
  const comments: HnCommentRecord[] = commentHits.map((hit) => {
    const text = htmlToText(hit.comment_text);
    const createdAt = hit.created_at_i ? new Date(hit.created_at_i * 1000).toISOString() : '';
    return {
      id: makeId('hn_comment'),
      hnId: Number(hit.objectID),
      storyId: hit.story_id ?? 0,
      author: hit.author ?? 'unknown',
      text,
      createdAt,
      sentiment: 'neutral',
      painSignals: matchLexicon(text, PAIN_LEXICON).map((entry) => entry.label),
      productSignals: matchLexicon(text, PRODUCT_LEXICON).map((entry) => entry.label),
      evidenceIds: [],
    };
  });

  dedupCache.set(key, { stories, comments, ts: Date.now() });
  return { stories, comments };
}

// Legacy named exports kept for any external callers / tests.
export function detectPainSignals(text: string): string[] {
  return matchLexicon(text, PAIN_LEXICON).map((entry) => entry.label);
}

export function detectProductSignals(text: string): string[] {
  return matchLexicon(text, PRODUCT_LEXICON).map((entry) => entry.label);
}
