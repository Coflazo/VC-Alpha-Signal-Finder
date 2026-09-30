export type ThemeMode = 'system' | 'light' | 'dark';

export type DealStatus = 'new' | 'watch' | 'contacted' | 'partner-review' | 'passed';

export type CaptureMode = 'visible_page' | 'selected_text' | 'manual_paste' | 'file_import' | 'approved_api_stub';

export type ProviderName = 'mock' | 'groq' | 'gemini' | 'openrouter' | 'localhost';

export type AnalysisTask =
  | 'extraction'
  | 'founder_classification'
  | 'startup_analysis'
  | 'technical_credibility'
  | 'market_pain'
  | 'hn_signal_analysis'
  | 'github_signal_analysis'
  | 'producthunt_signal_analysis'
  | 'yc_fit_analysis'
  | 'investor_signals'
  | 'risk_analysis'
  | 'vc_memo';

export type ClaimStatus = 'confirmed_fact' | 'strong_inference' | 'weak_signal' | 'contradiction' | 'unknown';

export type SourceReliability =
  | 'high'
  | 'medium_high'
  | 'medium'
  | 'medium_low'
  | 'low';

export type FounderLabel =
  | 'confirmed_founder'
  | 'very_likely_founder'
  | 'possible_founder'
  | 'weak_signal'
  | 'not_enough_evidence';

export type StartupStage =
  | 'idea_stealth'
  | 'pre_product'
  | 'mvp_beta'
  | 'pre_seed'
  | 'seed'
  | 'series_a_plus'
  | 'unknown';

export type Recommendation =
  | 'immediate_outreach'
  | 'take_meeting'
  | 'partner_review'
  | 'monitor'
  | 'pass'
  | 'unknown';

export type GraphNodeType =
  | 'person'
  | 'founder'
  | 'cofounder'
  | 'company'
  | 'investor'
  | 'fund'
  | 'school'
  | 'post'
  | 'hn_story'
  | 'hn_comment'
  | 'github_repo'
  | 'producthunt_launch'
  | 'yc_rfs_topic'
  | 'market'
  | 'competitor'
  | 'evidence'
  | 'risk';

export type GraphEdgeType =
  | 'FOUNDER_OF'
  | 'COFOUNDER_WITH'
  | 'WORKED_AT'
  | 'EDUCATED_AT'
  | 'BUILT_REPO'
  | 'LAUNCHED_ON_HN'
  | 'LAUNCHED_ON_PRODUCT_HUNT'
  | 'MATCHES_YC_RFS'
  | 'INVESTED_IN'
  | 'POSSIBLE_INVESTOR_INTEREST'
  | 'COMMENTED_ON'
  | 'LIKED_POST'
  | 'COMPETES_WITH'
  | 'CLAIMS_TRACTION'
  | 'HAS_RISK'
  | 'SUPPORTED_BY_EVIDENCE'
  | 'WARM_INTRO_PATH';

export interface FundProfile {
  fundName: string;
  stageFocus: StartupStage[];
  geographyFocus: string[];
  sectorThesis: string[];
  checkSize: string;
  portfolioCompanies: string[];
  restrictedCompetitors: string[];
  preferredPartnerInterests: string[];
  excludedSectors: string[];
  outreachStyle: string;
}

export interface ProviderSettings {
  enabled: boolean;
  apiKey: string;
  model?: string;
}

export interface TreeoSettings {
  theme: ThemeMode;
  autoOpenSidePanel: boolean;
  autoAnalyzeProfiles: boolean;
  localOnlyMode: boolean;
  publicResearchEnabled: boolean;
  llmDisclosureAccepted: boolean;
  redactionBeforeLlm: boolean;
  retentionDays: number;
  exportIncludesRawEvidence: boolean;
  aiEndpoint: string;
  aiApiKey: string;
  /** Optional bearer token for the GitHub search API. Bumps rate limit from 60/hr to 5000/hr. */
  githubToken: string;
  /** Optional Product Hunt API v2 token. When blank, Product Hunt research is silently skipped. */
  producthuntToken: string;
  minScoreForReview: number;
  /** Send each capture to the local VC Alpha engine as well as scoring it here. */
  engineEnabled: boolean;
  /** Fund thesis id the engine screens captures against. Blank: its best match. */
  engineThesis: string;
  focusMarkets: string[];
  providerOrder: ProviderName[];
  providers: Record<ProviderName, ProviderSettings>;
  fundProfile: FundProfile;
  weighting: {
    collaborativeEdge: number;
    structuralDemand: number;
    mutualValue: number;
    technicalCredibility: number;
    marketPain: number;
    investorFit: number;
    outreachUrgency: number;
  };
}

export interface SourceMetadata {
  captureMode: CaptureMode;
  sourceUrl?: string;
  sourceTitle?: string;
  sourceType?: string;
  capturedAt: string;
  isLinkedInLike?: boolean;
}

export interface Evidence {
  id: string;
  dealId?: string;
  sourceType: string;
  sourceUrl: string;
  capturedText: string;
  quote: string;
  fieldPath: string;
  reliability: SourceReliability;
  extractionMethod: CaptureMode | 'public_api' | 'public_web' | 'llm' | 'heuristic';
  capturedAt: string;
  freshnessScore: number;
}

export interface Claim {
  id: string;
  dealId?: string;
  subjectId: string;
  subjectType: GraphNodeType | 'analysis';
  claimType: string;
  claimText: string;
  status: ClaimStatus;
  confidence: number;
  evidenceIds: string[];
  createdAt: string;
  expiresAt?: string;
}

export interface CompanyRecord {
  id: string;
  name: string;
  website: string;
  domain: string;
  description: string;
  industry: string;
  location: string;
  teamSize: string;
  fundingStatus: string;
  stageEstimate: StartupStage;
  productStatus: string;
  createdAt: string;
  updatedAt: string;
}

export interface ExperienceRecord {
  id: string;
  personId: string;
  companyId?: string;
  title: string;
  startDate: string;
  endDate: string;
  description: string;
  founderSignal: boolean;
  evidenceIds: string[];
}

export interface EducationRecord {
  id: string;
  personId: string;
  institution: string;
  degree: string;
  field: string;
  startDate: string;
  endDate: string;
  evidenceIds: string[];
}

export interface PostRecord {
  id: string;
  authorPersonId?: string;
  platform: string;
  url: string;
  text: string;
  date: string;
  engagementSummary: string;
  extractedClaims: string[];
  evidenceIds: string[];
}

export interface RelationshipRecord {
  id: string;
  sourceId: string;
  targetId: string;
  sourceType: GraphNodeType;
  targetType: GraphNodeType;
  relationshipType: GraphEdgeType;
  confidence: number;
  evidenceIds: string[];
}

export interface InvestorSignalRecord {
  id: string;
  investorPersonId?: string;
  investorFirmId?: string;
  targetPersonId?: string;
  targetCompanyId?: string;
  signalType: string;
  strength: 'confirmed' | 'strong' | 'weak' | 'unknown';
  confidence: number;
  evidenceIds: string[];
}

export interface HnStoryRecord {
  id: string;
  hnId: number;
  type: string;
  title: string;
  url: string;
  author: string;
  score: number;
  commentCount: number;
  createdAt: string;
  retrievedAt: string;
  tags: string[];
  relatedCompanyIds: string[];
  relatedPersonIds: string[];
}

export interface HnCommentRecord {
  id: string;
  hnId: number;
  storyId: number;
  author: string;
  text: string;
  createdAt: string;
  sentiment: 'positive' | 'neutral' | 'negative' | 'mixed';
  painSignals: string[];
  productSignals: string[];
  evidenceIds: string[];
}

export interface GithubRepoRecord {
  id: string;
  owner: string;
  name: string;
  url: string;
  stars: number;
  forks: number;
  openIssues: number;
  language: string;
  lastCommitAt: string;
  readmeQuality: number;
  testDetected: boolean;
  docsDetected: boolean;
  releaseCount: number;
  evidenceIds: string[];
}

export interface ProductHuntLaunchRecord {
  id: string;
  name: string;
  url: string;
  tagline: string;
  makerNames: string[];
  launchDate: string;
  votes: number;
  comments: number;
  relatedCompanyId?: string;
  relatedPersonIds: string[];
  evidenceIds: string[];
}

export interface YcSignalRecord {
  id: string;
  companyId?: string;
  rfsTopic: string;
  fitScore: number;
  rationale: string;
  evidenceIds: string[];
}

export interface WatchlistRecord {
  id: string;
  personId?: string;
  companyId?: string;
  status: 'active' | 'paused' | 'archived';
  priority: number;
  notes: string;
  lastCheckedAt?: string;
  nextCheckAt?: string;
}

export interface AlertRecord {
  id: string;
  watchlistId: string;
  alertType: string;
  message: string;
  severity: 'info' | 'warning' | 'urgent';
  createdAt: string;
  readAt?: string;
  evidenceIds: string[];
}

export interface ExtractedProfile {
  id?: string;
  name: string;
  headline: string;
  location: string;
  about: string;
  profileUrl: string;
  profileImageUrl: string;
  companyName: string;
  companyUrl: string;
  companyWebsite?: string;
  rawText?: string;
  currentRoles: string[];
  pastRoles: string[];
  experience: string[];
  education: string[];
  skills: string[];
  languages: string[];
  posts: string[];
  interactions?: string[];
  visibleLinks: string[];
  hnUsernames: string[];
  githubUsernames: string[];
  productHuntUsernames: string[];
  sourceMetadata?: SourceMetadata;
  evidenceIds?: string[];
  extractedAt: string;
}

export interface ScoringSignal {
  label: string;
  evidence: string;
  evidenceIds?: string[];
  weight: number;
  confidence: number;
  principle:
    | 'Collaborative Edge'
    | 'Structural Demand'
    | 'Mutual Value'
    | 'Technical Credibility'
    | 'Market Pain'
    | 'Investor Fit'
    | 'Outreach Urgency'
    | 'Risk';
}

export interface StageEstimate {
  stage: StartupStage;
  confidence: number;
  evidenceIds: string[];
  missingEvidence: string[];
}

export interface Scorecard {
  founderQuality: number;
  founderMarketFit: number;
  technicalCredibility: number;
  commercialCredibility: number;
  marketSize: number;
  timing: number;
  traction: number;
  fundability: number;
  networkQuality: number;
  redFlagRisk: number;
  dataQuality: number;
}

export interface DealScore {
  /** Score schema version. v1 is legacy keyword math; v2 is logistic + dataQualityGate. */
  version?: 'v1' | 'v2';
  total: number;
  collaborativeEdge: number;
  structuralDemand: number;
  mutualValue: number;
  technicalCredibility: number;
  marketPain: number;
  marketTiming: number;
  investorFit: number;
  outreachUrgency: number;
  redFlagRisk: number;
  dataQuality: number;
  founderLikelihoodScore: number;
  founderLabel: FounderLabel;
  confidence: number;
  stage: StartupStage | 'Pre-idea' | 'Idea' | 'Pre-seed' | 'Seed' | 'Series A+' | 'Unknown';
  stageEstimate: StageEstimate;
  recommendation: 'High priority' | 'Review' | 'Watch' | 'Pass' | Recommendation;
  summary: string;
  nextAction: string;
  signals: ScoringSignal[];
  risks: string[];
  missingEvidence: string[];
  scorecard: Scorecard;
}

export interface StartupAnalysis {
  companySummary: string;
  productHypothesis: string;
  stageEstimate: StageEstimate;
  tractionSignals: string[];
  businessModel: string;
  credibilitySignals: string[];
  technicalCredibility: string;
  missingInfo: string[];
}

export interface TechnicalCredibilityAnalysis {
  repoQuality: string;
  technicalDepth: string;
  builderProof: string[];
  dependencyRisk: string;
  moat: string;
  score: number;
  evidenceIds: string[];
}

export interface MarketPainAnalysis {
  marketCategory: string;
  customerSegment: string;
  painFrequency: number;
  painIntensity: number;
  buyerClarity: string;
  willingnessToPay: string;
  existingWorkarounds: string[];
  competitors: string[];
  confidence: number;
  evidenceIds: string[];
}

export interface HnSignalAnalysis {
  showHnLaunches: string[];
  askHnPainClusters: string[];
  founderHnCredibility: string;
  categoryHeat: number;
  developerResonance: number;
  objections: string[];
  customerLanguage: string[];
  competitorMentions: string[];
  evidenceIds: string[];
}

export interface InvestorSignalsAnalysis {
  confirmedInvestors: string[];
  possibleInvestorInterest: string[];
  weakSignals: string[];
  warmIntroPaths: string[];
  fundThesisFit: string;
  portfolioConflicts: string[];
  confidence: number;
  evidenceIds: string[];
}

export interface RiskAnalysis {
  redFlags: string[];
  inconsistencies: string[];
  overclaimingRisk: string;
  dataQualityWarnings: string[];
  privacyWarnings: string[];
}

export interface VcMemo {
  thirtySecondSummary: string;
  onePageMemo: string;
  recommendation: Recommendation;
  outreachUrgency: string;
  firstCallQuestions: string[];
  scorecard: Scorecard;
}

export interface GraphNode {
  id: string;
  type: GraphNodeType;
  label: string;
  subtitle?: string;
  confidence?: number;
  evidenceIds: string[];
  data?: Record<string, unknown>;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  type: GraphEdgeType;
  confidence: number;
  evidenceIds: string[];
  label?: string;
}

export interface FounderGraph {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface AnalysisRunRecord {
  id: string;
  dealId?: string;
  task?: AnalysisTask;
  personId?: string;
  companyId?: string;
  createdAt: string;
  modelProvider: ProviderName | 'deterministic';
  modelName: string;
  promptHash: string;
  outputJson: unknown;
  warnings: string[];
}

export interface TreeoDeal {
  id: string;
  profile: ExtractedProfile;
  company?: CompanyRecord;
  score: DealScore;
  status: DealStatus;
  notes: string;
  tags: string[];
  evidence: Evidence[];
  claims: Claim[];
  startupAnalysis?: StartupAnalysis;
  technicalCredibility?: TechnicalCredibilityAnalysis;
  marketPain?: MarketPainAnalysis;
  hnSignals?: HnSignalAnalysis;
  investorSignals?: InvestorSignalsAnalysis;
  riskAnalysis?: RiskAnalysis;
  memo?: VcMemo;
  researchQueries?: string[];
  hnStories?: HnStoryRecord[];
  hnComments?: HnCommentRecord[];
  githubRepos?: GithubRepoRecord[];
  productHuntLaunches?: ProductHuntLaunchRecord[];
  ycSignals?: YcSignalRecord[];
  graph?: FounderGraph;
  /** What the local VC Alpha engine made of the same capture, or why it could not say. */
  engine?: EngineResult;
  createdAt: string;
  updatedAt: string;
}

/** One of the engine's six triage signals, with the quote behind it. */
export interface EngineSignal {
  key: string;
  score: number;
  quote: string;
}

/** The response of POST /api/capture on the VC Alpha engine. */
export interface EngineVerdict {
  id: string | null;
  status: 'scored' | 'stored' | 'excluded';
  source: string | null;
  thesis: { id: string; name: string } | null;
  similarity: number | null;
  confidence: number | null;
  score: number | null;
  stage: string | null;
  summary: string | null;
  signals: EngineSignal[];
  note: string;
}

export type EngineResult = { ok: true; verdict: EngineVerdict } | { ok: false; reason: string };

export interface PipelineStats {
  totalDeals: number;
  reviewReady: number;
  averageScore: number;
  aiNativeCount: number;
  urgentCount: number;
}

export type RuntimeMessage =
  | { type: 'TREEO_GET_PROFILE' }
  | { type: 'TREEO_GET_VISIBLE_PAGE' }
  | { type: 'TREEO_GET_SELECTED_TEXT' }
  | { type: 'TREEO_PROFILE_RESULT'; payload: ExtractedProfile }
  | { type: 'TREEO_ANALYZE_CURRENT'; payload?: { tabId?: number; mode?: CaptureMode; rawText?: string; sourceUrl?: string; sourceTitle?: string; private?: boolean } }
  | { type: 'TREEO_ANALYSIS_COMPLETE'; payload: TreeoDeal }
  | { type: 'TREEO_SAVE_DEAL'; payload: TreeoDeal }
  | { type: 'TREEO_UPDATE_DEAL'; payload: TreeoDeal }
  | { type: 'TREEO_GET_DEALS' }
  | { type: 'TREEO_GET_LAST_DEAL' }
  | { type: 'TREEO_OPEN_PANEL' }
  | { type: 'TREEO_DELETE_ALL_DATA' }
  | { type: 'TREEO_GET_RUNS'; payload: { dealId: string } }
  | { type: 'TREEO_ERROR'; payload: { message: string } };
