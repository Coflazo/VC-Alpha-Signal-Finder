/**
 * Per-dimension logistic models.
 *
 * Each dimension is computed as `100 · σ(Σ wᵢ · featureᵢ + bias)` where every
 * feature is normalized to [0,1] in `scoringFeatures.extractFeatures`.
 *
 * Biases are calibrated against `src/tests/fixtures/founderProfile.ts` so that
 * a strong, well-evidenced profile lands around `take_meeting` (total ≥ 72,
 * confidence ≥ 0.55). See `src/tests/unit/scoring.test.ts` for the boundary
 * and monotonicity tests that lock this calibration in.
 */
import type { FeatureRecord } from './scoringFeatures';

export interface DimensionTerm {
  label: string;
  weight: number;
  feature: (f: FeatureRecord) => number;
}

export interface DimensionModel {
  key: 'founderLikelihoodScore'
    | 'collaborativeEdge'
    | 'structuralDemand'
    | 'mutualValue'
    | 'technicalCredibility'
    | 'marketPain'
    | 'marketTiming'
    | 'investorFit'
    | 'outreachUrgency'
    | 'redFlagRisk'
    | 'dataQuality';
  label: string;
  bias: number;
  terms: DimensionTerm[];
  /** Feature keys whose evidence ids should attach to this dimension. */
  evidenceFeatureKeys: string[];
}

export const DIMENSION_MODELS: DimensionModel[] = [
  {
    key: 'founderLikelihoodScore',
    label: 'Founder likelihood',
    bias: -0.6,
    terms: [
      { label: 'has company', weight: 0.5, feature: (f) => f.hasCompany },
      { label: 'public site', weight: 0.4, feature: (f) => f.hasPublicSite },
      { label: 'GitHub', weight: 0.4, feature: (f) => f.hasGithub },
      { label: 'Hacker News', weight: 0.4, feature: (f) => f.hasHn },
      { label: 'founder language', weight: 0.4, feature: (f) => f.founderHits },
      { label: 'builder language', weight: 0.3, feature: (f) => f.builderHits },
      { label: 'student flag', weight: -0.7, feature: (f) => f.studentFlag },
      { label: 'stealth flag', weight: -0.5, feature: (f) => f.stealthFlag },
    ],
    evidenceFeatureKeys: ['hasCompany', 'hasPublicSite', 'hasGithub', 'hasHn', 'founderHits', 'builderHits'],
  },
  {
    key: 'collaborativeEdge',
    label: 'Collaborative edge',
    bias: -0.4,
    terms: [
      { label: 'has company', weight: 0.5, feature: (f) => f.hasCompany },
      { label: 'public site', weight: 0.4, feature: (f) => f.hasPublicSite },
      { label: 'founder language', weight: 0.5, feature: (f) => f.founderHits },
      { label: 'cross-border fit', weight: 0.3, feature: (f) => f.crossBorderHits },
      { label: 'posts cadence', weight: 0.2, feature: (f) => f.postsCount },
    ],
    evidenceFeatureKeys: ['founderHits', 'crossBorderHits', 'hasCompany', 'hasPublicSite'],
  },
  {
    key: 'structuralDemand',
    label: 'Structural demand',
    bias: -0.5,
    terms: [
      { label: 'AI-native vocabulary', weight: 0.6, feature: (f) => f.aiHits },
      { label: 'B2B surface', weight: 0.5, feature: (f) => f.b2bHits },
      { label: 'pain language', weight: 0.4, feature: (f) => f.painHits },
      { label: 'has company', weight: 0.3, feature: (f) => f.hasCompany },
    ],
    evidenceFeatureKeys: ['aiHits', 'b2bHits', 'painHits', 'hasCompany'],
  },
  {
    key: 'mutualValue',
    label: 'Mutual value',
    bias: -0.4,
    terms: [
      { label: 'about richness', weight: 0.4, feature: (f) => f.aboutRichness },
      { label: 'experience count', weight: 0.25, feature: (f) => f.experienceCount },
      { label: 'education count', weight: 0.2, feature: (f) => f.educationCount },
      { label: 'public site', weight: 0.5, feature: (f) => f.hasPublicSite },
      { label: 'evidence density', weight: 0.3, feature: (f) => f.evidenceCount },
    ],
    evidenceFeatureKeys: ['hasPublicSite', 'dataQuality'],
  },
  {
    key: 'technicalCredibility',
    label: 'Technical credibility',
    bias: -0.4,
    terms: [
      { label: 'builder language', weight: 0.4, feature: (f) => f.builderHits },
      { label: 'GitHub', weight: 0.5, feature: (f) => f.hasGithub },
      { label: 'skills listed', weight: 0.3, feature: (f) => f.skillsCount },
      { label: 'technical role', weight: 0.4, feature: (f) => f.hasTechnicalRole },
    ],
    evidenceFeatureKeys: ['hasGithub', 'builderHits', 'hasTechnicalRole'],
  },
  {
    key: 'marketPain',
    label: 'Market pain',
    bias: -0.5,
    terms: [
      { label: 'pain language', weight: 0.5, feature: (f) => f.painHits },
      { label: 'B2B surface', weight: 0.4, feature: (f) => f.b2bHits },
      { label: 'customer mention', weight: 0.3, feature: (f) => f.customerMention },
      { label: 'enterprise mention', weight: 0.3, feature: (f) => f.enterpriseMention },
    ],
    evidenceFeatureKeys: ['painHits', 'b2bHits'],
  },
  {
    key: 'marketTiming',
    label: 'Market timing',
    bias: -0.3,
    terms: [
      { label: 'Hacker News', weight: 0.4, feature: (f) => f.hasHn },
      { label: 'YC mention', weight: 0.3, feature: (f) => f.ycMention },
      { label: 'AI-native vocabulary', weight: 0.4, feature: (f) => f.aiHits },
      { label: 'launch mention', weight: 0.3, feature: (f) => f.launchMention },
    ],
    evidenceFeatureKeys: ['hasHn', 'aiHits'],
  },
  {
    key: 'investorFit',
    label: 'Investor fit',
    bias: -0.3,
    terms: [
      { label: 'investor language', weight: 0.4, feature: (f) => f.investorHits },
      { label: 'cross-border fit', weight: 0.3, feature: (f) => f.crossBorderHits },
      { label: 'B2B surface', weight: 0.3, feature: (f) => f.b2bHits },
      { label: 'AI-native vocabulary', weight: 0.3, feature: (f) => f.aiHits },
    ],
    evidenceFeatureKeys: ['investorHits', 'crossBorderHits', 'b2bHits', 'aiHits'],
  },
  {
    key: 'outreachUrgency',
    label: 'Outreach urgency',
    bias: -0.3,
    terms: [
      { label: 'launch mention', weight: 0.4, feature: (f) => f.launchMention },
      { label: 'hiring mention', weight: 0.3, feature: (f) => f.hiringMention },
      { label: 'investor language', weight: 0.4, feature: (f) => f.investorHits },
      { label: 'posts cadence', weight: 0.3, feature: (f) => f.postsCount },
    ],
    evidenceFeatureKeys: ['investorHits', 'launchMention'],
  },
  {
    key: 'redFlagRisk',
    label: 'Red-flag risk',
    bias: -1.0,
    terms: [
      { label: 'risk language', weight: 0.5, feature: (f) => f.riskHits },
      { label: 'weak founder evidence', weight: 0.5, feature: (f) => f.lowFounderFlag },
      { label: 'no company', weight: 0.4, feature: (f) => 1 - f.hasCompany },
      { label: 'no public site', weight: 0.3, feature: (f) => 1 - f.hasPublicSite },
    ],
    evidenceFeatureKeys: ['riskHits'],
  },
  {
    key: 'dataQuality',
    label: 'Data quality',
    bias: -0.4,
    terms: [
      { label: 'evidence density', weight: 0.35, feature: (f) => f.evidenceCount },
      { label: 'visible links', weight: 0.2, feature: (f) => f.linksCount },
      { label: 'about present', weight: 0.3, feature: (f) => f.aboutPresent },
      { label: 'experience present', weight: 0.3, feature: (f) => f.experiencePresent },
      { label: 'source reliability', weight: 0.4, feature: (f) => f.sourceReliabilityMean },
    ],
    evidenceFeatureKeys: ['dataQuality'],
  },
];

export const DIMENSION_KEYS = DIMENSION_MODELS.map((model) => model.key);
