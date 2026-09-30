import type { Evidence, ExtractedProfile } from '../../lib/types';
import type { ChatMessage } from '../providers/types';
import { FounderClassificationSchema } from '../schemas';
import { buildJsonPrompt, evidenceDigest } from './base';

const FEW_SHOTS = [
  {
    user: 'Person: Eda Yilmaz, "Co-founder and CTO at LedgerFlow AI" with a public website, GitHub examples, and a Show HN launch.\nEvidence:\n[ev_a] profile.headline: "Co-founder and CTO at LedgerFlow AI" (medium_high)\n[ev_b] profile.links: "github.com/ledgerflow" (medium_high)',
    assistant: JSON.stringify({
      founderLikelihoodScore: 84,
      label: 'very_likely_founder',
      evidence: ['headline explicitly states co-founder and CTO', 'public GitHub link'],
      evidence_ids: ['ev_a', 'ev_b'],
      missingEvidence: ['fundraising stage confirmation'],
      confidence: 0.78,
    }),
  },
  {
    user: 'Person: Anon Reader, "AI enthusiast and follower of founders" with no company, no GitHub, no posts.\nEvidence:\n[ev_x] profile.headline: "AI enthusiast and follower of founders" (medium_low)',
    assistant: JSON.stringify({
      founderLikelihoodScore: 18,
      label: 'not_enough_evidence',
      evidence: [],
      evidence_ids: [],
      missingEvidence: ['company name', 'product proof', 'public site'],
      confidence: 0.25,
    }),
  },
];

export function classifyFounderPrompt(profile: ExtractedProfile, evidence: Evidence[]): ChatMessage[] {
  const userContent = [
    'Classify whether this person is likely a startup founder.',
    'Valid label values: confirmed_founder, very_likely_founder, possible_founder, weak_signal, not_enough_evidence.',
    '',
    `Profile: ${JSON.stringify(profile, null, 2).slice(0, 9000)}`,
    '',
    `Evidence:\n${evidenceDigest(evidence)}`,
  ].join('\n');
  return buildJsonPrompt('founder_classification', FounderClassificationSchema, userContent, FEW_SHOTS);
}
