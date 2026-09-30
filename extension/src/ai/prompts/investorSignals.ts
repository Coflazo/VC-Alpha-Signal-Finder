import type { TreeoDeal, TreeoSettings } from '../../lib/types';
import type { ChatMessage } from '../providers/types';
import { InvestorSignalsSchema } from '../schemas';
import { buildJsonPrompt, dealDigest } from './base';

export function investorSignalsPrompt(deal: TreeoDeal, settings: TreeoSettings): ChatMessage[] {
  const userContent = [
    'Assess investor fit and possible investor attention. Do not label a possible signal as a confirmed investor approach unless direct evidence exists.',
    '',
    `Fund profile: ${JSON.stringify(settings.fundProfile, null, 2)}`,
    '',
    dealDigest(deal),
  ].join('\n');
  return buildJsonPrompt('investor_signals', InvestorSignalsSchema, userContent);
}
