import type { ExtractedProfile } from '../../lib/types';

/**
 * A noisy paste that contains the substring "founder" and "AI" without
 * actually identifying a founder. Tests that the scorer doesn't run the score
 * up on shallow keyword presence alone — confidence should be low and the
 * recommendation should not exceed `monitor`.
 */
export const noisyLinkedInDump: ExtractedProfile = { // gitleaks:allow (variable name, not a secret)
  id: 'person_noisy',
  name: 'Generic Operator',
  headline: 'AI enthusiast | follower of founders | excited about the future',
  location: '',
  about: 'I love reading about founders. AI is exciting. I follow many YC accounts and read launches every day. Idea: maybe one day I will build something. Exploring.',
  profileUrl: 'https://www.linkedin.com/in/generic-op',
  profileImageUrl: '',
  companyName: '',
  companyUrl: '',
  companyWebsite: '',
  rawText: 'founder ai launches yc exploring idea',
  currentRoles: [],
  pastRoles: [],
  experience: [],
  education: [],
  skills: ['Reading', 'Writing'],
  languages: ['English'],
  posts: ['Just read another great post about founders.'],
  interactions: [],
  visibleLinks: ['https://www.linkedin.com/in/generic-op'],
  hnUsernames: [],
  githubUsernames: [],
  productHuntUsernames: [],
  sourceMetadata: {
    captureMode: 'manual_paste',
    sourceUrl: 'fixture',
    sourceTitle: 'Fixture',
    sourceType: 'fixture',
    capturedAt: '2026-06-19T00:00:00.000Z',
    isLinkedInLike: true,
  },
  extractedAt: '2026-06-19T00:00:00.000Z',
};
