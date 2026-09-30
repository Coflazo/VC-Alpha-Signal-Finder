import type { ExtractedProfile, SourceMetadata } from '../lib/types';
import { cleanText, nowIso } from '../lib/utils';

const LINKEDIN_COMPANY_RE = /https?:\/\/(?:www\.)?linkedin\.com\/company\/[^\s)"']+/i;
const LINK_RE = /https?:\/\/[^\s)"']+/gi;
const GITHUB_RE = /github\.com\/([A-Za-z0-9_.-]+)/gi;
const HN_USER_RE = /news\.ycombinator\.com\/user\?id=([A-Za-z0-9_-]+)/gi;
const PRODUCT_HUNT_RE = /producthunt\.com\/@([A-Za-z0-9_-]+)/gi;

function firstLine(lines: string[], fallback = ''): string {
  return lines.find((line) => line.trim().length > 1) ?? fallback;
}

function afterLabel(lines: string[], label: RegExp): string {
  const index = lines.findIndex((line) => label.test(line));
  if (index < 0) return '';
  return cleanText(lines.slice(index + 1, index + 5).join(' ')).slice(0, 1200);
}

function collectSection(lines: string[], label: RegExp, stop: RegExp, limit = 10): string[] {
  const start = lines.findIndex((line) => label.test(line));
  if (start < 0) return [];
  const out: string[] = [];
  for (const line of lines.slice(start + 1)) {
    if (stop.test(line)) break;
    if (line.length > 2) out.push(line);
    if (out.length >= limit) break;
  }
  return out;
}

function uniqueMatches(text: string, pattern: RegExp): string[] {
  const found = new Set<string>();
  for (const match of text.matchAll(pattern)) {
    if (match[1]) found.add(match[1]);
    else if (match[0]) found.add(match[0]);
  }
  return [...found];
}

function guessCompany(lines: string[], links: string[]): { name: string; url: string; website: string } {
  const companyLine =
    lines.find((line) => /\b(founder|co-founder|ceo|cto|building|owner)\b.+\bat\b/i.test(line)) ??
    lines.find((line) => /\bat\s+[A-Z][A-Za-z0-9 .&-]{2,}/.test(line)) ??
    '';
  const atMatch = companyLine.match(/\bat\s+(.{2,80})$/i);
  const companyName = cleanText(atMatch?.[1] ?? '');
  const linkedinCompany = links.find((href) => LINKEDIN_COMPANY_RE.test(href)) ?? '';
  const website = links.find((href) => !href.includes('linkedin.com') && !href.includes('github.com') && !href.includes('news.ycombinator.com')) ?? '';
  return { name: companyName, url: linkedinCompany, website };
}

export function normalizeRawProfile(rawInput: string, metadata: SourceMetadata, visibleLinks: string[] = []): ExtractedProfile {
  const rawText = cleanText(rawInput).slice(0, 40_000);
  const lines = rawText
    .split(/(?:\n| {2,}|\t)+/)
    .map(cleanText)
    .filter(Boolean)
    .slice(0, 500);
  const links = [...visibleLinks, ...(rawText.match(LINK_RE) ?? [])]
    .map((href) => href.replace(/[),.]+$/, ''))
    .filter((href, index, list) => list.indexOf(href) === index)
    .slice(0, 80);
  const company = guessCompany(lines, links);
  const name = firstLine(lines, metadata.sourceTitle?.replace(/\| LinkedIn.*$/i, '').split(' - ')[0] ?? '');
  const headline =
    lines.find((line) => /\b(founder|co-founder|ceo|cto|investor|builder|engineer|operator|student)\b/i.test(line) && line !== name) ??
    metadata.sourceTitle?.split(' - ').slice(1).join(' - ').replace(/\| LinkedIn.*$/i, '') ??
    '';
  const about = afterLabel(lines, /^about$/i) || lines.slice(0, 12).join(' ').slice(0, 1200);
  const experience = collectSection(lines, /^experience$/i, /^(education|activity|posts|skills|licenses|recommendations)$/i, 12);
  const education = collectSection(lines, /^education$/i, /^(experience|activity|posts|skills|licenses|recommendations)$/i, 8);
  const posts = collectSection(lines, /^(activity|posts)$/i, /^(experience|education|skills|licenses|recommendations)$/i, 10)
    .map((value) => value.slice(0, 700));
  const skills = collectSection(lines, /^skills$/i, /^(experience|education|activity|posts|licenses|recommendations)$/i, 20);

  return {
    name,
    headline,
    location: lines.find((line) => /\b(Netherlands|Amsterdam|Istanbul|Turkey|United States|London|Berlin|Paris|San Francisco|New York)\b/i.test(line)) ?? '',
    about,
    profileUrl: metadata.sourceUrl ?? '',
    profileImageUrl: '',
    companyName: company.name,
    companyUrl: company.url,
    companyWebsite: company.website,
    rawText,
    currentRoles: experience.slice(0, 3),
    pastRoles: experience.slice(3),
    experience,
    education,
    skills,
    languages: [],
    posts,
    visibleLinks: links,
    hnUsernames: uniqueMatches(rawText, HN_USER_RE),
    githubUsernames: uniqueMatches(rawText, GITHUB_RE),
    productHuntUsernames: uniqueMatches(rawText, PRODUCT_HUNT_RE),
    sourceMetadata: metadata,
    extractedAt: metadata.capturedAt || nowIso(),
  };
}
