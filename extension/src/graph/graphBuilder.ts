import type { FounderGraph, GraphEdge, GraphEdgeType, GraphNode, GraphNodeType, TreeoDeal } from '../lib/types';
import { hashString, truncateMiddle } from '../lib/utils';

function id(prefix: string, value: string): string {
  return `${prefix}_${hashString(value || prefix).replace(/^h_/, '')}`;
}

function confidence(value: number | undefined, fallback = 0.55): number {
  if (typeof value !== 'number' || Number.isNaN(value)) return fallback;
  return Math.max(0, Math.min(1, value > 1 ? value / 100 : value));
}

function pushNode(nodes: GraphNode[], node: GraphNode): string {
  if (!nodes.some((existing) => existing.id === node.id)) nodes.push(node);
  return node.id;
}

function pushEdge(edges: GraphEdge[], source: string, target: string, type: GraphEdgeType, edgeConfidence: number, evidenceIds: string[] = [], label?: string): void {
  if (source === target) return;
  const edgeId = `${source}_${type}_${target}`;
  if (edges.some((edge) => edge.id === edgeId)) return;
  edges.push({
    id: edgeId,
    source,
    target,
    type,
    confidence: confidence(edgeConfidence),
    evidenceIds,
    label,
  });
}

function nodeTypeFromSignal(signal: string): GraphNodeType {
  if (/risk|red flag|missing|privacy/i.test(signal)) return 'risk';
  if (/investor|fund|angel|vc/i.test(signal)) return 'investor';
  if (/market|customer|pain|buyer/i.test(signal)) return 'market';
  if (/technical|github|repo|builder/i.test(signal)) return 'github_repo';
  return 'evidence';
}

export function buildFounderGraph(deal: TreeoDeal): FounderGraph {
  const nodes: GraphNode[] = [];
  const edges: GraphEdge[] = [];
  const founderId = pushNode(nodes, {
    id: deal.profile.id || id('person', deal.profile.profileUrl || deal.profile.name || deal.id),
    type: 'founder',
    label: deal.profile.name || 'Unknown founder',
    subtitle: deal.profile.headline || deal.score.founderLabel,
    confidence: confidence(deal.score.founderLikelihoodScore, 0.45),
    evidenceIds: deal.profile.evidenceIds ?? deal.evidence.map((item) => item.id).slice(0, 3),
    data: {
      score: deal.score.total,
      founderScore: deal.score.founderLikelihoodScore,
      recommendation: deal.score.recommendation,
      photo: deal.profile.profileImageUrl,
    },
  });

  const companyLabel = deal.company?.name || deal.profile.companyName;
  let companyId = '';
  if (companyLabel || deal.profile.companyWebsite || deal.profile.companyUrl) {
    companyId = pushNode(nodes, {
      id: deal.company?.id || id('company', companyLabel || deal.profile.companyWebsite || deal.profile.companyUrl),
      type: 'company',
      label: companyLabel || truncateMiddle(deal.profile.companyWebsite || deal.profile.companyUrl, 40),
      subtitle: deal.profile.companyWebsite || deal.profile.companyUrl || deal.score.stage,
      confidence: confidence(deal.score.stageEstimate.confidence, 0.55),
      evidenceIds: deal.score.stageEstimate.evidenceIds,
      data: {
        website: deal.profile.companyWebsite,
        linkedin: deal.profile.companyUrl,
        stage: deal.score.stageEstimate.stage,
      },
    });
    pushEdge(edges, founderId, companyId, 'FOUNDER_OF', deal.score.founderLikelihoodScore, deal.score.stageEstimate.evidenceIds, 'founder signal');
  }

  for (const role of deal.profile.experience.slice(0, 8)) {
    const roleId = pushNode(nodes, {
      id: id('role', `${deal.id}:${role}`),
      type: /founder|co-founder|cofounder/i.test(role) ? 'cofounder' : 'company',
      label: truncateMiddle(role, 54),
      subtitle: 'captured role',
      confidence: 0.52,
      evidenceIds: deal.profile.evidenceIds ?? [],
    });
    pushEdge(edges, founderId, roleId, 'WORKED_AT', 0.52, deal.profile.evidenceIds ?? []);
  }

  for (const school of deal.profile.education.slice(0, 4)) {
    const schoolId = pushNode(nodes, {
      id: id('school', `${deal.id}:${school}`),
      type: 'school',
      label: truncateMiddle(school, 52),
      subtitle: 'education',
      confidence: 0.6,
      evidenceIds: deal.profile.evidenceIds ?? [],
    });
    pushEdge(edges, founderId, schoolId, 'EDUCATED_AT', 0.6, deal.profile.evidenceIds ?? []);
  }

  for (const repo of deal.githubRepos ?? []) {
    const repoId = pushNode(nodes, {
      id: repo.id,
      type: 'github_repo',
      label: `${repo.owner}/${repo.name}`,
      subtitle: `${repo.language || 'unknown'} | ${repo.stars} stars | README ${repo.readmeQuality}`,
      confidence: confidence(repo.readmeQuality, 0.5),
      evidenceIds: repo.evidenceIds,
      data: repo as unknown as Record<string, unknown>,
    });
    pushEdge(edges, founderId, repoId, 'BUILT_REPO', repo.readmeQuality, repo.evidenceIds);
  }

  for (const story of deal.hnStories ?? []) {
    const storyId = pushNode(nodes, {
      id: story.id,
      type: 'hn_story',
      label: truncateMiddle(story.title, 58),
      subtitle: `Hacker News | ${story.score} points | ${story.commentCount} comments`,
      confidence: confidence(Math.min(100, story.score + story.commentCount), 0.45),
      evidenceIds: [],
      data: story as unknown as Record<string, unknown>,
    });
    pushEdge(edges, companyId || founderId, storyId, story.type === 'show_hn' ? 'LAUNCHED_ON_HN' : 'SUPPORTED_BY_EVIDENCE', Math.min(100, story.score + story.commentCount), [], story.type === 'show_hn' ? 'Show HN' : 'HN mention');
  }

  for (const launch of deal.productHuntLaunches ?? []) {
    const launchId = pushNode(nodes, {
      id: launch.id,
      type: 'producthunt_launch',
      label: truncateMiddle(launch.name, 46),
      subtitle: `${launch.votes} votes | ${launch.comments} comments`,
      confidence: confidence(Math.min(100, launch.votes / 5 + launch.comments), 0.45),
      evidenceIds: launch.evidenceIds,
      data: launch as unknown as Record<string, unknown>,
    });
    pushEdge(edges, companyId || founderId, launchId, 'LAUNCHED_ON_PRODUCT_HUNT', Math.min(100, launch.votes / 5 + launch.comments), launch.evidenceIds);
  }

  for (const yc of deal.ycSignals ?? []) {
    const ycId = pushNode(nodes, {
      id: yc.id,
      type: 'yc_rfs_topic',
      label: truncateMiddle(yc.rfsTopic, 54),
      subtitle: `YC fit ${yc.fitScore}`,
      confidence: confidence(yc.fitScore, 0.5),
      evidenceIds: yc.evidenceIds,
      data: yc as unknown as Record<string, unknown>,
    });
    pushEdge(edges, companyId || founderId, ycId, 'MATCHES_YC_RFS', yc.fitScore, yc.evidenceIds);
  }

  if (deal.marketPain) {
    const marketId = pushNode(nodes, {
      id: id('market', deal.marketPain.marketCategory || deal.marketPain.customerSegment || deal.id),
      type: 'market',
      label: deal.marketPain.marketCategory || 'Market pain',
      subtitle: deal.marketPain.customerSegment,
      confidence: confidence(deal.marketPain.confidence),
      evidenceIds: deal.marketPain.evidenceIds,
      data: deal.marketPain as unknown as Record<string, unknown>,
    });
    pushEdge(edges, companyId || founderId, marketId, 'SUPPORTED_BY_EVIDENCE', deal.marketPain.confidence, deal.marketPain.evidenceIds);
    for (const competitor of deal.marketPain.competitors.slice(0, 8)) {
      const competitorId = pushNode(nodes, {
        id: id('competitor', competitor),
        type: 'competitor',
        label: competitor,
        subtitle: 'possible competitor',
        confidence: 0.45,
        evidenceIds: deal.marketPain.evidenceIds,
      });
      pushEdge(edges, companyId || founderId, competitorId, 'COMPETES_WITH', 0.45, deal.marketPain.evidenceIds);
    }
  }

  if (deal.investorSignals) {
    const investorLists = [
      ...deal.investorSignals.confirmedInvestors.map((name) => ({ name, confidence: 0.85, type: 'INVESTED_IN' as const })),
      ...deal.investorSignals.possibleInvestorInterest.map((name) => ({ name, confidence: 0.55, type: 'POSSIBLE_INVESTOR_INTEREST' as const })),
      ...deal.investorSignals.weakSignals.map((name) => ({ name, confidence: 0.35, type: 'POSSIBLE_INVESTOR_INTEREST' as const })),
    ];
    for (const signal of investorLists.slice(0, 12)) {
      const investorId = pushNode(nodes, {
        id: id('investor', signal.name),
        type: 'investor',
        label: truncateMiddle(signal.name, 46),
        subtitle: signal.type === 'INVESTED_IN' ? 'confirmed investor' : 'possible investor interest',
        confidence: signal.confidence,
        evidenceIds: deal.investorSignals.evidenceIds,
      });
      pushEdge(edges, investorId, companyId || founderId, signal.type, signal.confidence, deal.investorSignals.evidenceIds);
    }
  }

  for (const signal of deal.score.signals.slice(0, 14)) {
    const signalId = pushNode(nodes, {
      id: id('signal', `${signal.label}:${signal.evidence}`),
      type: nodeTypeFromSignal(signal.principle),
      label: signal.label,
      subtitle: truncateMiddle(signal.evidence, 68),
      confidence: signal.confidence,
      evidenceIds: signal.evidenceIds ?? [],
      data: signal as unknown as Record<string, unknown>,
    });
    pushEdge(edges, founderId, signalId, 'SUPPORTED_BY_EVIDENCE', signal.confidence, signal.evidenceIds ?? []);
  }

  const riskItems = [...deal.score.risks, ...(deal.riskAnalysis?.redFlags ?? [])].slice(0, 10);
  for (const risk of riskItems) {
    const riskId = pushNode(nodes, {
      id: id('risk', risk),
      type: 'risk',
      label: truncateMiddle(risk, 58),
      subtitle: 'diligence risk',
      confidence: 0.6,
      evidenceIds: [],
    });
    pushEdge(edges, companyId || founderId, riskId, 'HAS_RISK', 0.6, []);
  }

  for (const evidence of deal.evidence.slice(0, 20)) {
    const evidenceId = pushNode(nodes, {
      id: evidence.id,
      type: 'evidence',
      label: truncateMiddle(evidence.fieldPath || evidence.sourceType, 48),
      subtitle: truncateMiddle(evidence.quote, 72),
      confidence: evidence.reliability === 'high' || evidence.reliability === 'medium_high' ? 0.78 : 0.55,
      evidenceIds: [evidence.id],
      data: evidence as unknown as Record<string, unknown>,
    });
    pushEdge(edges, evidenceId, founderId, 'SUPPORTED_BY_EVIDENCE', 0.7, [evidence.id]);
  }

  return { nodes, edges };
}
