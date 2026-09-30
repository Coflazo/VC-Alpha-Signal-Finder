/**
 * Brand metadata. Color tokens live in `src/styles/globals.css` (CSS vars) —
 * importing this file no longer pulls a duplicate palette into the codebase.
 */
export const TREEO_BRAND = {
  name: 'Treeo VC Scout',
  shortName: 'Treeo Scout',
  thesis: 'Early-stage AI-native B2B startups led by Turkish and immigrant founders entering the U.S. market.',
  principles: ['Collaborative Edge', 'Structural Demand', 'Mutual Value'] as const,
};

export const DEFAULT_FOCUS_MARKETS = [
  'AI-native B2B',
  'U.S. market entry',
  'Turkish founders',
  'immigrant founders',
  'vertical SaaS',
  'data infrastructure',
  'agentic workflows',
];
