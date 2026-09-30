/**
 * Scoring v2.
 *
 * Every dimension is `100 · σ(Σ wᵢ · featureᵢ + bias)` where every feature is
 * normalized to [0,1] in `scoringFeatures.extractFeatures`. Recommendations
 * are (total, confidence, redFlagRisk) tuples. The total is the weighted dim
 * sum modulated by a bounded `dataQualityGate ∈ [0.85, 1.10]` — no risk
 * subtraction, no `* 1.18` magic. Risk gates the recommendation tier.
 *
 * Public signatures `scoreProfile`/`createDeal` are preserved.
 */
import { extractFeatures, logistic } from './scoringFeatures';
import { DIMENSION_MODELS, type DimensionModel } from './scoringModel';
import { clamp, makeId, nowIso } from './utils';
import type {
  Claim,
  DealScore,
  Evidence,
  ExtractedProfile,
  FounderLabel,
  ScoringSignal,
  Scorecard,
  StageEstimate,
  StartupStage,
  TreeoDeal,
  TreeoSettings,
} from './types';

export const SCORE_VERSION = 'v2';

function evidenceIdFor(evidence: Evidence[], fieldPath: string): string[] {
  const hit = evidence.find((item) => item.fieldPath === fieldPath);
  return hit ? [hit.id] : [];
}

function evidenceFromProfile(profile: ExtractedProfile): Evidence[] {
  const sourceUrl = profile.sourceMetadata?.sourceUrl || profile.profileUrl || '';
  const sourceType = profile.sourceMetadata?.sourceType || (profile.sourceMetadata?.isLinkedInLike ? 'linkedin_visible_page' : 'user_input');
  const capturedAt = profile.sourceMetadata?.capturedAt || profile.extractedAt || nowIso();
  const reliability = profile.sourceMetadata?.captureMode === 'manual_paste' ? 'medium_high' : 'medium';
  const items: Array<[string, string, string]> = [
    ['profile.name', profile.name, profile.name],
    ['profile.headline', profile.headline, profile.headline],
    ['profile.about', profile.about, profile.about],
    ['profile.companyName', profile.companyName, profile.companyName],
    ['profile.experience', profile.experience.join('\n'), profile.experience[0] ?? ''],
    ['profile.posts', profile.posts.join('\n'), profile.posts[0] ?? ''],
    ['profile.links', profile.visibleLinks.join('\n'), profile.visibleLinks[0] ?? ''],
  ];

  return items
    .filter(([, text]) => text.trim().length > 0)
    .map(([fieldPath, text, quote]) => ({
      id: makeId('ev'),
      sourceType,
      sourceUrl,
      capturedText: text.slice(0, 4000),
      quote: (quote || text).slice(0, 500),
      fieldPath,
      reliability,
      extractionMethod: profile.sourceMetadata?.captureMode ?? 'visible_page',
      capturedAt,
      freshnessScore: 1,
    }));
}

function stageFromProfile(profile: ExtractedProfile, evidence: Evidence[]): StageEstimate {
  const corpus = [
    profile.headline,
    profile.about,
    profile.rawText,
    ...profile.posts,
    ...profile.experience,
  ].join(' ').toLowerCase();

  const checks: Array<[StartupStage, string[], number, string[]]> = [
    ['series_a_plus', ['series a', 'series b', 'series c', 'growth round'], 0.75, ['recent funding announcement']],
    ['seed', [' seed ', 'seed round', 'seed-stage'], 0.72, ['round size', 'lead investor']],
    ['pre_seed', ['pre-seed', 'preseed', 'angel round'], 0.7, ['product traction', 'customer proof']],
    ['mvp_beta', ['beta', 'pilot', 'demo', 'launched', 'public product'], 0.68, ['active customer proof']],
    ['pre_product', ['waitlist', 'coming soon', 'landing page'], 0.58, ['demo', 'customer usage']],
    ['idea_stealth', ['stealth', 'building', 'exploring'], 0.5, ['website', 'product proof']],
  ];
  const found = checks.find(([, terms]) => terms.some((term) => corpus.includes(term)));
  if (!found) {
    return {
      stage: 'unknown',
      confidence: 0.35,
      evidenceIds: [],
      missingEvidence: ['website', 'product proof', 'funding status', 'customer proof'],
    };
  }
  return {
    stage: found[0],
    confidence: found[2],
    evidenceIds: evidence.map((item) => item.id).slice(0, 2),
    missingEvidence: found[3],
  };
}

function legacyStageLabel(stage: StartupStage): DealScore['stage'] {
  if (stage === 'idea_stealth') return 'Idea';
  if (stage === 'pre_seed') return 'Pre-seed';
  if (stage === 'seed') return 'Seed';
  if (stage === 'series_a_plus') return 'Series A+';
  if (stage === 'pre_product' || stage === 'mvp_beta') return 'Pre-seed';
  return 'Unknown';
}

function founderLabel(score: number): FounderLabel {
  if (score >= 80) return 'confirmed_founder';
  if (score >= 60) return 'very_likely_founder';
  if (score >= 40) return 'possible_founder';
  if (score >= 20) return 'weak_signal';
  return 'not_enough_evidence';
}

function computeDimension(
  model: DimensionModel,
  features: Parameters<DimensionModel['terms'][number]['feature']>[0],
): number {
  const linear = model.terms.reduce((sum, term) => sum + term.weight * term.feature(features), 0) + model.bias;
  return Math.round(100 * logistic(linear));
}

/**
 * Recommendation thresholds. Each tier is (total, confidence, redFlagRisk). The
 * first tier whose conditions all clear wins.
 *
 * Replaces single-number bands. Saved deals scored with v1 keep their stored
 * recommendation until re-analyzed; this function only runs on fresh scoring.
 */
const RECOMMENDATION_TIERS: Array<{
  recommendation: DealScore['recommendation'];
  total: number;
  confidence: number;
  maxRisk: number;
  nextAction: string;
}> = [
  {
    recommendation: 'immediate_outreach',
    total: 80,
    confidence: 0.65,
    maxRisk: 40,
    nextAction: 'Reach out today after verifying product proof and conflict risk.',
  },
  {
    recommendation: 'take_meeting',
    total: 72,
    confidence: 0.55,
    maxRisk: 55,
    nextAction: 'Prepare a first-call brief and verify technical proof, market pain, and current raise status.',
  },
  {
    recommendation: 'partner_review',
    total: 64,
    confidence: 0.50,
    maxRisk: 70,
    nextAction: 'Route to partner review with missing evidence highlighted.',
  },
  {
    recommendation: 'monitor',
    total: 42,
    confidence: 0.30,
    maxRisk: 85,
    nextAction: 'Add to watchlist and monitor HN, GitHub, launches, and public company updates.',
  },
];

function pickRecommendation(total: number, confidence: number, risk: number): { recommendation: DealScore['recommendation']; nextAction: string } {
  for (const tier of RECOMMENDATION_TIERS) {
    if (total >= tier.total && confidence >= tier.confidence && risk <= tier.maxRisk) {
      return { recommendation: tier.recommendation, nextAction: tier.nextAction };
    }
  }
  return {
    recommendation: 'pass',
    nextAction: 'Pass for now unless new evidence changes founder, product, or market confidence.',
  };
}

function addSignal(
  list: ScoringSignal[],
  principle: ScoringSignal['principle'],
  label: string,
  evidenceText: string,
  weight: number,
  confidence: number,
  evidenceIds: string[],
): void {
  list.push({ principle, label, evidence: evidenceText, weight, confidence, evidenceIds });
}

function buildSummary(profile: ExtractedProfile, founderScore: number, aiHits: string[], b2bHits: string[], crossBorderHits: string[]): string {
  const startup = profile.companyName || 'the company';
  const founder = founderScore >= 60 ? 'strong founder signal' : founderScore >= 40 ? 'possible founder signal' : 'weak founder evidence';
  const ai = aiHits.length ? `AI signal: ${aiHits.slice(0, 3).join(', ')}` : 'AI signal unknown';
  const buyer = b2bHits.length ? `B2B surface: ${b2bHits.slice(0, 3).join(', ')}` : 'buyer surface unknown';
  const bridge = crossBorderHits.length ? `Treeo fit: ${crossBorderHits.slice(0, 3).join(', ')}` : 'Treeo cross-border fit unproven';
  return `${profile.name || 'This profile'} has ${founder} around ${startup}. ${ai}. ${buyer}. ${bridge}.`;
}

export function scoreProfile(profile: ExtractedProfile, settings: TreeoSettings, existingEvidence: Evidence[] = []): DealScore {
  const evidence = existingEvidence.length ? existingEvidence : evidenceFromProfile(profile);
  const features = extractFeatures(profile, evidence, settings);

  // Compute founder score first so the risk dimension can fold it in via lowFounderFlag.
  const founderModel = DIMENSION_MODELS.find((m) => m.key === 'founderLikelihoodScore')!;
  const founderLikelihoodScore = computeDimension(founderModel, features);
  features.lowFounderFlag = founderLikelihoodScore < 35 ? 1 : 0;

  const dimensionScores: Record<DimensionModel['key'], number> = {
    founderLikelihoodScore,
    collaborativeEdge: 0,
    structuralDemand: 0,
    mutualValue: 0,
    technicalCredibility: 0,
    marketPain: 0,
    marketTiming: 0,
    investorFit: 0,
    outreachUrgency: 0,
    redFlagRisk: 0,
    dataQuality: 0,
  };
  for (const model of DIMENSION_MODELS) {
    if (model.key === 'founderLikelihoodScore') continue;
    dimensionScores[model.key] = computeDimension(model, features);
  }

  const {
    collaborativeEdge, structuralDemand, mutualValue, technicalCredibility,
    marketPain, marketTiming, investorFit, outreachUrgency, redFlagRisk, dataQuality,
  } = dimensionScores;

  // Emit human-readable signals tied to the dominant features. The UI consumes these.
  const signals: ScoringSignal[] = [];
  const evMap = features.evidenceIdsByFeature;
  if (features.founderHits > 0) {
    addSignal(signals, 'Collaborative Edge', 'Founder/operator language', features.rawHits.founder.slice(0, 5).join(', '), 0.5, 0.78, evMap.founderHits);
  }
  if (features.builderHits > 0) {
    addSignal(signals, 'Technical Credibility', 'Builder proof language', features.rawHits.builder.slice(0, 5).join(', '), 0.4, 0.7, evMap.builderHits);
  }
  if (features.crossBorderHits > 0) {
    addSignal(signals, 'Collaborative Edge', 'Cross-border fit', features.rawHits.crossBorder.slice(0, 5).join(', '), 0.3, 0.64, evMap.crossBorderHits);
  }
  if (features.aiHits > 0) {
    addSignal(signals, 'Structural Demand', 'AI-native vocabulary', features.rawHits.ai.slice(0, 5).join(', '), 0.6, 0.72, evMap.aiHits);
  }
  if (features.b2bHits > 0 || features.painHits > 0) {
    const merged = [...features.rawHits.b2b, ...features.rawHits.pain].slice(0, 6).join(', ');
    addSignal(signals, 'Market Pain', 'B2B pain surface', merged, 0.5, 0.68, [...evMap.b2bHits, ...evMap.painHits]);
  }
  if (features.hasPublicSite) {
    addSignal(signals, 'Mutual Value', 'Public proof link', 'company website or non-LinkedIn public link', 0.5, 0.7, evMap.hasPublicSite);
  }
  if (features.investorHits > 0) {
    addSignal(signals, 'Investor Fit', 'Fundraising or investor context', features.rawHits.investor.slice(0, 4).join(', '), 0.4, 0.6, evMap.investorHits);
  }
  if (features.riskHits > 0 || features.stealthFlag) {
    const items = [...features.rawHits.risk, features.stealthFlag ? 'stealth flag' : ''].filter(Boolean);
    addSignal(signals, 'Risk', 'Risk language', items.slice(0, 5).join(', '), 0.5, 0.55, evMap.riskHits);
  }

  // Honest confidence: multiplicative blend of data quality, evidence coverage,
  // source reliability, and absolute evidence count. The multiplicative form is
  // critical — additive confidence floats high on weak profiles because the
  // medium_high reliability default contributes a free bonus.
  const evidenceCoverage = signals.length === 0 ? 0 : signals.filter((s) => (s.evidenceIds ?? []).length > 0).length / signals.length;
  const evidenceCountFactor = Math.min(evidence.length / 6, 1);
  const confidence = clamp(
    Math.pow(dataQuality / 100, 0.9)
    * (0.5 + 0.5 * evidenceCoverage)
    * (0.5 + 0.5 * features.sourceReliabilityMean)
    * evidenceCountFactor,
    0,
    1,
  );

  const weighted = (
    collaborativeEdge * settings.weighting.collaborativeEdge
    + structuralDemand * settings.weighting.structuralDemand
    + mutualValue * settings.weighting.mutualValue
    + technicalCredibility * settings.weighting.technicalCredibility
    + marketPain * settings.weighting.marketPain
    + investorFit * settings.weighting.investorFit
    + outreachUrgency * settings.weighting.outreachUrgency
  );
  const dataQualityGate = 0.85 + 0.25 * (dataQuality / 100);
  const total = clamp(Math.round(weighted * dataQualityGate));

  const { recommendation, nextAction } = pickRecommendation(total, confidence, redFlagRisk);

  const stageEstimate = stageFromProfile(profile, evidence);

  const scorecard: Scorecard = {
    founderQuality: Math.round(founderLikelihoodScore / 10),
    founderMarketFit: Math.round(clamp((collaborativeEdge + structuralDemand) / 2) / 10),
    technicalCredibility: Math.round(technicalCredibility / 10),
    commercialCredibility: Math.round(clamp((marketPain + investorFit) / 2) / 10),
    marketSize: Math.round(clamp((marketPain + marketTiming) / 2) / 10),
    timing: Math.round(marketTiming / 10),
    traction: Math.round(clamp(features.builderHits * 70 + (features.hasPublicSite ? 30 : 0)) / 10),
    fundability: Math.round(investorFit / 10),
    networkQuality: Math.round(clamp(features.crossBorderHits * 35 + features.investorHits * 35 + features.linksCount * 30) / 10),
    redFlagRisk: Math.round(redFlagRisk / 10),
    dataQuality: Math.round(dataQuality / 10),
  };

  const risks: string[] = [];
  if (!features.aiHits) risks.push('No clear AI-native signal in visible evidence.');
  if (!features.b2bHits) risks.push('B2B buyer or workflow is not explicit yet.');
  if (!features.hasPublicSite) risks.push('No non-LinkedIn public product proof found in visible links.');
  if (founderLikelihoodScore < 40) risks.push('Founder status is not well supported by the captured text.');
  if (redFlagRisk > 45) risks.push('Profile has vague or early-stage wording that needs human diligence.');
  if (features.stealthFlag) risks.push('Stealth mention without a public site or company name.');

  const missingEvidence: string[] = [];
  if (!features.hasPublicSite) missingEvidence.push('company website or product demo');
  if (!features.hasGithub) missingEvidence.push('technical proof from GitHub or product docs');
  if (!features.hasHn) missingEvidence.push('Hacker News or developer-community signal');
  if (!features.investorHits) missingEvidence.push('direct investor or fundraising evidence');
  if (!features.painHits) missingEvidence.push('customer pain language');

  return {
    version: SCORE_VERSION,
    total,
    collaborativeEdge,
    structuralDemand,
    mutualValue,
    technicalCredibility,
    marketPain,
    marketTiming,
    investorFit,
    outreachUrgency,
    redFlagRisk,
    dataQuality,
    founderLikelihoodScore,
    founderLabel: founderLabel(founderLikelihoodScore),
    confidence,
    stage: legacyStageLabel(stageEstimate.stage),
    stageEstimate,
    recommendation,
    summary: buildSummary(profile, founderLikelihoodScore, features.rawHits.ai, features.rawHits.b2b, features.rawHits.crossBorder),
    nextAction,
    signals: signals.sort((a, b) => b.weight - a.weight),
    risks,
    missingEvidence,
    scorecard,
  };
}

function claimFromSignal(signal: ScoringSignal, profileId: string): Claim {
  return {
    id: makeId('claim'),
    subjectId: profileId,
    subjectType: 'founder',
    claimType: signal.label,
    claimText: `${signal.label}: ${signal.evidence}`,
    status: signal.confidence >= 0.75 ? 'strong_inference' : 'weak_signal',
    confidence: signal.confidence,
    evidenceIds: signal.evidenceIds ?? [],
    createdAt: nowIso(),
  };
}

export function createDeal(profile: ExtractedProfile, settings: TreeoSettings): TreeoDeal {
  const now = nowIso();
  const profileId = profile.id || makeId('person');
  const normalizedProfile: ExtractedProfile = {
    ...profile,
    id: profileId,
    currentRoles: profile.currentRoles ?? [],
    pastRoles: profile.pastRoles ?? [],
    skills: profile.skills ?? [],
    languages: profile.languages ?? [],
    hnUsernames: profile.hnUsernames ?? [],
    githubUsernames: profile.githubUsernames ?? [],
    productHuntUsernames: profile.productHuntUsernames ?? [],
    extractedAt: profile.extractedAt || now,
  };
  const evidence = evidenceFromProfile(normalizedProfile);
  const score = scoreProfile(normalizedProfile, settings, evidence);
  const status: TreeoDeal['status'] = score.total >= settings.minScoreForReview
    ? 'partner-review'
    : score.recommendation === 'monitor' || score.recommendation === 'Watch'
      ? 'watch'
      : 'new';

  return {
    id: makeId('deal'),
    profile: {
      ...normalizedProfile,
      evidenceIds: evidence.map((item) => item.id),
    },
    score,
    status,
    notes: '',
    tags: [
      String(score.stage),
      String(score.recommendation),
      score.founderLabel,
      ...score.signals.slice(0, 3).map((s) => s.principle),
    ],
    evidence,
    claims: score.signals.map((signal) => claimFromSignal(signal, profileId)),
    createdAt: now,
    updatedAt: now,
  };
}
