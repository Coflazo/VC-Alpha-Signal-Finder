import type { GithubRepoRecord, TreeoDeal } from '../../lib/types';
import type { ChatMessage } from '../providers/types';
import { TechnicalCredibilitySchema } from '../schemas';
import { buildJsonPrompt, dealDigest } from './base';

export function technicalCredibilityPrompt(deal: TreeoDeal, repos: GithubRepoRecord[]): ChatMessage[] {
  const userContent = [
    'Assess whether the founder/team can actually build the product.',
    'Never infer technical quality from school or employer alone.',
    '',
    dealDigest(deal),
    '',
    `GitHub repos: ${JSON.stringify(repos, null, 2).slice(0, 8000)}`,
  ].join('\n');
  return buildJsonPrompt('technical_credibility', TechnicalCredibilitySchema, userContent);
}
