import type { ExtractedProfile } from '../lib/types';
import { nowIso } from '../lib/utils';
import { extractLinkedInProfile } from './linkedinExtractor';
import { normalizeRawProfile } from './genericProfileAdapter';

/**
 * A pasted LinkedIn profile arrives as one big undelimited blob: name +
 * connection chips + "Highlights" + "About" + "Activity" + nav + footer +
 * "More profiles for you" + language picker. Detect that and run the
 * LinkedIn-aware extractor; everything else falls through to the generic
 * normalizer.
 */
function looksLikeLinkedInPaste(text: string): boolean {
  const head = text.slice(0, 8000);
  // Any one of these is a near-certain LinkedIn signal. Keep the check
  // permissive — the LinkedIn extractor handles non-LinkedIn text gracefully,
  // but the generic extractor cannot handle the undelimited LinkedIn blob.
  return (
    /linkedin\.com/i.test(text)
    || /·\s*(?:1st|2nd|3rd)/i.test(head)
    || /mutual connections?/i.test(head)
    || /contact info/i.test(head)
    || (/connections?/i.test(head) && /\bmessage\b/i.test(head) && /\bhighlights?\b/i.test(head))
  );
}

export function profileFromManualPaste(text: string, sourceTitle = 'Manual paste'): ExtractedProfile {
  const isLinkedIn = looksLikeLinkedInPaste(text);
  const metadata = {
    captureMode: 'manual_paste' as const,
    sourceTitle,
    sourceType: isLinkedIn ? 'linkedin_manual_paste' : 'manual_paste',
    capturedAt: nowIso(),
    isLinkedInLike: isLinkedIn,
  };
  if (isLinkedIn) return extractLinkedInProfile(text, metadata);
  return normalizeRawProfile(text, metadata);
}
