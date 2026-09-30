import { sourceReliabilityFor } from '../research/sourceReliability';
import type { Evidence, ExtractedProfile, SourceReliability, TreeoSettings } from './types';

export const KEYWORDS = {
  AI_NATIVE: [
    'ai', 'artificial intelligence', 'llm', 'agent', 'agents', 'machine learning',
    'ml', 'automation', 'copilot', 'workflow', 'reasoning', 'model', 'data',
  ],
  B2B: [
    'b2b', 'enterprise', 'workflow', 'platform', 'saas', 'developer', 'infrastructure',
    'compliance', 'finance', 'ops', 'supply chain', 'sales', 'security', 'hr',
  ],
  FOUNDER: [
    'founder', 'co-founder', 'cofounder', 'founding', 'ceo', 'cto', 'stealth founder',
    'startup founder',
  ],
  BUILDER: [
    'building', 'built', 'launched', 'demo', 'beta', 'waitlist', 'github', 'api',
    'open source', 'product', 'release', 'ship', 'shipping',
  ],
  MARKET_PAIN: [
    'manual', 'pain', 'broken', 'slow', 'expensive', 'inefficient', 'fragmented',
    'compliance', 'legacy', 'spreadsheet', 'workaround', 'labor shortage',
  ],
  INVESTOR: [
    'fundraising', 'pre-seed', 'preseed', 'seed', 'angel', 'investor', 'vc',
    'accelerator', 'yc', 'techstars', 'raise',
  ],
  CROSS_BORDER: [
    'turkey', 'turkish', 'istanbul', 'ankara', 'immigrant', 'diaspora', 'us market',
    'u.s.', 'united states', 'cross-border', 'global', 'san francisco', 'new york',
    'amsterdam', 'europe',
  ],
  RISK: [
    'stealth', 'advisor', 'consultant', 'fractional', 'student', 'aspiring',
    'exploring', 'idea', 'coming soon',
  ],
  CUSTOMER: ['customer', 'customers', 'design partner', 'design partners', 'paying user'],
  ENTERPRISE: ['enterprise', 'fortune', 'gtm', 'rfp', 'procurement'],
  LAUNCH: ['launch', 'launched', 'ship', 'shipped', 'shipping', 'release', 'public beta'],
  HIRING: ['hiring', 'we are hiring', 'open roles', 'careers'],
  YC: ['yc', 'y combinator', 'ycombinator'],
  TECHNICAL_ROLE: /\b(engineer|engineering|cto|developer|technical|architect|software)\b/i,
} as const;

const RELIABILITY_TO_SCORE: Record<SourceReliability, number> = {
  high: 1.0,
  medium_high: 0.75,
  medium: 0.5,
  medium_low: 0.3,
  low: 0.15,
};

export interface FeatureRecord {
  // Booleans (0 or 1)
  hasCompany: number;
  hasPublicSite: number;
  hasGithub: number;
  hasHn: number;
  hasTechnicalRole: number;
  studentFlag: number;
  stealthFlag: number;
  ycMention: number;
  launchMention: number;
  hiringMention: number;
  customerMention: number;
  enterpriseMention: number;
  aboutPresent: number;
  experiencePresent: number;
  lowFounderFlag: number;

  // Normalized hit counts in [0,1]
  founderHits: number;
  builderHits: number;
  painHits: number;
  investorHits: number;
  crossBorderHits: number;
  riskHits: number;
  aiHits: number;
  b2bHits: number;

  // Other normalized [0,1] features
  postsCount: number;
  experienceCount: number;
  educationCount: number;
  skillsCount: number;
  aboutRichness: number;
  evidenceCount: number;
  linksCount: number;
  sourceReliabilityMean: number;

  // Raw hit lists, kept for signal labels and traceability
  rawHits: {
    founder: string[];
    builder: string[];
    pain: string[];
    investor: string[];
    crossBorder: string[];
    risk: string[];
    ai: string[];
    b2b: string[];
  };

  // Per-feature evidence ids, for traceability
  evidenceIdsByFeature: Record<string, string[]>;
}

function lowerCorpus(profile: ExtractedProfile): string {
  return [
    profile.name,
    profile.headline,
    profile.location,
    profile.about,
    profile.companyName,
    profile.companyWebsite,
    profile.rawText,
    ...profile.currentRoles,
    ...profile.pastRoles,
    ...profile.experience,
    ...profile.education,
    ...profile.skills,
    ...profile.posts,
    ...profile.visibleLinks,
  ].filter(Boolean).join(' ').toLowerCase();
}

function keywordHits(corpus: string, keywords: readonly string[]): string[] {
  return keywords.filter((term) => corpus.includes(term));
}

function publicSiteLink(profile: ExtractedProfile): string | undefined {
  const candidates = [profile.companyWebsite, profile.companyUrl, ...profile.visibleLinks].filter(
    (href): href is string => Boolean(href),
  );
  return candidates.find((href) => !href.includes('linkedin.com') && /^https?:\/\//.test(href));
}

function evidenceIdFor(evidence: Evidence[], fieldPath: string): string[] {
  const hit = evidence.find((item) => item.fieldPath === fieldPath);
  return hit ? [hit.id] : [];
}

function allEvidenceIds(evidence: Evidence[]): string[] {
  return evidence.map((item) => item.id);
}

function meanSourceReliability(evidence: Evidence[]): number {
  if (!evidence.length) return RELIABILITY_TO_SCORE.medium_low;
  const sum = evidence.reduce((total, item) => total + (RELIABILITY_TO_SCORE[item.reliability] ?? 0.3), 0);
  return sum / evidence.length;
}

export function extractFeatures(
  profile: ExtractedProfile,
  evidence: Evidence[],
  _settings: TreeoSettings,
): FeatureRecord {
  const corpus = lowerCorpus(profile);
  const founderHitList = keywordHits(corpus, KEYWORDS.FOUNDER);
  const builderHitList = keywordHits(corpus, KEYWORDS.BUILDER);
  const painHitList = keywordHits(corpus, KEYWORDS.MARKET_PAIN);
  const investorHitList = keywordHits(corpus, KEYWORDS.INVESTOR);
  const crossBorderHitList = keywordHits(corpus, KEYWORDS.CROSS_BORDER);
  const riskHitList = keywordHits(corpus, KEYWORDS.RISK);
  const aiHitList = keywordHits(corpus, KEYWORDS.AI_NATIVE);
  const b2bHitList = keywordHits(corpus, KEYWORDS.B2B);

  const hasCompany = Boolean(profile.companyName || profile.companyWebsite || profile.companyUrl) ? 1 : 0;
  const publicSite = publicSiteLink(profile);
  const hasPublicSite = publicSite ? 1 : 0;
  const hasGithub = profile.githubUsernames.length > 0 || corpus.includes('github.com') ? 1 : 0;
  const hasHn = profile.hnUsernames.length > 0 || corpus.includes('news.ycombinator.com') || corpus.includes('show hn') ? 1 : 0;

  const hasTechnicalRole = profile.experience.some((role) => KEYWORDS.TECHNICAL_ROLE.test(role))
    || profile.currentRoles.some((role) => KEYWORDS.TECHNICAL_ROLE.test(role))
    || profile.pastRoles.some((role) => KEYWORDS.TECHNICAL_ROLE.test(role))
    ? 1
    : 0;

  const studentFlag = founderHitList.length === 0 && corpus.includes('student') ? 1 : 0;
  // Stealth flag: explicit "stealth" mention without a public site or company name
  const stealthFlag = corpus.includes('stealth') && !hasPublicSite && !hasCompany ? 1 : 0;
  const ycMention = KEYWORDS.YC.some((term) => corpus.includes(term)) ? 1 : 0;
  const launchMention = KEYWORDS.LAUNCH.some((term) => corpus.includes(term)) ? 1 : 0;
  const hiringMention = KEYWORDS.HIRING.some((term) => corpus.includes(term)) ? 1 : 0;
  const customerMention = KEYWORDS.CUSTOMER.some((term) => corpus.includes(term)) ? 1 : 0;
  const enterpriseMention = KEYWORDS.ENTERPRISE.some((term) => corpus.includes(term)) ? 1 : 0;
  const aboutPresent = profile.about && profile.about.length > 0 ? 1 : 0;
  const experiencePresent = profile.experience.length > 0 ? 1 : 0;

  const normalize = (count: number, scale: number): number => Math.min(count / scale, 1);

  const aboutRichness = profile.about ? Math.min(profile.about.length / 240, 1) : 0;

  const sourceReliabilityMean = meanSourceReliability(evidence);
  const evidenceCount = normalize(evidence.length, 6);
  const linksCount = normalize(profile.visibleLinks.length, 6);

  const features: FeatureRecord = {
    hasCompany,
    hasPublicSite,
    hasGithub,
    hasHn,
    hasTechnicalRole,
    studentFlag,
    stealthFlag,
    ycMention,
    launchMention,
    hiringMention,
    customerMention,
    enterpriseMention,
    aboutPresent,
    experiencePresent,
    lowFounderFlag: 0, // filled in after founder score is computed

    founderHits: normalize(founderHitList.length, 3),
    builderHits: normalize(builderHitList.length, 4),
    painHits: normalize(painHitList.length, 3),
    investorHits: normalize(investorHitList.length, 3),
    crossBorderHits: normalize(crossBorderHitList.length, 3),
    riskHits: normalize(riskHitList.length, 3),
    aiHits: normalize(aiHitList.length, 3),
    b2bHits: normalize(b2bHitList.length, 3),

    postsCount: normalize(profile.posts.length, 5),
    experienceCount: normalize(profile.experience.length, 3),
    educationCount: normalize(profile.education.length, 2),
    skillsCount: normalize(profile.skills.length, 3),
    aboutRichness,
    evidenceCount,
    linksCount,
    sourceReliabilityMean: profile.sourceMetadata?.sourceUrl
      ? Math.max(sourceReliabilityMean, RELIABILITY_TO_SCORE[sourceReliabilityFor(profile.sourceMetadata.sourceUrl, profile.sourceMetadata.sourceType ?? '')] ?? 0)
      : sourceReliabilityMean,

    rawHits: {
      founder: founderHitList,
      builder: builderHitList,
      pain: painHitList,
      investor: investorHitList,
      crossBorder: crossBorderHitList,
      risk: riskHitList,
      ai: aiHitList,
      b2b: b2bHitList,
    },

    evidenceIdsByFeature: {
      hasCompany: hasCompany ? [...evidenceIdFor(evidence, 'profile.companyName'), ...evidenceIdFor(evidence, 'profile.links')] : [],
      hasPublicSite: hasPublicSite ? evidenceIdFor(evidence, 'profile.links') : [],
      hasGithub: hasGithub ? evidenceIdFor(evidence, 'profile.links') : [],
      hasHn: hasHn ? [...evidenceIdFor(evidence, 'profile.posts'), ...evidenceIdFor(evidence, 'profile.links')] : [],
      hasTechnicalRole: hasTechnicalRole ? [...evidenceIdFor(evidence, 'profile.experience'), ...evidenceIdFor(evidence, 'profile.headline')] : [],
      founderHits: founderHitList.length ? evidenceIdFor(evidence, 'profile.headline') : [],
      builderHits: builderHitList.length ? evidenceIdFor(evidence, 'profile.about') : [],
      painHits: painHitList.length ? evidenceIdFor(evidence, 'profile.about') : [],
      investorHits: investorHitList.length ? evidenceIdFor(evidence, 'profile.posts') : [],
      crossBorderHits: crossBorderHitList.length ? evidenceIdFor(evidence, 'profile.about') : [],
      riskHits: riskHitList.length ? evidenceIdFor(evidence, 'profile.about') : [],
      aiHits: aiHitList.length ? evidenceIdFor(evidence, 'profile.about') : [],
      b2bHits: b2bHitList.length ? evidenceIdFor(evidence, 'profile.about') : [],
      dataQuality: allEvidenceIds(evidence).slice(0, 4),
    },
  };

  return features;
}

/**
 * Logistic activation. Inputs are linear combinations of normalized [0,1] features.
 * Output is in (0,1); multiply by 100 to get a 0..100 dimension score.
 */
export function logistic(linear: number): number {
  return 1 / (1 + Math.exp(-linear));
}

export function dimensionScore(linear: number): number {
  return Math.round(100 * logistic(linear));
}
