export function isLinkedInLikeUrl(url: string): boolean {
  try {
    const parsed = new URL(url);
    return /(^|\.)linkedin\.com$/i.test(parsed.hostname);
  } catch {
    return false;
  }
}

export function isProfileLikeText(text: string): boolean {
  return /\b(founder|co-founder|ceo|cto|building|startup|experience|education|about)\b/i.test(text);
}
