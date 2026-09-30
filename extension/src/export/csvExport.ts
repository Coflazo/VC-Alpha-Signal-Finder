import Papa from 'papaparse';
import type { TreeoDeal } from '../lib/types';

export interface CsvExportBundle {
  people: string;
  companies: string;
  relationships: string;
  evidence: string;
  investorSignals: string;
  hnSignals: string;
  githubSignals: string;
  ycSignals: string;
  scorecard: string;
}

/**
 * Strict-quoting unparse. Every field is wrapped in double quotes so that
 * newlines, commas, and embedded quotes inside evidence quotes are preserved
 * exactly across round-trips through Excel, Numbers, and Google Sheets.
 */
function unparse(rows: Array<Record<string, unknown>>, withBom = false): string {
  const csv = Papa.unparse(rows, {
    quotes: true,
    newline: '\n',
    quoteChar: '"',
    escapeChar: '"',
  });
  // UTF-8 BOM is what Excel uses to detect UTF-8. Behind a flag so downstream
  // tools that don't strip it (some text processors) are unaffected by default.
  return withBom ? `﻿${csv}` : csv;
}

export function buildCsvExports(deals: TreeoDeal[], { utf8Bom = false }: { utf8Bom?: boolean } = {}): CsvExportBundle {
  const opt = (rows: Array<Record<string, unknown>>) => unparse(rows, utf8Bom);
  return {
    people: opt(deals.map((deal) => ({
      id: deal.profile.id,
      dealId: deal.id,
      name: deal.profile.name,
      headline: deal.profile.headline,
      location: deal.profile.location,
      profileUrl: deal.profile.profileUrl,
      companyName: deal.profile.companyName,
      founderLikelihoodScore: deal.score.founderLikelihoodScore,
      recommendation: deal.score.recommendation,
      totalScore: deal.score.total,
    }))),
    companies: opt(deals.map((deal) => ({
      dealId: deal.id,
      companyName: deal.company?.name || deal.profile.companyName,
      website: deal.company?.website || deal.profile.companyWebsite,
      linkedinUrl: deal.profile.companyUrl,
      stage: deal.score.stageEstimate.stage,
      stageConfidence: deal.score.stageEstimate.confidence,
      productHypothesis: deal.startupAnalysis?.productHypothesis ?? '',
    }))),
    relationships: opt(deals.flatMap((deal) => (deal.graph?.edges ?? []).map((edge) => ({
      dealId: deal.id,
      edgeId: edge.id,
      source: edge.source,
      target: edge.target,
      relationshipType: edge.type,
      confidence: edge.confidence,
      evidenceIds: edge.evidenceIds.join(';'),
    })))),
    evidence: opt(deals.flatMap((deal) => deal.evidence.map((item) => ({
      dealId: deal.id,
      id: item.id,
      sourceType: item.sourceType,
      sourceUrl: item.sourceUrl,
      // Preserve newlines exactly; quotes: true wraps the value so analysts
      // can paste a multiline quote into a memo without re-formatting.
      quote: item.quote,
      fieldPath: item.fieldPath,
      reliability: item.reliability,
      extractionMethod: item.extractionMethod,
      capturedAt: item.capturedAt,
    })))),
    investorSignals: opt(deals.map((deal) => ({
      dealId: deal.id,
      confirmedInvestors: deal.investorSignals?.confirmedInvestors.join(';') ?? '',
      possibleInvestorInterest: deal.investorSignals?.possibleInvestorInterest.join(';') ?? '',
      weakSignals: deal.investorSignals?.weakSignals.join(';') ?? '',
      warmIntroPaths: deal.investorSignals?.warmIntroPaths.join(';') ?? '',
      confidence: deal.investorSignals?.confidence ?? '',
    }))),
    hnSignals: opt(deals.flatMap((deal) => [
      ...(deal.hnStories ?? []).map((story) => ({
        dealId: deal.id,
        type: 'story',
        hnId: story.hnId,
        title: story.title,
        url: story.url,
        author: story.author,
        score: story.score,
        comments: story.commentCount,
      })),
      ...(deal.hnComments ?? []).map((comment) => ({
        dealId: deal.id,
        type: 'comment',
        hnId: comment.hnId,
        title: comment.text.slice(0, 180),
        url: `https://news.ycombinator.com/item?id=${comment.storyId}`,
        author: comment.author,
        score: '',
        comments: '',
      })),
    ])),
    githubSignals: opt(deals.flatMap((deal) => (deal.githubRepos ?? []).map((repo) => ({
      dealId: deal.id,
      owner: repo.owner,
      name: repo.name,
      url: repo.url,
      stars: repo.stars,
      forks: repo.forks,
      openIssues: repo.openIssues,
      language: repo.language,
      readmeQuality: repo.readmeQuality,
      tests: repo.testDetected,
      docs: repo.docsDetected,
    })))),
    ycSignals: opt(deals.flatMap((deal) => (deal.ycSignals ?? []).map((signal) => ({
      dealId: deal.id,
      topic: signal.rfsTopic,
      fitScore: signal.fitScore,
      rationale: signal.rationale,
    })))),
    scorecard: opt(deals.map((deal) => ({
      dealId: deal.id,
      founder: deal.profile.name,
      total: deal.score.total,
      founderLikelihood: deal.score.founderLikelihoodScore,
      technicalCredibility: deal.score.technicalCredibility,
      marketPain: deal.score.marketPain,
      marketTiming: deal.score.marketTiming,
      investorFit: deal.score.investorFit,
      outreachUrgency: deal.score.outreachUrgency,
      dataQuality: deal.score.dataQuality,
      recommendation: deal.score.recommendation,
    }))),
  };
}
