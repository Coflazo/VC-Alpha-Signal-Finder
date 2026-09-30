export interface GithubRepoApi {
  id: number;
  name: string;
  full_name: string;
  html_url: string;
  stargazers_count: number;
  forks_count: number;
  open_issues_count: number;
  language: string | null;
  pushed_at: string | null;
  owner: { login: string; type?: 'User' | 'Organization' };
  topics?: string[];
}

function authHeaders(token = ''): Record<string, string> {
  const base: Record<string, string> = {
    Accept: 'application/vnd.github+json',
    'X-GitHub-Api-Version': '2022-11-28',
  };
  if (token) base.Authorization = `Bearer ${token}`;
  return base;
}

export async function searchGithubRepos(query: string, limit = 8, token = ''): Promise<GithubRepoApi[]> {
  if (!query.trim()) return [];
  const url = new URL('https://api.github.com/search/repositories');
  url.searchParams.set('q', `${query} in:name,description,readme`);
  url.searchParams.set('sort', 'updated');
  url.searchParams.set('order', 'desc');
  url.searchParams.set('per_page', String(Math.min(20, limit)));
  const response = await fetch(url.toString(), { headers: authHeaders(token) });
  if (!response.ok) return [];
  const json = await response.json();
  return Array.isArray(json?.items) ? json.items : [];
}

export async function fetchGithubReadme(owner: string, repo: string, token = ''): Promise<string> {
  const response = await fetch(`https://api.github.com/repos/${owner}/${repo}/readme`, {
    headers: { ...authHeaders(token), Accept: 'application/vnd.github.raw' },
  });
  if (!response.ok) return '';
  return response.text();
}

export async function fetchGithubContents(owner: string, repo: string, token = ''): Promise<Array<{ name: string; type: string; path: string }>> {
  const response = await fetch(`https://api.github.com/repos/${owner}/${repo}/contents`, { headers: authHeaders(token) });
  if (!response.ok) return [];
  const json = await response.json();
  return Array.isArray(json) ? json : [];
}

export async function fetchGithubTree(owner: string, repo: string, token = ''): Promise<string[]> {
  const response = await fetch(`https://api.github.com/repos/${owner}/${repo}/git/trees/HEAD?recursive=1`, { headers: authHeaders(token) });
  if (!response.ok) return [];
  const json = await response.json();
  const tree = Array.isArray(json?.tree) ? json.tree : [];
  return tree.map((entry: { path?: string }) => entry.path ?? '').filter(Boolean);
}
