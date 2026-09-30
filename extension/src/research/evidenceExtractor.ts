import type { CaptureMode, Evidence, SourceReliability } from '../lib/types';
import { makeId, nowIso } from '../lib/utils';

export function createEvidence(input: {
  sourceType: string;
  sourceUrl: string;
  capturedText: string;
  quote?: string;
  fieldPath: string;
  reliability: SourceReliability;
  extractionMethod: CaptureMode | 'public_api' | 'public_web' | 'llm' | 'heuristic';
  capturedAt?: string;
  freshnessScore?: number;
}): Evidence {
  return {
    id: makeId('ev'),
    sourceType: input.sourceType,
    sourceUrl: input.sourceUrl,
    capturedText: input.capturedText.slice(0, 5000),
    quote: (input.quote || input.capturedText).slice(0, 600),
    fieldPath: input.fieldPath,
    reliability: input.reliability,
    extractionMethod: input.extractionMethod,
    capturedAt: input.capturedAt || nowIso(),
    freshnessScore: input.freshnessScore ?? 1,
  };
}
