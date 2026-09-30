import { describe, expect, it } from 'vitest';
import { DEFAULT_SETTINGS } from '../../db/repositories';
import { buildCsvExports } from '../../export/csvExport';
import { buildJsonExport } from '../../export/jsonExport';
import { buildMemoMarkdown } from '../../export/memoExport';
import { createDeal } from '../../lib/scoring';
import { founderProfile } from '../fixtures/founderProfile';

describe('exports', () => {
  it('exports normalized deal data as CSV and JSON', () => {
    const deal = createDeal(founderProfile, DEFAULT_SETTINGS);
    const csv = buildCsvExports([deal]);
    const json = buildJsonExport([deal]);

    expect(csv.people).toContain('Ada Founder');
    expect(csv.evidence).toContain('profile.headline');
    expect(JSON.parse(json).deals[0].profile.name).toBe('Ada Founder');
  });

  it('labels possible investor interest as unconfirmed in memos', () => {
    const deal = {
      ...createDeal(founderProfile, DEFAULT_SETTINGS),
      investorSignals: {
        confirmedInvestors: [],
        possibleInvestorInterest: ['Example Seed Partner liked launch post'],
        weakSignals: [],
        warmIntroPaths: [],
        fundThesisFit: 'unknown',
        portfolioConflicts: [],
        confidence: 0.4,
        evidenceIds: [],
      },
    };

    expect(buildMemoMarkdown(deal)).toContain('Possible investor interest, not confirmed investor approach');
  });
});
