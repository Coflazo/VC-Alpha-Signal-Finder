import type { ExtractedProfile } from '../../lib/types';

/**
 * A student exploring without product, company, or builder proof.
 * Should land in `pass` / `monitor` with a low founderLikelihoodScore and
 * a high "student" risk signal.
 */
export const studentSignal: ExtractedProfile = {
  id: 'person_student',
  name: 'Student Curious',
  headline: 'CS student at Bilkent, exploring AI ideas',
  location: 'Ankara, Turkey',
  about: 'Studying machine learning. Interested in startups. Aspiring to build something one day.',
  profileUrl: 'https://www.linkedin.com/in/student-curious',
  profileImageUrl: '',
  companyName: '',
  companyUrl: '',
  companyWebsite: '',
  rawText: 'student CS Bilkent machine learning aspiring',
  currentRoles: ['Student at Bilkent University'],
  pastRoles: [],
  experience: ['Student at Bilkent University'],
  education: ['BSc Computer Science, Bilkent'],
  skills: ['Python'],
  languages: ['English', 'Turkish'],
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
