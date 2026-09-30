import type { GithubRepoRecord } from '../../lib/types';
import { makeId } from '../../lib/utils';
import { fetchGithubContents, fetchGithubReadme, fetchGithubTree, searchGithubRepos, type GithubRepoApi } from './githubApiClient';

/**
 * README quality is a weighted blend of length, structure (headings, code
 * blocks), and signal keywords. Replaces the bare char-count + 3-keyword
 * heuristic. Output is clamped to [0,100].
 */
export function readmeQuality(readme: string): number {
  if (!readme) return 0;
  const corpus = readme.toLowerCase();
  const headingCount = (readme.match(/^#+\s/gm) ?? []).length;
  const codeBlockCount = (readme.match(/```/g) ?? []).length / 2;
  const linkCount = (readme.match(/\[[^\]]+\]\([^)]+\)/g) ?? []).length;
  const hasExamples = /example|usage|quickstart|getting started/.test(corpus) ? 1 : 0;
  const hasInstall = /install|setup|requirements|prerequisites/.test(corpus) ? 1 : 0;
  const hasLicense = /license|mit|apache/.test(corpus) ? 1 : 0;
  const hasContrib = /contribut|pull request|issue tracker/.test(corpus) ? 1 : 0;
  const lengthScore = Math.min(35, readme.length / 80);
  return Math.round(Math.min(100,
    lengthScore
    + Math.min(15, headingCount * 2)
    + Math.min(15, codeBlockCount * 4)
    + Math.min(10, linkCount * 1.5)
    + hasExamples * 9
    + hasInstall * 7
    + hasLicense * 4
    + hasContrib * 5,
  ));
}

function hasPath(paths: string[], pattern: RegExp): boolean {
  return paths.some((p) => pattern.test(p));
}

function commitRecencyMultiplier(pushedAt: string | null): number {
  if (!pushedAt) return 0.4;
  const ageDays = (Date.now() - Date.parse(pushedAt)) / 86_400_000;
  if (Number.isNaN(ageDays)) return 0.4;
  // Active <30d → 1.0, 6-month-old → 0.7, year-old → 0.4, year+ → 0.2 floor.
  if (ageDays < 30) return 1.0;
  if (ageDays < 180) return 0.85;
  if (ageDays < 365) return 0.6;
  return 0.3;
}

async function repoToRecord(repo: GithubRepoApi, token: string): Promise<GithubRepoRecord> {
  const [readme, contents, tree] = await Promise.all([
    fetchGithubReadme(repo.owner.login, repo.name, token),
    fetchGithubContents(repo.owner.login, repo.name, token),
    // Tree call is only worth it when authenticated (it's expensive on unauthenticated quota).
    token ? fetchGithubTree(repo.owner.login, repo.name, token) : Promise.resolve<string[]>([]),
  ]);
  const allPaths = [
    ...contents.map((item) => item.path),
    ...tree,
  ];
  const recency = commitRecencyMultiplier(repo.pushed_at);
  const baseQuality = readmeQuality(readme);
  const ciDetected = hasPath(allPaths, /\.github\/workflows|\.gitlab-ci|\.circleci|\.travis|\.azure-pipelines/);
  return {
    id: makeId('gh_repo'),
    owner: repo.owner.login,
    name: repo.name,
    url: repo.html_url,
    stars: repo.stargazers_count,
    forks: repo.forks_count,
    openIssues: repo.open_issues_count,
    language: repo.language ?? 'unknown',
    lastCommitAt: repo.pushed_at ?? '',
    readmeQuality: Math.round(baseQuality * recency + (ciDetected ? 6 : 0)),
    testDetected: hasPath(allPaths, /(^|\/)(test|tests|spec|specs|__tests__|vitest|pytest|jest)([./]|$)/i),
    docsDetected: hasPath(allPaths, /(^|\/)(docs?|examples?|guides?)([./]|$)/i),
    releaseCount: 0,
    evidenceIds: [],
  };
}

export async function analyzeGithubRepos(query: string, token = ''): Promise<GithubRepoRecord[]> {
  const repos = await searchGithubRepos(query, 6, token);
  return Promise.all(repos.map((repo) => repoToRecord(repo, token)));
}
