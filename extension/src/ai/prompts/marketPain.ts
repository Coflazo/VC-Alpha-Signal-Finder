import type { HnCommentRecord, HnStoryRecord, TreeoDeal } from '../../lib/types';
import type { ChatMessage } from '../providers/types';
import { MarketPainSchema } from '../schemas';
import { buildJsonPrompt, dealDigest } from './base';

export function marketPainPrompt(deal: TreeoDeal, hnStories: HnStoryRecord[], hnComments: HnCommentRecord[]): ChatMessage[] {
  const userContent = [
    'Assess market pain from captured profile evidence and Hacker News public signal.',
    '',
    dealDigest(deal),
    '',
    `HN stories: ${JSON.stringify(hnStories.slice(0, 12), null, 2)}`,
    `HN comments: ${JSON.stringify(hnComments.slice(0, 20), null, 2)}`,
  ].join('\n');
  return buildJsonPrompt('market_pain', MarketPainSchema, userContent);
}
