import type { ExtractedProfile, SourceMetadata } from '../lib/types';
import { cleanText, nowIso } from '../lib/utils';

/**
 * The visible-text capture on a LinkedIn profile arrives as a single,
 * undelimited blob: the profile content interleaved with nav chrome,
 * connection-degree chips, "Show all" buttons, footer, ads, language picker,
 * "More profiles for you", and so on. The generic adapter cannot parse that
 * — it assumes line-delimited input. This module exists to:
 *
 *   1) Truncate the dump at the first known noise marker.
 *   2) Inject break-points before/after known LinkedIn section labels so the
 *      resulting text can be line-split.
 *   3) Pull name, headline, location, about, experience, education from the
 *      cleaned sections instead of guessing across the whole page.
 *
 * Everything below `Activity` / `Experience` / `Education` is treated as
 * structured content; everything from `Ad Options` / `More profiles for you`
 * / `Pages for you` / `LinkedIn Corporation` onward is discarded.
 */

const NOISE_TRUNCATIONS: RegExp[] = [
  /Ad Options/i,
  /More profiles for you/i,
  /People you may know/i,
  /You might like/i,
  /Pages for you/i,
  /About\s+Accessibility\s+Talent/i,
  /Recommendation transparency/i,
  /Select language/i,
  /LinkedIn Corporation/i,
  /Manage your account and privacy/i,
];

const SECTION_LABELS = [
  'About',
  'Activity',
  'Posts',
  'Comments',
  'Featured',
  'Highlights',
  'Experience',
  'Education',
  'Licenses & certifications',
  'Honors & awards',
  'Honors and awards',
  'Skills',
  'Languages',
  'Interests',
  'Top Voices',
  'Companies',
  'Schools',
  'Causes',
  'Contact info',
  'Volunteering',
  'Publications',
  'Projects',
  'Recommendations',
];

const NOISE_PHRASES: RegExp[] = [
  /Show all\b[^\n]*/g,
  /\b\d+(?:,\d{3})*\+? connections\b/g,
  /\b\d+(?:,\d{3})* followers\b/g,
  /\bMutual connections?\b[^\n]*/g,
  /\bSend (InMail|profile)\b[^\n]*/g,
  /\bMore actions?\b[^\n]*/g,
  /·\s*(Self-employed|Full-time|Part-time|Contract|Internship|Freelance)/g,
  /^\s*(Message|Connect|Follow|Following)\s*$/gim,
];

const HEADLINE_NOISE = /(·\s*1st|·\s*2nd|·\s*3rd|·\s*Contact info)/g;

const LINK_RE = /https?:\/\/[^\s)"']+/gi;
const GITHUB_RE = /github\.com\/([A-Za-z0-9_.-]+)/gi;
const HN_USER_RE = /news\.ycombinator\.com\/user\?id=([A-Za-z0-9_-]+)/gi;
const PRODUCT_HUNT_RE = /producthunt\.com\/@([A-Za-z0-9_-]+)/gi;

function truncateAtNoise(text: string): string {
  let cut = text.length;
  for (const pattern of NOISE_TRUNCATIONS) {
    const match = pattern.exec(text);
    if (match && match.index < cut) cut = match.index;
  }
  return text.slice(0, cut);
}

/**
 * Insert a newline before each known section label so that the resulting
 * text is parseable as line-delimited sections. We use a lookbehind so we
 * only break when the label appears mid-stream, not at the very start.
 */
function injectSectionBreaks(text: string): string {
  let out = text;
  for (const label of SECTION_LABELS) {
    const escaped = label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    // Section labels are followed by either uppercase (new heading) or a space.
    out = out.replace(new RegExp(`(\\S)${escaped}(?=[A-Z]|\\s)`, 'g'), `$1\n${label}\n`);
  }
  return out;
}

function stripNoisePhrases(text: string): string {
  let out = text;
  for (const pattern of NOISE_PHRASES) out = out.replace(pattern, ' ');
  return out;
}

/**
 * Split a "Sarp Türker· 1st· 2ndCofounder of Merlon | Junior at U of C" into
 * `{ name, headline }`. The first chunk before the connection-degree chips
 * is the name; the rest, stripped of chrome, is the headline.
 */
function parseNameAndHeadline(firstChunk: string): { name: string; headline: string } {
  const cleaned = firstChunk.replace(/^\s+|\s+$/g, '');
  const splitOnDegree = cleaned.split(/·\s*(?:1st|2nd|3rd)/);
  const name = cleanText(splitOnDegree[0] ?? '');
  const tail = splitOnDegree.slice(1).join(' ').replace(HEADLINE_NOISE, ' ');
  // Collapse repeated "·" separators, trim location/contact suffix.
  const headline = cleanText(tail)
    .replace(/\bContact info\b/i, '')
    .replace(/\s{2,}/g, ' ')
    .trim();
  return { name, headline };
}

interface Sections {
  about: string;
  experience: string[];
  education: string[];
  skills: string[];
  posts: string[];
  honors: string[];
  languages: string[];
  location: string;
}

const KNOWN_SECTION = /^(About|Activity|Posts|Featured|Highlights|Experience|Education|Honors & awards|Honors and awards|Skills|Languages|Interests|Top Voices|Companies|Schools|Causes|Volunteering|Publications|Projects|Recommendations|Contact info|Licenses & certifications)$/i;

function takeUntilNextSection(lines: string[], startIndex: number): { value: string[]; nextIndex: number } {
  const out: string[] = [];
  let i = startIndex;
  for (; i < lines.length; i += 1) {
    if (KNOWN_SECTION.test(lines[i])) break;
    if (lines[i].trim().length > 1) out.push(lines[i]);
  }
  return { value: out, nextIndex: i };
}

function partitionSections(lines: string[]): Sections {
  const sections: Sections = {
    about: '',
    experience: [],
    education: [],
    skills: [],
    posts: [],
    honors: [],
    languages: [],
    location: '',
  };

  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i].trim();
    if (/^about$/i.test(line)) {
      const { value, nextIndex } = takeUntilNextSection(lines, i + 1);
      sections.about = cleanText(value.join(' ')).slice(0, 1500);
      i = nextIndex - 1;
    } else if (/^(activity|posts)$/i.test(line)) {
      const { value, nextIndex } = takeUntilNextSection(lines, i + 1);
      sections.posts = value.filter((entry) => entry.length > 12).slice(0, 8).map((entry) => entry.slice(0, 600));
      i = nextIndex - 1;
    } else if (/^experience$/i.test(line)) {
      const { value, nextIndex } = takeUntilNextSection(lines, i + 1);
      sections.experience = value.filter((entry) => entry.length > 4).slice(0, 12);
      i = nextIndex - 1;
    } else if (/^education$/i.test(line)) {
      const { value, nextIndex } = takeUntilNextSection(lines, i + 1);
      sections.education = value.filter((entry) => entry.length > 4).slice(0, 8);
      i = nextIndex - 1;
    } else if (/^skills$/i.test(line)) {
      const { value, nextIndex } = takeUntilNextSection(lines, i + 1);
      sections.skills = value.filter((entry) => entry.length > 1).slice(0, 24);
      i = nextIndex - 1;
    } else if (/^(honors\s*&\s*awards|honors and awards)$/i.test(line)) {
      const { value, nextIndex } = takeUntilNextSection(lines, i + 1);
      sections.honors = value.filter((entry) => entry.length > 4).slice(0, 8);
      i = nextIndex - 1;
    } else if (/^languages$/i.test(line)) {
      const { value, nextIndex } = takeUntilNextSection(lines, i + 1);
      sections.languages = value
        .filter((entry) => entry.length > 1 && !/proficiency/i.test(entry))
        .slice(0, 8);
      i = nextIndex - 1;
    }
  }

  return sections;
}

function locationFromHeaderBlock(headerLines: string[]): string {
  // LinkedIn renders the location as a line like "Istanbul, Istanbul, Türkiye·Contact info"
  // shortly after the headline. Match any line with at least one comma and a known
  // country-or-region word, then strip the trailing "·Contact info" tail.
  const locationLine = headerLines.find((line) => /,\s*[A-Za-zÀ-ɏ]/.test(line) && !/(Cofounder|founder|engineer|student|building|cto|ceo)/i.test(line));
  if (!locationLine) return '';
  return cleanText(locationLine.replace(/·\s*Contact info.*$/i, '').replace(/^[·\s]+/, ''));
}

function guessCurrentCompanyFromHeadline(headline: string): string {
  // "Cofounder of Merlon | Junior at University of Chicago" → "Merlon"
  const ofMatch = headline.match(/(?:cofounder|co-founder|founder|ceo|cto|building)\s+(?:of|at)\s+([A-Za-z0-9 .&'-]{2,60})/i);
  if (ofMatch) return cleanText(ofMatch[1]).replace(/\s*[|·].*$/, '');
  const atMatch = headline.match(/\b(?:at|@)\s+([A-Z][A-Za-z0-9 .&'-]{2,60})/);
  if (atMatch) return cleanText(atMatch[1]).replace(/\s*[|·].*$/, '');
  return '';
}

function uniqueMatches(text: string, pattern: RegExp): string[] {
  const found = new Set<string>();
  for (const match of text.matchAll(pattern)) {
    if (match[1]) found.add(match[1]);
    else if (match[0]) found.add(match[0]);
  }
  return [...found];
}

/**
 * Public entry point. Take the raw LinkedIn page text and turn it into an
 * `ExtractedProfile` with no chrome, no nav, no "More profiles for you".
 */
export function extractLinkedInProfile(
  rawInput: string,
  metadata: SourceMetadata,
  visibleLinks: string[] = [],
): ExtractedProfile {
  const truncated = truncateAtNoise(rawInput);
  const broken = injectSectionBreaks(truncated);
  const denoised = stripNoisePhrases(broken).slice(0, 60_000);

  const lines = denoised
    .split(/\n+/)
    .map(cleanText)
    .filter((line) => line.length > 0);

  // The first non-section line is the header block: "Sarp Türker· 1st· 2nd…"
  const headerStart = lines.findIndex((line) => !KNOWN_SECTION.test(line));
  const headerLines: string[] = [];
  for (let i = headerStart; i < lines.length; i += 1) {
    if (KNOWN_SECTION.test(lines[i])) break;
    headerLines.push(lines[i]);
    if (headerLines.length >= 6) break;
  }

  const { name, headline } = parseNameAndHeadline(headerLines[0] ?? metadata.sourceTitle ?? '');
  const location = locationFromHeaderBlock(headerLines.slice(1));
  const sections = partitionSections(lines);

  const companyFromHeadline = guessCurrentCompanyFromHeadline(headline);
  const companyFromExperience = sections.experience.find((entry) => /\bat\b|\b·\b/.test(entry)) ?? '';
  const companyName = companyFromHeadline
    || cleanText(companyFromExperience.split(/\bat\b|·/i)[1] ?? '').split(/\s*[|·]/)[0]
    || '';

  const rawText = truncated.slice(0, 8_000);

  const allLinks = [...visibleLinks, ...(rawInput.match(LINK_RE) ?? [])]
    .map((href) => href.replace(/[),.]+$/, ''))
    .filter((href, index, list) => list.indexOf(href) === index)
    .slice(0, 60);

  const companyWebsite = allLinks.find((href) => !href.includes('linkedin.com') && !href.includes('github.com') && !href.includes('news.ycombinator.com')) ?? '';
  const companyUrl = allLinks.find((href) => /linkedin\.com\/company\//i.test(href)) ?? '';

  return {
    name,
    headline,
    location,
    about: sections.about,
    profileUrl: metadata.sourceUrl ?? '',
    profileImageUrl: '',
    companyName,
    companyUrl,
    companyWebsite,
    rawText,
    currentRoles: sections.experience.slice(0, 2),
    pastRoles: sections.experience.slice(2),
    experience: sections.experience,
    education: sections.education,
    skills: sections.skills,
    languages: sections.languages,
    posts: sections.posts,
    visibleLinks: allLinks,
    hnUsernames: uniqueMatches(denoised, HN_USER_RE),
    githubUsernames: uniqueMatches(denoised, GITHUB_RE),
    productHuntUsernames: uniqueMatches(denoised, PRODUCT_HUNT_RE),
    sourceMetadata: { ...metadata, sourceType: 'linkedin_visible_page', isLinkedInLike: true },
    extractedAt: metadata.capturedAt || nowIso(),
  };
}
