/**
 * Dexie database schema for Treeo VC Scout.
 *
 * Migration rule: every additive schema change increments the `version()` and
 * registers an `.upgrade()` block that walks existing rows and back-fills the
 * new columns. Never silently drop data. Never change the database name.
 *
 * Versions:
 *   v1 — initial schema (legacy v1 scoring; one-way evidence links).
 *   v2 — adds `evidence.dealId`, `claims.dealId`, `analysisRuns.dealId`,
 *        `analysisRuns.task`, plus compound indices that make the common
 *        analyst queries (deals by status+score, evidence by deal+field,
 *        runs by deal+task) sub-linear.
 */
import Dexie, { type Table } from 'dexie';
import type {
  AlertRecord,
  AnalysisRunRecord,
  Claim,
  CompanyRecord,
  EducationRecord,
  Evidence,
  ExperienceRecord,
  GithubRepoRecord,
  HnCommentRecord,
  HnStoryRecord,
  InvestorSignalRecord,
  PostRecord,
  ProductHuntLaunchRecord,
  RelationshipRecord,
  TreeoDeal,
  TreeoSettings,
  WatchlistRecord,
  YcSignalRecord,
} from '../lib/types';

export interface SettingRecord {
  key: string;
  value: unknown;
  updatedAt: string;
}

export interface ExportRecord {
  id: string;
  profileId: string;
  format: 'csv' | 'xlsx' | 'json' | 'markdown' | 'html' | 'graph-json' | 'graph-html';
  fileName: string;
  createdAt: string;
}

export class TreeoDatabase extends Dexie {
  deals!: Table<TreeoDeal, string>;
  people!: Table<TreeoDeal['profile'], string>;
  companies!: Table<CompanyRecord, string>;
  experiences!: Table<ExperienceRecord, string>;
  education!: Table<EducationRecord, string>;
  posts!: Table<PostRecord, string>;
  relationships!: Table<RelationshipRecord, string>;
  investorSignals!: Table<InvestorSignalRecord, string>;
  hnStories!: Table<HnStoryRecord, string>;
  hnComments!: Table<HnCommentRecord, string>;
  githubRepos!: Table<GithubRepoRecord, string>;
  productHuntLaunches!: Table<ProductHuntLaunchRecord, string>;
  ycSignals!: Table<YcSignalRecord, string>;
  claims!: Table<Claim, string>;
  evidence!: Table<Evidence, string>;
  analysisRuns!: Table<AnalysisRunRecord, string>;
  watchlist!: Table<WatchlistRecord, string>;
  alerts!: Table<AlertRecord, string>;
  settings!: Table<SettingRecord, string>;
  exports!: Table<ExportRecord, string>;

  constructor() {
    super('treeo_vc_scout_alpha');

    this.version(1).stores({
      deals: '&id, status, createdAt, updatedAt, score.total, score.recommendation, profile.name, profile.companyName',
      people: '&id, name, profileUrl, companyName, extractedAt',
      companies: '&id, name, domain, website, stageEstimate, updatedAt',
      experiences: '&id, personId, companyId, title',
      education: '&id, personId, institution',
      posts: '&id, authorPersonId, platform, date',
      relationships: '&id, sourceId, targetId, relationshipType',
      investorSignals: '&id, investorPersonId, investorFirmId, targetPersonId, targetCompanyId, signalType',
      hnStories: '&id, hnId, type, author, score, retrievedAt',
      hnComments: '&id, hnId, storyId, author, createdAt',
      githubRepos: '&id, owner, name, stars, lastCommitAt',
      productHuntLaunches: '&id, name, launchDate, relatedCompanyId',
      ycSignals: '&id, companyId, rfsTopic, fitScore',
      claims: '&id, subjectId, subjectType, claimType, status, confidence, createdAt',
      evidence: '&id, sourceType, sourceUrl, reliability, capturedAt',
      analysisRuns: '&id, personId, companyId, createdAt, modelProvider, promptHash',
      watchlist: '&id, personId, companyId, status, priority, nextCheckAt',
      alerts: '&id, watchlistId, alertType, severity, createdAt, readAt',
      settings: '&key, updatedAt',
      exports: '&id, profileId, format, createdAt',
    });

    this.version(2)
      .stores({
        deals: '&id, status, createdAt, updatedAt, score.total, score.recommendation, score.founderLikelihoodScore, profile.name, profile.companyName, [status+score.total], [profile.companyName+createdAt]',
        evidence: '&id, dealId, sourceType, sourceUrl, reliability, capturedAt, [dealId+fieldPath]',
        claims: '&id, dealId, subjectId, subjectType, claimType, status, confidence, createdAt, [dealId+subjectId]',
        analysisRuns: '&id, dealId, task, personId, companyId, createdAt, modelProvider, promptHash, [dealId+task]',
      })
      .upgrade(async (tx) => {
        // Stream-walk existing deals in chunks so the upgrade does not block
        // the sidepanel for users with thousands of stored deals.
        const dealsTable = tx.table<TreeoDeal>('deals');
        const evidenceTable = tx.table<Evidence>('evidence');
        const claimsTable = tx.table<Claim>('claims');
        const runsTable = tx.table<AnalysisRunRecord>('analysisRuns');

        const CHUNK = 200;
        let offset = 0;
        // Dexie does not expose offset() during upgrades, so accumulate the
        // primary keys into an array and walk it in chunks.
        const allDeals = await dealsTable.toArray();
        for (offset = 0; offset < allDeals.length; offset += CHUNK) {
          const chunk = allDeals.slice(offset, offset + CHUNK);
          for (const deal of chunk) {
            const dealId = deal.id;
            if (!deal.score.version) {
              deal.score.version = 'v1';
              await dealsTable.put(deal);
            }
            // Back-fill dealId on evidence rows we can recognize. Walk both
            // embedded (deal.evidence) and standalone tables.
            const embeddedEvidenceIds = (deal.evidence ?? []).map((item) => item.id);
            for (const evidenceId of embeddedEvidenceIds) {
              const existing = await evidenceTable.get(evidenceId);
              if (existing && !existing.dealId) {
                existing.dealId = dealId;
                await evidenceTable.put(existing);
              }
            }
            const embeddedClaimIds = (deal.claims ?? []).map((claim) => claim.id);
            for (const claimId of embeddedClaimIds) {
              const existing = await claimsTable.get(claimId);
              if (existing && !existing.dealId) {
                existing.dealId = dealId;
                await claimsTable.put(existing);
              }
            }
          }
          if (typeof globalThis !== 'undefined' && typeof chrome !== 'undefined' && chrome.runtime?.sendMessage) {
            chrome.runtime
              .sendMessage({
                type: 'TREEO_ERROR',
                payload: { message: `Dexie v2 upgrade ${Math.min(offset + CHUNK, allDeals.length)}/${allDeals.length}` },
              })
              .catch(() => undefined);
          }
        }

        // Back-fill `dealId` and `task` on analysisRuns by inspecting their
        // `warnings` tags, which the pipeline already stamps.
        const allRuns = await runsTable.toArray();
        for (const run of allRuns) {
          if (run.dealId && run.task) continue;
          const dealTag = run.warnings.find((tag) => tag.startsWith('dealId:'));
          const taskTag = run.warnings.find((tag) => tag.startsWith('task:'));
          if (dealTag) run.dealId = dealTag.slice('dealId:'.length);
          if (taskTag) run.task = taskTag.slice('task:'.length) as AnalysisRunRecord['task'];
          if (run.dealId || run.task) await runsTable.put(run);
        }
      });
  }
}

export const db = new TreeoDatabase();

export async function saveSettingValue<T>(key: string, value: T): Promise<void> {
  await db.settings.put({ key, value, updatedAt: new Date().toISOString() });
}

export async function getSettingValue<T>(key: string): Promise<T | undefined> {
  const record = await db.settings.get(key);
  return record?.value as T | undefined;
}

export type StoredSettings = TreeoSettings;
