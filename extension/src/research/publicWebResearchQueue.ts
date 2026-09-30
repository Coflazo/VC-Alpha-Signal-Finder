/**
 * Thin compatibility shim. The real implementation moved to
 * `researchOrchestrator.ts` (bounded queue, retry, dedup, persistence).
 * Keep this file so any external imports of `runPublicResearch` keep working.
 */
import type { ExtractedProfile, GithubRepoRecord, HnCommentRecord, HnStoryRecord, ProductHuntLaunchRecord, TreeoSettings, YcSignalRecord } from '../lib/types';
import { runResearch } from './researchOrchestrator';

export interface PublicResearchResult {
  hnStories: HnStoryRecord[];
  hnComments: HnCommentRecord[];
  githubRepos: GithubRepoRecord[];
  ycSignals: YcSignalRecord[];
  productHuntLaunches: ProductHuntLaunchRecord[];
  queries: string[];
  warnings: string[];
}

export async function runPublicResearch(profile: ExtractedProfile, settingsOrEnabled: TreeoSettings | boolean): Promise<PublicResearchResult> {
  if (typeof settingsOrEnabled === 'boolean') {
    // Legacy call site: only `enabled` was passed. Synthesize a minimal settings shape.
    const synthetic = {
      publicResearchEnabled: settingsOrEnabled,
      githubToken: '',
      producthuntToken: '',
    } as unknown as TreeoSettings;
    return runResearch(profile, synthetic);
  }
  return runResearch(profile, settingsOrEnabled);
}
