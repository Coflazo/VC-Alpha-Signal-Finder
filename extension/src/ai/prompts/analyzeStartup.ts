import type { TreeoDeal } from '../../lib/types';
import type { ChatMessage } from '../providers/types';
import { StartupAnalysisSchema } from '../schemas';
import { buildJsonPrompt, dealDigest } from './base';

export function analyzeStartupPrompt(deal: TreeoDeal): ChatMessage[] {
  const userContent = [
    'Analyze the startup behind this founder profile.',
    'stageEstimate.stage must be one of: idea_stealth, pre_product, mvp_beta, pre_seed, seed, series_a_plus, unknown.',
    '',
    dealDigest(deal),
  ].join('\n');
  return buildJsonPrompt('startup_analysis', StartupAnalysisSchema, userContent);
}
