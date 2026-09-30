import { describe, expect, it } from 'vitest';
import { DEFAULT_SETTINGS } from '../../db/repositories';
import { buildFounderGraph } from '../../graph/graphBuilder';
import { createDeal } from '../../lib/scoring';
import { founderProfile } from '../fixtures/founderProfile';

describe('graph builder', () => {
  it('builds a founder-centered evidence graph', () => {
    const deal = createDeal(founderProfile, DEFAULT_SETTINGS);
    const graph = buildFounderGraph({
      ...deal,
      ycSignals: [{
        id: 'yc_fixture',
        rfsTopic: 'AI agents for back-office work',
        fitScore: 88,
        rationale: 'Fixture topic match.',
        evidenceIds: [],
      }],
    });

    expect(graph.nodes[0].type).toBe('founder');
    expect(graph.nodes.some((node) => node.type === 'company')).toBe(true);
    expect(graph.nodes.some((node) => node.type === 'yc_rfs_topic')).toBe(true);
    expect(graph.edges.some((edge) => edge.type === 'FOUNDER_OF')).toBe(true);
    expect(graph.edges.some((edge) => edge.type === 'MATCHES_YC_RFS')).toBe(true);
  });
});
