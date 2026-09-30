import type { AiProvider, ProviderRequest, ProviderResponse } from './types';

function textFromMessages(request: ProviderRequest): string {
  return request.messages.map((message) => message.content).join('\n').toLowerCase();
}

function mockJson(request: ProviderRequest): string {
  const text = textFromMessages(request);
  const hasFounder = /\b(founder|co-founder|ceo|cto|building)\b/.test(text);
  const hasAi = /\b(ai|llm|agent|automation|machine learning)\b/.test(text);
  const hasProduct = /\b(demo|beta|launch|waitlist|github|product)\b/.test(text);

  if (request.task === 'founder_classification') {
    return JSON.stringify({
      founderLikelihoodScore: hasFounder ? 74 : 28,
      label: hasFounder ? 'very_likely_founder' : 'weak_signal',
      evidence: hasFounder ? ['Captured text contains founder/operator language.'] : [],
      evidence_ids: [],
      missingEvidence: hasProduct ? ['customer traction'] : ['product proof', 'company website', 'customer traction'],
      confidence: hasFounder ? 0.7 : 0.38,
    });
  }

  if (request.task === 'startup_analysis') {
    return JSON.stringify({
      companySummary: hasAi ? 'AI-native startup signal found in captured evidence.' : 'Company summary is not well established from captured evidence.',
      productHypothesis: hasProduct ? 'The company appears to have a product or launch surface.' : 'Product hypothesis is unknown.',
      stageEstimate: {
        stage: hasProduct ? 'mvp_beta' : 'unknown',
        confidence: hasProduct ? 0.62 : 0.33,
        evidence_ids: [],
        missingEvidence: ['revenue', 'customer count', 'funding confirmation'],
      },
      tractionSignals: hasProduct ? ['product or launch wording'] : [],
      businessModel: 'unknown',
      credibilitySignals: hasFounder ? ['founder/operator language'] : [],
      technicalCredibility: 'unknown until GitHub or technical docs are reviewed',
      missingInfo: ['customers', 'pricing', 'technical architecture'],
    });
  }

  if (request.task === 'technical_credibility') {
    return JSON.stringify({
      repoQuality: text.includes('github') ? 'GitHub link found but repository depth requires review.' : 'No repository evidence found.',
      technicalDepth: 'unknown',
      builderProof: text.includes('github') ? ['GitHub mention'] : [],
      dependencyRisk: 'unknown',
      moat: 'unknown',
      score: text.includes('github') ? 58 : 24,
      evidence_ids: [],
    });
  }

  if (request.task === 'market_pain') {
    return JSON.stringify({
      marketCategory: hasAi ? 'AI workflow software' : 'unknown',
      customerSegment: text.includes('enterprise') ? 'enterprise buyers' : 'unknown',
      painFrequency: text.includes('manual') || text.includes('workflow') ? 58 : 20,
      painIntensity: text.includes('broken') || text.includes('expensive') ? 62 : 24,
      buyerClarity: text.includes('enterprise') || text.includes('b2b') ? 'moderate' : 'unknown',
      willingnessToPay: 'unknown',
      existingWorkarounds: text.includes('spreadsheet') ? ['spreadsheet workaround'] : [],
      competitors: [],
      confidence: 0.42,
      evidence_ids: [],
    });
  }

  if (request.task === 'hn_signal_analysis') {
    return JSON.stringify({
      showHnLaunches: text.includes('show hn') ? ['Possible Show HN launch mention'] : [],
      askHnPainClusters: [],
      founderHnCredibility: 'unknown',
      categoryHeat: text.includes('hacker news') || text.includes('show hn') ? 54 : 10,
      developerResonance: 0,
      objections: [],
      customerLanguage: [],
      competitorMentions: [],
      evidence_ids: [],
    });
  }

  if (request.task === 'investor_signals') {
    return JSON.stringify({
      confirmedInvestors: [],
      possibleInvestorInterest: text.includes('investor') || text.includes('fundraising') ? ['Possible investor or fundraising wording'] : [],
      weakSignals: [],
      warmIntroPaths: [],
      fundThesisFit: hasAi ? 'Potential fit with AI-native B2B thesis, pending evidence.' : 'unknown',
      portfolioConflicts: [],
      confidence: 0.35,
      evidence_ids: [],
    });
  }

  if (request.task === 'risk_analysis') {
    return JSON.stringify({
      redFlags: hasProduct ? [] : ['No clear product proof in captured evidence.'],
      inconsistencies: [],
      overclaimingRisk: 'medium if final memo states stage or traction without outside evidence',
      dataQualityWarnings: ['Mock provider used; analyst should verify all claims.'],
      privacyWarnings: [],
    });
  }

  return JSON.stringify({
    thirtySecondSummary: hasFounder ? 'Possible founder profile with evidence gaps around product, market pain, and traction.' : 'Insufficient founder evidence.',
    onePageMemo: [
      '## Summary',
      hasFounder ? 'Captured evidence suggests a possible founder worth monitoring.' : 'Captured evidence does not yet support a founder conclusion.',
      '',
      '## Evidence gaps',
      '- Product proof',
      '- Customer pain',
      '- Technical credibility',
      '- Investor fit',
    ].join('\n'),
    recommendation: hasFounder ? 'monitor' : 'unknown',
    outreachUrgency: hasProduct ? 'monitor closely' : 'low urgency until product proof appears',
    firstCallQuestions: [
      'What product is live today?',
      'Who is the buyer?',
      'What evidence shows repeated customer pain?',
    ],
    scorecard: {
      founderQuality: hasFounder ? 7 : 3,
      founderMarketFit: 5,
      technicalCredibility: text.includes('github') ? 6 : 3,
      commercialCredibility: 4,
      marketSize: 5,
      timing: hasAi ? 6 : 4,
      traction: hasProduct ? 5 : 2,
      fundability: 4,
      networkQuality: 3,
      redFlagRisk: hasProduct ? 3 : 6,
      dataQuality: 4,
    },
  });
}

export const mockProvider: AiProvider = {
  name: 'mock',
  defaultModel: 'mock-treeo-analyst',
  timeoutMs: 100,
  async complete(request: ProviderRequest): Promise<ProviderResponse> {
    const started = performance.now();
    return {
      provider: 'mock',
      model: request.model || this.defaultModel,
      content: mockJson(request),
      latencyMs: Math.round(performance.now() - started),
    };
  },
};
