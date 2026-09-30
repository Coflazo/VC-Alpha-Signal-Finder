import type { ExtractedProfile, SourceMetadata } from '../lib/types';
import { extractLinkedInProfile } from './linkedinExtractor';

const BLOCKLIST = [
  /linkedin\.com\/sales\b/i,
  /linkedin\.com\/recruiter\b/i,
  /linkedin\.com\/talent\b/i,
  /linkedin\.com\/learning\b/i,
];

export class LinkedInCaptureRefusedError extends Error {
  constructor(public reason: string) {
    super(`LinkedIn capture refused: ${reason}`);
    this.name = 'LinkedInCaptureRefusedError';
  }
}

export function isLinkedInBlockedUrl(url: string): boolean {
  return BLOCKLIST.some((pattern) => pattern.test(url));
}

/**
 * Visible-text LinkedIn capture. Refuses on the URL blocklist (Sales
 * Navigator, Recruiter, Talent, Learning) and delegates to a LinkedIn-aware
 * extractor that strips nav chrome, ads, and "More profiles for you" before
 * the text reaches the LLM or the UI.
 */
export function profileFromLinkedInVisibleText(
  rawText: string,
  metadata: SourceMetadata,
  links: string[],
): ExtractedProfile {
  if (metadata.sourceUrl && isLinkedInBlockedUrl(metadata.sourceUrl)) {
    throw new LinkedInCaptureRefusedError(
      'This page is on the LinkedIn blocklist (Sales Navigator, Recruiter, Talent, or Learning). Use manual paste or an approved API adapter instead.',
    );
  }
  return extractLinkedInProfile(rawText, metadata, links);
}
