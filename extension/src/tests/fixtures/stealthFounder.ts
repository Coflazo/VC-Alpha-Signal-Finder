import type { ExtractedProfile } from '../../lib/types';

/**
 * A profile that asserts founder status but offers no public proof.
 * Should land low on `take_meeting` / high on risk: vague stealth wording,
 * no company website, no GitHub, no HN, weak experience.
 */
export const stealthFounder: ExtractedProfile = {
  id: 'person_stealth',
  name: 'Stealth Operator',
  headline: 'Stealth founder · exploring something in AI',
  location: 'Somewhere',
  about: 'Stealth founder building something new. Coming soon.',
  profileUrl: 'https://www.linkedin.com/in/stealth-op',
  profileImageUrl: '',
  companyName: '',
  companyUrl: '',
  companyWebsite: '',
  rawText: 'stealth founder exploring AI',
  currentRoles: ['Stealth founder'],
  pastRoles: [],
  experience: [],
  education: [],
  skills: [],
  languages: ['English'],
  posts: [],
  interactions: [],
  visibleLinks: [],
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
