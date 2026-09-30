import type { HnCommentRecord, HnStoryRecord, TreeoDeal } from '../../lib/types';
import type { ChatMessage } from '../providers/types';
import { HnSignalSchema } from '../schemas';
import { buildJsonPrompt, dealDigest } from './base';

export function hnSignalAnalysisPrompt(deal: TreeoDeal, stories: HnStoryRecord[], comments: HnCommentRecord[]): ChatMessage[] {
  const userContent = [
    'Analyze Hacker News as YC community/news signal: Show HN launches, Ask HN pain, technical credibility, developer resonance, objections, customer language, competitor mentions.',
    '',
    dealDigest(deal),
    '',
    JSON.stringify({ stories: stories.slice(0, 20), comments: comments.slice(0, 35) }, null, 2).slice(0, 14_000),
  ].join('\n');
  return buildJsonPrompt('hn_signal_analysis', HnSignalSchema, userContent);
}
