import type { ExtractedProfile, YcSignalRecord } from '../../lib/types';
import { makeId } from '../../lib/utils';
import { fetchYcRfsTopics, type YcRfsTopic } from './ycRfsClient';

/**
 * Tokenize a piece of text into a set of meaningful tokens. Strips
 * non-alphanumeric runs and drops short stop tokens.
 */
function tokenize(text: string): string[] {
  return text
    .toLowerCase()
    .split(/[^a-z0-9]+/)
    .filter((token) => token.length > 2);
}

function termFrequencies(tokens: string[]): Map<string, number> {
  const freq = new Map<string, number>();
  for (const token of tokens) freq.set(token, (freq.get(token) ?? 0) + 1);
  return freq;
}

function inverseDocumentFrequency(topics: YcRfsTopic[]): Map<string, number> {
  const total = topics.length;
  const counts = new Map<string, number>();
  for (const topic of topics) {
    const seen = new Set(topic.keywords);
    for (const token of seen) counts.set(token, (counts.get(token) ?? 0) + 1);
  }
  const idf = new Map<string, number>();
  for (const [token, count] of counts) idf.set(token, Math.log(total / count));
  return idf;
}

/**
 * TF-IDF cosine similarity between the profile corpus and each RFS topic.
 * Replaces the `min(100, matches * 22)` linear count, which gave the same
 * weight to a marquee keyword as to a noise token.
 */
function cosineSimilarity(profileTokens: string[], topicKeywords: string[], idf: Map<string, number>): number {
  const profileTf = termFrequencies(profileTokens);
  const topicTf = termFrequencies(topicKeywords);
  const allTokens = new Set([...profileTf.keys(), ...topicTf.keys()]);
  let dot = 0;
  let profileMag = 0;
  let topicMag = 0;
  for (const token of allTokens) {
    const idfWeight = idf.get(token) ?? 1;
    const profileValue = (profileTf.get(token) ?? 0) * idfWeight;
    const topicValue = (topicTf.get(token) ?? 0) * idfWeight;
    dot += profileValue * topicValue;
    profileMag += profileValue * profileValue;
    topicMag += topicValue * topicValue;
  }
  if (profileMag === 0 || topicMag === 0) return 0;
  return dot / (Math.sqrt(profileMag) * Math.sqrt(topicMag));
}

export async function analyzeYcFit(profile: ExtractedProfile): Promise<YcSignalRecord[]> {
  const profileText = [
    profile.headline,
    profile.about,
    profile.companyName,
    profile.companyWebsite,
    ...profile.experience,
    ...profile.posts,
  ].join(' ');
  const profileTokens = tokenize(profileText);
  const topics = await fetchYcRfsTopics();
  const idf = inverseDocumentFrequency(topics);

  return topics
    .map((topic) => {
      const similarity = cosineSimilarity(profileTokens, topic.keywords, idf);
      const matchedKeywords = topic.keywords.filter((kw) => profileText.toLowerCase().includes(kw));
      return {
        id: makeId('yc_signal'),
        rfsTopic: topic.topic,
        // similarity is in [0,1]; scale to [0,100] with a soft floor so weak
        // matches show up at 5..20 rather than being dropped silently.
        fitScore: Math.round(similarity * 100),
        rationale: matchedKeywords.length
          ? `TF-IDF cosine ${similarity.toFixed(2)}. Matched keywords: ${matchedKeywords.slice(0, 6).join(', ')}.`
          : `TF-IDF cosine ${similarity.toFixed(2)}. No direct keyword overlap; weak categorical match only.`,
        evidenceIds: [],
      } satisfies YcSignalRecord;
    })
    .filter((signal) => signal.fitScore > 5)
    .sort((a, b) => b.fitScore - a.fitScore);
}
