import type { ExtractedProfile } from '../../lib/types';

/**
 * A founder of a Series A company with deep public proof. Should produce a
 * high total + high confidence, but the recommendation tier may downgrade to
 * `partner_review` because a Series A founder is typically out of scope for a
 * pre-seed thesis. The point is that the math is honest about strength.
 */
export const seriesAFounder: ExtractedProfile = {
  id: 'person_series_a',
  name: 'Series A Founder',
  headline: 'Founder and CEO at FlowEnterprise (Series A)',
  location: 'San Francisco, United States',
  about: 'Founder and CEO of FlowEnterprise, the AI workflow platform for enterprise finance teams. Series A led by Sequoia. Recently launched our enterprise-tier compliance and procurement product. Hiring across go-to-market and engineering.',
  profileUrl: 'https://www.linkedin.com/in/series-a-founder',
  profileImageUrl: '',
  companyName: 'FlowEnterprise',
  companyUrl: 'https://www.linkedin.com/company/flowenterprise',
  companyWebsite: 'https://flowenterprise.ai',
  rawText: 'Founder CEO FlowEnterprise Series A Sequoia enterprise AI workflow finance compliance procurement hiring github launched product launch demo customer revenue investor',
  currentRoles: ['Founder and CEO at FlowEnterprise'],
  pastRoles: ['Senior PM at Stripe', 'Engineer at Google'],
  experience: ['Founder and CEO at FlowEnterprise', 'Senior PM at Stripe', 'Software engineer at Google'],
  education: ['BS Computer Science, Stanford', 'MBA, Stanford GSB'],
  skills: ['Enterprise sales', 'AI agents', 'Workflow design', 'Compliance'],
  languages: ['English'],
  posts: [
    'We just closed our Series A led by Sequoia. We are hiring across GTM and engineering.',
    'Launched our enterprise compliance workspace today. Customer pilots showed 60 percent time saved.',
  ],
  interactions: [],
  visibleLinks: ['https://flowenterprise.ai', 'https://github.com/flowenterprise/agent-sdk'],
  hnUsernames: ['flowfounder'],
  githubUsernames: ['flowenterprise'],
  productHuntUsernames: ['flowenterprise'],
  sourceMetadata: {
    captureMode: 'manual_paste',
    sourceUrl: 'fixture',
    sourceTitle: 'Fixture',
    sourceType: 'fixture',
    capturedAt: '2026-06-19T00:00:00.000Z',
    isLinkedInLike: false,
  },
  extractedAt: '2026-06-19T00:00:00.000Z',
};
