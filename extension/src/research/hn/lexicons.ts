/**
 * Versioned, weighted lexicons used by the HN trend miner. Lifting these out
 * of the regex inline makes them testable and lets us change one word without
 * editing the miner.
 *
 * Each lexicon entry: term substring and weight (0..1) for confidence.
 */
export interface LexiconEntry {
  term: string;
  weight: number;
  label: string;
}

export const PAIN_LEXICON: LexiconEntry[] = [
  { term: 'would pay', weight: 0.9, label: 'willingness to pay' },
  { term: 'pay for', weight: 0.7, label: 'willingness to pay' },
  { term: 'we built this internally', weight: 0.85, label: 'internal workaround' },
  { term: 'we built our own', weight: 0.8, label: 'internal workaround' },
  { term: 'is broken', weight: 0.75, label: 'high-friction language' },
  { term: 'frustrating', weight: 0.65, label: 'high-friction language' },
  { term: 'pain point', weight: 0.7, label: 'pain language' },
  { term: 'workaround', weight: 0.65, label: 'workaround language' },
  { term: 'spreadsheet hell', weight: 0.85, label: 'workaround language' },
  { term: 'zapier glue', weight: 0.6, label: 'workaround language' },
];

export const PRODUCT_LEXICON: LexiconEntry[] = [
  { term: 'live demo', weight: 0.7, label: 'demo available' },
  { term: 'try the demo', weight: 0.8, label: 'demo available' },
  { term: 'open source', weight: 0.7, label: 'open source positioning' },
  { term: 'self-hosted', weight: 0.65, label: 'self-host option' },
  { term: 'api docs', weight: 0.7, label: 'API discussed' },
  { term: 'rest api', weight: 0.55, label: 'API discussed' },
  { term: 'sdk', weight: 0.55, label: 'SDK available' },
  { term: 'waitlist', weight: 0.6, label: 'waitlist gated' },
];

export const LEXICON_VERSION = '2026-06-1';

export function matchLexicon(corpus: string, lexicon: LexiconEntry[]): Array<{ label: string; weight: number }> {
  const lower = corpus.toLowerCase();
  const out: Array<{ label: string; weight: number }> = [];
  const seen = new Set<string>();
  for (const entry of lexicon) {
    if (lower.includes(entry.term) && !seen.has(entry.label)) {
      out.push({ label: entry.label, weight: entry.weight });
      seen.add(entry.label);
    }
  }
  return out;
}

/**
 * Exponential recency decay clamped to [0.25, 1.0]. A 6-month-old signal is
 * worth ~e^(-1) ≈ 0.37 of a fresh one; a 2-year-old signal is clamped to 0.25
 * so historical context is not silently zeroed out.
 */
export function recencyDecay(isoDate: string): number {
  if (!isoDate) return 0.25;
  const ts = Date.parse(isoDate);
  if (Number.isNaN(ts)) return 0.25;
  const ageDays = (Date.now() - ts) / 86_400_000;
  const decay = Math.exp(-ageDays / 180);
  return Math.max(0.25, Math.min(1, decay));
}
