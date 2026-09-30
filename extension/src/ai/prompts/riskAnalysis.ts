import type { TreeoDeal } from '../../lib/types';
import type { ChatMessage } from '../providers/types';
import { RiskAnalysisSchema } from '../schemas';
import { buildJsonPrompt, dealDigest } from './base';

export function riskAnalysisPrompt(deal: TreeoDeal): ChatMessage[] {
  const userContent = [
    'Identify contradictions, red flags, overclaiming risk, data-quality warnings, and privacy warnings.',
    '',
    dealDigest(deal),
  ].join('\n');
  return buildJsonPrompt('risk_analysis', RiskAnalysisSchema, userContent);
}
