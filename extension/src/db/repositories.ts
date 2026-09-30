import { DEFAULT_FOCUS_MARKETS } from '../lib/brand';
import type { AnalysisRunRecord, DealScore, Evidence, FounderGraph, TreeoDeal, TreeoSettings, ThemeMode } from '../lib/types';
import { makeId, nowIso } from '../lib/utils';
import { db, getSettingValue, saveSettingValue } from './schema';

const LEGACY_KEYS = {
  settings: 'treeo_scout_settings_v1',
  deals: 'treeo_scout_deals_v1',
  lastDeal: 'treeo_scout_last_deal_v1',
  migrated: 'treeo_scout_indexeddb_migrated_v1',
};

export const DEFAULT_SETTINGS: TreeoSettings = {
  theme: 'system',
  autoOpenSidePanel: true,
  autoAnalyzeProfiles: false,
  localOnlyMode: true,
  publicResearchEnabled: false,
  llmDisclosureAccepted: false,
  redactionBeforeLlm: true,
  retentionDays: 365,
  exportIncludesRawEvidence: false,
  aiEndpoint: 'http://localhost:4000/v1/chat/completions',
  aiApiKey: '',
  githubToken: '',
  producthuntToken: '',
  minScoreForReview: 72,
  focusMarkets: DEFAULT_FOCUS_MARKETS,
  providerOrder: ['mock', 'groq', 'gemini', 'openrouter', 'localhost'],
  providers: {
    mock: { enabled: true, apiKey: '', model: 'mock-treeo-analyst' },
    groq: { enabled: false, apiKey: '', model: 'llama-3.3-70b-versatile' },
    gemini: { enabled: false, apiKey: '', model: 'gemini-2.5-flash-lite' },
    openrouter: { enabled: false, apiKey: '', model: 'qwen/qwen3-235b-a22b:free' },
    localhost: { enabled: false, apiKey: '', model: 'auto' },
  },
  fundProfile: {
    fundName: 'Treeo VC',
    stageFocus: ['idea_stealth', 'pre_product', 'mvp_beta', 'pre_seed'],
    geographyFocus: ['United States', 'Europe', 'Turkey', 'global'],
    sectorThesis: DEFAULT_FOCUS_MARKETS,
    checkSize: '$100k-$1m',
    portfolioCompanies: [],
    restrictedCompetitors: [],
    preferredPartnerInterests: ['AI-native B2B', 'vertical SaaS', 'data infrastructure'],
    excludedSectors: [],
    outreachStyle: 'Direct, evidence-first, founder-friendly.',
  },
  weighting: {
    collaborativeEdge: 0.18,
    structuralDemand: 0.18,
    mutualValue: 0.12,
    technicalCredibility: 0.14,
    marketPain: 0.13,
    investorFit: 0.11,
    outreachUrgency: 0.14,
  },
};

function hasChromeStorage(): boolean {
  return typeof chrome !== 'undefined' && Boolean(chrome.storage?.local);
}

function mergeSettings(partial: Partial<TreeoSettings> | undefined): TreeoSettings {
  return {
    ...DEFAULT_SETTINGS,
    ...partial,
    providers: {
      ...DEFAULT_SETTINGS.providers,
      ...(partial?.providers ?? {}),
      mock: { ...DEFAULT_SETTINGS.providers.mock, ...(partial?.providers?.mock ?? {}) },
      groq: { ...DEFAULT_SETTINGS.providers.groq, ...(partial?.providers?.groq ?? {}) },
      gemini: { ...DEFAULT_SETTINGS.providers.gemini, ...(partial?.providers?.gemini ?? {}) },
      openrouter: { ...DEFAULT_SETTINGS.providers.openrouter, ...(partial?.providers?.openrouter ?? {}) },
      localhost: { ...DEFAULT_SETTINGS.providers.localhost, ...(partial?.providers?.localhost ?? {}) },
    },
    fundProfile: {
      ...DEFAULT_SETTINGS.fundProfile,
      ...(partial?.fundProfile ?? {}),
    },
    weighting: {
      ...DEFAULT_SETTINGS.weighting,
      ...(partial?.weighting ?? {}),
    },
  };
}

function emptyScore(score: Partial<DealScore> | undefined): DealScore {
  const total = score?.total ?? 0;
  return {
    total,
    collaborativeEdge: score?.collaborativeEdge ?? 0,
    structuralDemand: score?.structuralDemand ?? 0,
    mutualValue: score?.mutualValue ?? 0,
    technicalCredibility: score?.technicalCredibility ?? 0,
    marketPain: score?.marketPain ?? 0,
    marketTiming: score?.marketTiming ?? 0,
    investorFit: score?.investorFit ?? 0,
    outreachUrgency: score?.outreachUrgency ?? 0,
    redFlagRisk: score?.redFlagRisk ?? 0,
    dataQuality: score?.dataQuality ?? score?.confidence ?? 0,
    founderLikelihoodScore: score?.founderLikelihoodScore ?? total,
    founderLabel: score?.founderLabel ?? 'not_enough_evidence',
    confidence: score?.confidence ?? 0,
    stage: score?.stage ?? 'Unknown',
    stageEstimate: score?.stageEstimate ?? {
      stage: 'unknown',
      confidence: 0,
      evidenceIds: [],
      missingEvidence: ['profile evidence'],
    },
    recommendation: score?.recommendation ?? 'Watch',
    summary: score?.summary ?? '',
    nextAction: score?.nextAction ?? 'Collect more evidence before taking action.',
    signals: score?.signals ?? [],
    risks: score?.risks ?? [],
    missingEvidence: score?.missingEvidence ?? [],
    scorecard: score?.scorecard ?? {
      founderQuality: 0,
      founderMarketFit: 0,
      technicalCredibility: 0,
      commercialCredibility: 0,
      marketSize: 0,
      timing: 0,
      traction: 0,
      fundability: 0,
      networkQuality: 0,
      redFlagRisk: 0,
      dataQuality: 0,
    },
  };
}

export function normalizeDeal(deal: TreeoDeal): TreeoDeal {
  const createdAt = deal.createdAt || nowIso();
  const dealId = deal.id || makeId('deal');
  const profileId = deal.profile.id || makeId('person');
  const evidence = (deal.evidence ?? []).map((item) => ({ ...item, dealId: item.dealId ?? dealId }));
  const claims = (deal.claims ?? []).map((claim) => ({ ...claim, dealId: claim.dealId ?? dealId }));
  const graph: FounderGraph | undefined = deal.graph;
  const score = emptyScore(deal.score);
  // Mark legacy deals so the UI can show a "v1 scoring" badge and so the
  // recompute path can skip them.
  if (!score.version) score.version = 'v1';

  return {
    ...deal,
    id: dealId,
    profile: {
      ...deal.profile,
      id: profileId,
      currentRoles: deal.profile.currentRoles ?? [],
      pastRoles: deal.profile.pastRoles ?? [],
      skills: deal.profile.skills ?? [],
      languages: deal.profile.languages ?? [],
      hnUsernames: deal.profile.hnUsernames ?? [],
      githubUsernames: deal.profile.githubUsernames ?? [],
      productHuntUsernames: deal.profile.productHuntUsernames ?? [],
      evidenceIds: deal.profile.evidenceIds ?? evidence.map((item) => item.id),
      extractedAt: deal.profile.extractedAt || createdAt,
    },
    score,
    status: deal.status ?? 'new',
    notes: deal.notes ?? '',
    tags: deal.tags ?? [],
    evidence,
    claims,
    graph,
    createdAt,
    updatedAt: deal.updatedAt || createdAt,
  };
}

export async function evidenceForClaim(claimId: string): Promise<Evidence[]> {
  const claim = await db.claims.get(claimId);
  if (!claim) return [];
  if (!claim.evidenceIds.length) return [];
  return db.evidence.where('id').anyOf(claim.evidenceIds).toArray();
}

export async function claimsForEvidence(evidenceId: string): Promise<import('../lib/types').Claim[]> {
  return (await db.claims.toArray()).filter((claim) => claim.evidenceIds.includes(evidenceId));
}

export async function migrateLegacyStorage(): Promise<void> {
  if (!hasChromeStorage()) return;
  const marker = await chrome.storage.local.get(LEGACY_KEYS.migrated);
  if (marker[LEGACY_KEYS.migrated]) return;

  const stored = await chrome.storage.local.get([LEGACY_KEYS.settings, LEGACY_KEYS.deals, LEGACY_KEYS.lastDeal]);
  const legacySettings = stored[LEGACY_KEYS.settings] as Partial<TreeoSettings> | undefined;
  const legacyDeals = (stored[LEGACY_KEYS.deals] as TreeoDeal[] | undefined) ?? [];
  const lastDeal = stored[LEGACY_KEYS.lastDeal] as TreeoDeal | undefined;

  if (legacySettings) {
    await saveSettings(mergeSettings(legacySettings));
  }

  const deals = [...legacyDeals];
  if (lastDeal && !deals.some((deal) => deal.id === lastDeal.id)) deals.unshift(lastDeal);
  if (deals.length) {
    await db.transaction('rw', db.deals, db.people, db.evidence, db.claims, async () => {
      for (const deal of deals) {
        const normalized = normalizeDeal(deal);
        await db.deals.put(normalized);
        await db.people.put(normalized.profile);
        if (normalized.evidence.length) await db.evidence.bulkPut(normalized.evidence);
        if (normalized.claims.length) await db.claims.bulkPut(normalized.claims);
      }
    });
  }

  await chrome.storage.local.set({ [LEGACY_KEYS.migrated]: true });
}

export async function getSettings(): Promise<TreeoSettings> {
  await migrateLegacyStorage();
  return mergeSettings(await getSettingValue<Partial<TreeoSettings>>('settings'));
}

export async function saveSettings(settings: TreeoSettings): Promise<void> {
  await saveSettingValue('settings', mergeSettings(settings));
}

export async function getDeals(): Promise<TreeoDeal[]> {
  await migrateLegacyStorage();
  return (await db.deals.orderBy('updatedAt').reverse().toArray()).map(normalizeDeal);
}

export async function getLastDeal(): Promise<TreeoDeal | null> {
  await migrateLegacyStorage();
  const deal = await db.deals.orderBy('updatedAt').last();
  return deal ? normalizeDeal(deal) : null;
}

export async function saveDeal(deal: TreeoDeal): Promise<void> {
  const normalized = normalizeDeal(deal);
  await db.transaction('rw', db.deals, db.people, db.companies, db.evidence, db.claims, async () => {
    await db.deals.put(normalized);
    await db.people.put(normalized.profile);
    if (normalized.company) await db.companies.put(normalized.company);
    if (normalized.evidence.length) await db.evidence.bulkPut(normalized.evidence);
    if (normalized.claims.length) await db.claims.bulkPut(normalized.claims);
  });
}

export async function updateDeal(deal: TreeoDeal): Promise<void> {
  await saveDeal({ ...deal, updatedAt: nowIso() });
}

export async function deleteAllLocalData(): Promise<void> {
  await db.transaction(
    'rw',
    [
      db.deals,
      db.people,
      db.companies,
      db.experiences,
      db.education,
      db.posts,
      db.relationships,
      db.investorSignals,
      db.hnStories,
      db.hnComments,
      db.githubRepos,
      db.productHuntLaunches,
      db.ycSignals,
      db.claims,
      db.evidence,
      db.analysisRuns,
      db.watchlist,
      db.alerts,
      db.exports,
    ],
    async () => {
      await Promise.all([
        db.deals.clear(),
        db.people.clear(),
        db.companies.clear(),
        db.experiences.clear(),
        db.education.clear(),
        db.posts.clear(),
        db.relationships.clear(),
        db.investorSignals.clear(),
        db.hnStories.clear(),
        db.hnComments.clear(),
        db.githubRepos.clear(),
        db.productHuntLaunches.clear(),
        db.ycSignals.clear(),
        db.claims.clear(),
        db.evidence.clear(),
        db.analysisRuns.clear(),
        db.watchlist.clear(),
        db.alerts.clear(),
        db.exports.clear(),
      ]);
    },
  );
}

/**
 * Persist a batch of analysis runs emitted by `runFounderAnalysis`. Each run
 * record is tagged with `dealId:<id>` and `task:<task>` in `warnings` so the
 * UI can group by deal and task without a schema bump. (Phase 3 promotes
 * `dealId` to a first-class indexed column.)
 */
export async function saveRuns(runs: AnalysisRunRecord[]): Promise<void> {
  if (!runs.length) return;
  await db.analysisRuns.bulkPut(runs);
}

export async function getRunsForDeal(dealId: string): Promise<AnalysisRunRecord[]> {
  const all = await db.analysisRuns.toArray();
  return all
    .filter((run) => run.warnings.some((tag) => tag === `dealId:${dealId}`))
    .sort((a, b) => a.createdAt.localeCompare(b.createdAt));
}

export function applyTheme(mode: ThemeMode): void {
  const systemDark = window.matchMedia?.('(prefers-color-scheme: dark)').matches;
  const resolved = mode === 'system' ? (systemDark ? 'dark' : 'light') : mode;
  document.documentElement.dataset.theme = resolved;
  document.documentElement.classList.toggle('dark', resolved === 'dark');
}

export function evidenceById(evidence: Evidence[]): Record<string, Evidence> {
  return Object.fromEntries(evidence.map((item) => [item.id, item]));
}
