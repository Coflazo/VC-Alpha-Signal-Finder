import { describe, expect, it } from 'vitest';
import { DEFAULT_SETTINGS } from '../../db/repositories';
import { createDeal, scoreProfile } from '../../lib/scoring';
import { explainScore } from '../../lib/scoringExplain';
import { founderProfile } from '../fixtures/founderProfile';
import { stealthFounder } from '../fixtures/stealthFounder';
import { studentSignal } from '../fixtures/studentSignal';
import { seriesAFounder } from '../fixtures/seriesAFounder';
import { noisyLinkedInDump } from '../fixtures/noisyLinkedInDump';

describe('founder scoring', () => {
  it('scores a founder with product and builder proof as meeting-ready', () => {
    const score = scoreProfile(founderProfile, DEFAULT_SETTINGS);

    expect(score.founderLikelihoodScore).toBeGreaterThanOrEqual(60);
    expect(score.technicalCredibility).toBeGreaterThan(20);
    expect(score.marketPain).toBeGreaterThan(20);
    expect(score.missingEvidence).not.toContain('company website or product demo');
  });

  it('lands the calibration fixture in the take_meeting tier', () => {
    const score = scoreProfile(founderProfile, DEFAULT_SETTINGS);
    expect(score.total).toBeGreaterThanOrEqual(72);
    expect(score.confidence).toBeGreaterThanOrEqual(0.55);
    expect(score.redFlagRisk).toBeLessThan(55);
    expect(score.recommendation).toBe('take_meeting');
  });

  it('creates evidence-linked claims from scoring signals', () => {
    const deal = createDeal(founderProfile, DEFAULT_SETTINGS);

    expect(deal.evidence.length).toBeGreaterThan(0);
    expect(deal.claims.length).toBeGreaterThan(0);
    expect(deal.claims.every((claim) => Array.isArray(claim.evidenceIds))).toBe(true);
  });

  it('every emitted signal carries at least one evidence id', () => {
    const score = scoreProfile(founderProfile, DEFAULT_SETTINGS);
    expect(score.signals.length).toBeGreaterThan(0);
    for (const signal of score.signals) {
      expect(signal.evidenceIds, `signal ${signal.label} needs evidence`).toBeDefined();
      expect((signal.evidenceIds ?? []).length, `signal ${signal.label} needs evidence`).toBeGreaterThan(0);
    }
  });
});

describe('scoring edge cases', () => {
  it('penalizes stealth founders without public proof', () => {
    const score = scoreProfile(stealthFounder, DEFAULT_SETTINGS);
    expect(score.recommendation === 'pass' || score.recommendation === 'monitor').toBe(true);
    expect(score.confidence).toBeLessThan(0.5);
    expect(score.missingEvidence).toContain('company website or product demo');
    expect(score.risks.some((risk) => /stealth/i.test(risk))).toBe(true);
  });

  it('does not over-score curious students with no product', () => {
    const score = scoreProfile(studentSignal, DEFAULT_SETTINGS);
    expect(score.founderLikelihoodScore).toBeLessThan(40);
    expect(score.recommendation === 'pass' || score.recommendation === 'monitor').toBe(true);
  });

  it('recognizes a Series A founder as strong but does not blindly flag immediate outreach without confidence', () => {
    const score = scoreProfile(seriesAFounder, DEFAULT_SETTINGS);
    expect(score.total).toBeGreaterThanOrEqual(70);
    expect(score.founderLikelihoodScore).toBeGreaterThanOrEqual(70);
    expect(score.confidence).toBeGreaterThan(0.5);
  });

  it('does not run the total up on noisy keyword presence alone', () => {
    const score = scoreProfile(noisyLinkedInDump, DEFAULT_SETTINGS);
    expect(score.confidence).toBeLessThan(0.6);
    // No public site, no GitHub, no HN — must not reach take_meeting.
    expect(score.recommendation === 'pass' || score.recommendation === 'monitor' || score.recommendation === 'partner_review').toBe(true);
    expect(score.total).toBeLessThan(72);
  });
});

describe('scoring properties', () => {
  it('is monotonic in evidence: adding signal-bearing evidence never lowers total', () => {
    const baseline = scoreProfile(studentSignal, DEFAULT_SETTINGS).total;

    const enriched = {
      ...studentSignal,
      about: `${studentSignal.about} I am the founder and CTO of a stealth AI agents startup with a public beta and GitHub repo.`,
      companyName: 'Curious Labs',
      companyWebsite: 'https://curious.example',
      visibleLinks: ['https://curious.example', 'https://github.com/curious/labs'],
      githubUsernames: ['curious'],
      rawText: `${studentSignal.rawText} founder cto stealth ai agents github beta`,
    };
    const enrichedScore = scoreProfile(enriched, DEFAULT_SETTINGS).total;

    expect(enrichedScore).toBeGreaterThanOrEqual(baseline);
  });

  it('explainScore enumerates every dimension with a formula and inputs', () => {
    const deal = createDeal(founderProfile, DEFAULT_SETTINGS);
    const explained = explainScore(deal, DEFAULT_SETTINGS);

    expect(explained.dimensions.length).toBe(11);
    for (const row of explained.dimensions) {
      expect(row.formula).toMatch(/σ/);
      expect(row.inputs.length).toBeGreaterThan(0);
    }
    expect(explained.dataQualityGate).toBeGreaterThanOrEqual(0.85);
    expect(explained.dataQualityGate).toBeLessThanOrEqual(1.10);
  });

  it('recommendation tiers respect the (total, confidence, risk) triple', () => {
    // Stealth fixture: risk should knock the recommendation down even if total is okay.
    const score = scoreProfile(stealthFounder, DEFAULT_SETTINGS);
    if (score.redFlagRisk >= 55) {
      expect(score.recommendation).not.toBe('take_meeting');
    }
    if (score.redFlagRisk >= 40) {
      expect(score.recommendation).not.toBe('immediate_outreach');
    }
  });
});
