import { describe, expect, it } from 'vitest';
import { mockProvider } from '../../ai/providers/mockProvider';

describe('mock LLM provider', () => {
  it('returns strict JSON for startup analysis without external APIs', async () => {
    const response = await mockProvider.complete({
      task: 'startup_analysis',
      messages: [{ role: 'user', content: 'Analyze LedgerFlow AI, a beta product for finance operations teams.' }],
      model: 'mock-treeo-analyst',
      maxTokens: 1200,
      temperature: 0,
    });

    const parsed = JSON.parse(response.content) as Record<string, unknown>;
    expect(response.provider).toBe('mock');
    expect(parsed.companySummary).toBeTypeOf('string');
    expect(parsed.stageEstimate).toBeTypeOf('object');
  });
});
