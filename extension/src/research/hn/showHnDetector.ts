export function isShowHnTitle(title: string): boolean {
  return /^show hn:?/i.test(title.trim());
}

export function showHnQualitySignals(title: string, url: string, text = ''): string[] {
  const corpus = `${title} ${url} ${text}`.toLowerCase();
  return [
    corpus.includes('demo') ? 'demo available' : '',
    corpus.includes('github') ? 'source or repo linked' : '',
    corpus.includes('waitlist') ? 'waitlist only' : '',
    corpus.includes('api') ? 'API surface' : '',
    corpus.includes('open source') ? 'open-source positioning' : '',
  ].filter(Boolean);
}
