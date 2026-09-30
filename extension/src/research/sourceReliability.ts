import type { SourceReliability } from '../lib/types';

export function sourceReliabilityFor(url: string, sourceType = ''): SourceReliability {
  const host = (() => {
    try {
      return new URL(url).hostname;
    } catch {
      return '';
    }
  })();
  if (sourceType.includes('approved_api') || sourceType.includes('official_api')) return 'high';
  if (host && /(^|\.)company|\.com$/.test(host) && !/(linkedin|twitter|x\.com|reddit)/.test(host)) return 'high';
  if (/github\.com|news\.ycombinator\.com|producthunt\.com/.test(host)) return 'medium_high';
  if (/linkedin\.com/.test(host)) return 'medium_high';
  if (/techcrunch|sifted|crunchbase|ycombinator/.test(host)) return 'medium';
  return 'medium_low';
}
