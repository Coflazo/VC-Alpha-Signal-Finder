import { z } from 'zod';

export const EvidenceRefSchema = z.object({
  evidence_ids: z.array(z.string()).default([]),
  confidence: z.number().min(0).max(1).default(0.4),
});

export const ExtractedProfileSchema = z.object({
  person: z.object({
    name: z.string().default('unknown'),
    headline: z.string().default('unknown'),
    location: z.string().default('unknown'),
    bio: z.string().default('unknown'),
  }),
  companies: z.array(z.object({
    name: z.string(),
    website: z.string().default('unknown'),
    description: z.string().default('unknown'),
    evidence_ids: z.array(z.string()).default([]),
  })).default([]),
  roles: z.array(z.object({
    title: z.string(),
    company: z.string().default('unknown'),
    evidence_ids: z.array(z.string()).default([]),
  })).default([]),
  skills: z.array(z.string()).default([]),
  posts: z.array(z.string()).default([]),
  warnings: z.array(z.string()).default([]),
});

export const FounderClassificationSchema = z.object({
  founderLikelihoodScore: z.number().min(0).max(100),
  label: z.enum(['confirmed_founder', 'very_likely_founder', 'possible_founder', 'weak_signal', 'not_enough_evidence']),
  evidence: z.array(z.string()).default([]),
  evidence_ids: z.array(z.string()).default([]),
  missingEvidence: z.array(z.string()).default([]),
  confidence: z.number().min(0).max(1),
});

export const StartupAnalysisSchema = z.object({
  companySummary: z.string().default('unknown'),
  productHypothesis: z.string().default('unknown'),
  stageEstimate: z.object({
    stage: z.enum(['idea_stealth', 'pre_product', 'mvp_beta', 'pre_seed', 'seed', 'series_a_plus', 'unknown']),
    confidence: z.number().min(0).max(1),
    evidence_ids: z.array(z.string()).default([]),
    missingEvidence: z.array(z.string()).default([]),
  }),
  tractionSignals: z.array(z.string()).default([]),
  businessModel: z.string().default('unknown'),
  credibilitySignals: z.array(z.string()).default([]),
  technicalCredibility: z.string().default('unknown'),
  missingInfo: z.array(z.string()).default([]),
});

export const TechnicalCredibilitySchema = z.object({
  repoQuality: z.string().default('unknown'),
  technicalDepth: z.string().default('unknown'),
  builderProof: z.array(z.string()).default([]),
  dependencyRisk: z.string().default('unknown'),
  moat: z.string().default('unknown'),
  score: z.number().min(0).max(100),
  evidence_ids: z.array(z.string()).default([]),
});

export const MarketPainSchema = z.object({
  marketCategory: z.string().default('unknown'),
  customerSegment: z.string().default('unknown'),
  painFrequency: z.number().min(0).max(100),
  painIntensity: z.number().min(0).max(100),
  buyerClarity: z.string().default('unknown'),
  willingnessToPay: z.string().default('unknown'),
  existingWorkarounds: z.array(z.string()).default([]),
  competitors: z.array(z.string()).default([]),
  confidence: z.number().min(0).max(1),
  evidence_ids: z.array(z.string()).default([]),
});

export const HnSignalSchema = z.object({
  showHnLaunches: z.array(z.string()).default([]),
  askHnPainClusters: z.array(z.string()).default([]),
  founderHnCredibility: z.string().default('unknown'),
  categoryHeat: z.number().min(0).max(100),
  developerResonance: z.number().min(0).max(100),
  objections: z.array(z.string()).default([]),
  customerLanguage: z.array(z.string()).default([]),
  competitorMentions: z.array(z.string()).default([]),
  evidence_ids: z.array(z.string()).default([]),
});

export const InvestorSignalsSchema = z.object({
  confirmedInvestors: z.array(z.string()).default([]),
  possibleInvestorInterest: z.array(z.string()).default([]),
  weakSignals: z.array(z.string()).default([]),
  warmIntroPaths: z.array(z.string()).default([]),
  fundThesisFit: z.string().default('unknown'),
  portfolioConflicts: z.array(z.string()).default([]),
  confidence: z.number().min(0).max(1),
  evidence_ids: z.array(z.string()).default([]),
});

export const RiskAnalysisSchema = z.object({
  redFlags: z.array(z.string()).default([]),
  inconsistencies: z.array(z.string()).default([]),
  overclaimingRisk: z.string().default('unknown'),
  dataQualityWarnings: z.array(z.string()).default([]),
  privacyWarnings: z.array(z.string()).default([]),
});

export const VcMemoSchema = z.object({
  thirtySecondSummary: z.string(),
  onePageMemo: z.string(),
  recommendation: z.enum(['immediate_outreach', 'take_meeting', 'partner_review', 'monitor', 'pass', 'unknown']),
  outreachUrgency: z.string(),
  firstCallQuestions: z.array(z.string()).default([]),
  scorecard: z.object({
    founderQuality: z.number().min(0).max(10),
    founderMarketFit: z.number().min(0).max(10),
    technicalCredibility: z.number().min(0).max(10),
    commercialCredibility: z.number().min(0).max(10),
    marketSize: z.number().min(0).max(10),
    timing: z.number().min(0).max(10),
    traction: z.number().min(0).max(10),
    fundability: z.number().min(0).max(10),
    networkQuality: z.number().min(0).max(10),
    redFlagRisk: z.number().min(0).max(10),
    dataQuality: z.number().min(0).max(10),
  }),
});

/**
 * Provider returned text that did not parse to a JSON object.
 * Carries the raw response so the audit trail can show what the model said.
 */
export class ProviderJsonParseError extends Error {
  constructor(message: string, public raw: string) {
    super(message);
    this.name = 'ProviderJsonParseError';
  }
}

/**
 * Strip BOM, common code fences, and "json"/"JSON" markers from a provider response.
 */
function stripJsonChrome(text: string): string {
  let working = text.replace(/^﻿/, '').trim();
  // ```json ... ``` or ``` ... ``` or ~~~json ... ~~~
  working = working
    .replace(/^```\s*json\s*/i, '')
    .replace(/^```\s*/i, '')
    .replace(/^~~~\s*json\s*/i, '')
    .replace(/^~~~\s*/i, '')
    .replace(/```\s*$/i, '')
    .replace(/~~~\s*$/i, '')
    .trim();
  // Some providers prefix with "Output:" or "Response:" before the JSON.
  working = working.replace(/^(?:json|response|output)\s*[:\-]\s*/i, '').trim();
  return working;
}

/**
 * Scan for a balanced top-level JSON object, ignoring braces inside strings.
 * Returns the first balanced substring `{...}` or null. The greedy
 * `\{[\s\S]*\}` regex it replaces would happily match `{"a":1} garbage {"b":2}`.
 */
function findBalancedJsonObject(text: string): string | null {
  const start = text.indexOf('{');
  if (start === -1) return null;
  let depth = 0;
  let inString = false;
  let escape = false;
  for (let i = start; i < text.length; i += 1) {
    const ch = text[i];
    if (inString) {
      if (escape) escape = false;
      else if (ch === '\\') escape = true;
      else if (ch === '"') inString = false;
      continue;
    }
    if (ch === '"') { inString = true; continue; }
    if (ch === '{') depth += 1;
    else if (ch === '}') {
      depth -= 1;
      if (depth === 0) return text.slice(start, i + 1);
    }
  }
  return null;
}

export function parseJsonObject(text: string): unknown {
  const stripped = stripJsonChrome(text);
  try {
    return JSON.parse(stripped);
  } catch {
    const balanced = findBalancedJsonObject(stripped);
    if (!balanced) throw new ProviderJsonParseError('Provider did not return JSON.', text);
    try {
      return JSON.parse(balanced);
    } catch (err) {
      throw new ProviderJsonParseError(
        `Provider returned malformed JSON: ${err instanceof Error ? err.message : String(err)}`,
        text,
      );
    }
  }
}

export type FounderClassificationOutput = z.infer<typeof FounderClassificationSchema>;
export type StartupAnalysisOutput = z.infer<typeof StartupAnalysisSchema>;
export type TechnicalCredibilityOutput = z.infer<typeof TechnicalCredibilitySchema>;
export type MarketPainOutput = z.infer<typeof MarketPainSchema>;
export type HnSignalOutput = z.infer<typeof HnSignalSchema>;
export type InvestorSignalsOutput = z.infer<typeof InvestorSignalsSchema>;
export type RiskAnalysisOutput = z.infer<typeof RiskAnalysisSchema>;
export type VcMemoOutput = z.infer<typeof VcMemoSchema>;
