import type { SourceMetadata } from '../lib/types';
import { cleanText, nowIso } from '../lib/utils';
import { isLinkedInLikeUrl } from './pageClassifier';

export interface VisiblePageCapture {
  rawText: string;
  selectedText: string;
  links: string[];
  title: string;
  url: string;
  metadata: SourceMetadata;
}

export function captureVisiblePage(root: Document = document): VisiblePageCapture {
  const main = root.querySelector('main') ?? root.body;
  const rawText = cleanText(main?.textContent ?? root.body?.textContent ?? '');
  const selectedText = cleanText(root.getSelection?.()?.toString() ?? '');
  const links = [...root.querySelectorAll<HTMLAnchorElement>('a[href]')]
    .map((anchor) => anchor.href)
    .filter((href) => /^https?:/.test(href))
    .filter((href, index, list) => list.indexOf(href) === index)
    .slice(0, 80);
  const url = location.href;

  return {
    rawText,
    selectedText,
    links,
    title: root.title,
    url,
    metadata: {
      captureMode: 'visible_page',
      sourceUrl: url,
      sourceTitle: root.title,
      sourceType: isLinkedInLikeUrl(url) ? 'linkedin_visible_page' : 'visible_page',
      capturedAt: nowIso(),
      isLinkedInLike: isLinkedInLikeUrl(url),
    },
  };
}
