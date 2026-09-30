import type {
  ExtractedProfile,
  GithubRepoRecord,
  HnCommentRecord,
  HnStoryRecord,
  ProductHuntLaunchRecord,
  TreeoSettings,
  YcSignalRecord,
} from '../lib/types';
import { hashString } from '../lib/utils';
import { analyzeGithubRepos } from './github/repoQualityAnalyzer';
import { mineHnSignals } from './hn/hnTrendMiner';
import { searchProductHuntLaunches } from './producthunt/productHuntClient';
import { generateResearchQueries } from './queryGenerator';
import { analyzeYcFit } from './yc/ycFitAnalysis';

export interface OrchestratedResearch {
  hnStories: HnStoryRecord[];
  hnComments: HnCommentRecord[];
  githubRepos: GithubRepoRecord[];
  ycSignals: YcSignalRecord[];
  productHuntLaunches: ProductHuntLaunchRecord[];
  queries: string[];
  warnings: string[];
}

interface Task<T> {
  /** Stable id used by the source-level dedup map. */
  id: string;
  /** Friendly label for warnings. */
  source: string;
  /** The actual fetch. */
  fn: () => Promise<T>;
}

const MAX_CONCURRENCY = 2;
const MAX_ATTEMPTS = 3;

interface MemoEntry {
  fetchedAt: number;
  payload: unknown;
}
const memo = new Map<string, MemoEntry>();
const inflight = new Map<string, Promise<unknown>>();
const MEMO_TTL_MS = 10 * 60 * 1000;

function jitter(baseMs: number, attempt: number): number {
  const ceil = Math.min(8_000, baseMs * Math.pow(2, attempt));
  return Math.round(ceil * (0.5 + Math.random() * 0.5));
}

async function runWithRetry<T>(task: Task<T>, warnings: string[]): Promise<T | null> {
  for (let attempt = 0; attempt < MAX_ATTEMPTS; attempt += 1) {
    try {
      return await task.fn();
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      warnings.push(`${task.source}_attempt_${attempt + 1}_failed: ${message}`);
      if (attempt === MAX_ATTEMPTS - 1) return null;
      await new Promise<void>((resolve) => setTimeout(resolve, jitter(400, attempt)));
    }
  }
  return null;
}

/**
 * Source-level dedup. If the same `(source, queryHash)` is already running or
 * cached, return its result instead of issuing a fresh request. The MV3
 * service worker can sleep mid-task; this keeps the cache warm across short
 * sleeps without persisting partials to disk yet.
 */
async function memoize<T>(task: Task<T>, warnings: string[]): Promise<T | null> {
  const hit = memo.get(task.id);
  if (hit && Date.now() - hit.fetchedAt < MEMO_TTL_MS) return hit.payload as T;
  const existing = inflight.get(task.id);
  if (existing) return existing as Promise<T | null>;
  const promise = runWithRetry(task, warnings).then((result) => {
    if (result !== null) memo.set(task.id, { fetchedAt: Date.now(), payload: result });
    inflight.delete(task.id);
    return result;
  });
  inflight.set(task.id, promise as Promise<unknown>);
  return promise as Promise<T | null>;
}

/**
 * Bounded queue. Runs up to MAX_CONCURRENCY tasks at a time. Useful when the
 * analyst clicks Analyze on a watchlist and we fan out many founders at once.
 */
async function runBounded<T>(tasks: Array<Task<T>>, warnings: string[]): Promise<Array<T | null>> {
  const results: Array<T | null> = new Array(tasks.length).fill(null);
  let cursor = 0;
  async function worker(): Promise<void> {
    while (true) {
      const index = cursor;
      cursor += 1;
      if (index >= tasks.length) return;
      results[index] = await memoize(tasks[index], warnings);
    }
  }
  const workers = Array.from({ length: Math.min(MAX_CONCURRENCY, tasks.length) }, () => worker());
  await Promise.all(workers);
  return results;
}

/**
 * Run all public research for one profile. Concurrency-bounded, retried,
 * deduped per source+query. Replaces the unbounded `Promise.all` queue.
 */
export async function runResearch(profile: ExtractedProfile, settings: TreeoSettings): Promise<OrchestratedResearch> {
  const queries = generateResearchQueries(profile);
  if (!settings.publicResearchEnabled) {
    return {
      hnStories: [],
      hnComments: [],
      githubRepos: [],
      ycSignals: await analyzeYcFit(profile),
      productHuntLaunches: [],
      queries,
      warnings: ['public_web_research_disabled'],
    };
  }

  const warnings: string[] = [];
  const mainQuery = profile.companyName || profile.name || profile.headline;
  const queryHash = hashString(mainQuery.toLowerCase());

  const tasks: Task<unknown>[] = [
    { id: `hn:${queryHash}`, source: 'hn', fn: () => mineHnSignals(mainQuery) },
    { id: `github:${queryHash}`, source: 'github', fn: () => analyzeGithubRepos(mainQuery, settings.githubToken) },
    { id: `yc:${profile.id ?? queryHash}`, source: 'yc', fn: () => analyzeYcFit(profile) },
  ];

  if (settings.producthuntToken) {
    tasks.push({
      id: `producthunt:${queryHash}`,
      source: 'producthunt',
      fn: () => searchProductHuntLaunches(mainQuery, settings.producthuntToken),
    });
  }

  const [hn, githubRepos, ycSignals, producthunt] = await runBounded(tasks, warnings);

  const hnPayload = (hn as { stories: HnStoryRecord[]; comments: HnCommentRecord[] } | null) ?? { stories: [], comments: [] };

  return {
    hnStories: hnPayload.stories,
    hnComments: hnPayload.comments,
    githubRepos: (githubRepos as GithubRepoRecord[] | null) ?? [],
    ycSignals: (ycSignals as YcSignalRecord[] | null) ?? [],
    productHuntLaunches: (producthunt as ProductHuntLaunchRecord[] | null) ?? [],
    queries,
    warnings,
  };
}
