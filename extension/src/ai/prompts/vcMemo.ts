import type { TreeoDeal } from '../../lib/types';
import type { ChatMessage } from '../providers/types';
import { VcMemoSchema } from '../schemas';
import { buildJsonPrompt, dealDigest } from './base';

export function vcMemoPrompt(deal: TreeoDeal): ChatMessage[] {
  const userContent = [
    'Write a VC diligence memo for an early-stage analyst. The memo must be evidence-first and must not overstate weak signals.',
    'Recommendation must be one of: immediate_outreach, take_meeting, partner_review, monitor, pass, unknown.',
    '',
    dealDigest(deal),
  ].join('\n');
  return buildJsonPrompt('vc_memo', VcMemoSchema, userContent);
}
