import type { SourceMetadata } from '../lib/types';
import { cleanText, nowIso } from '../lib/utils';
import { isLinkedInLikeUrl } from './pageClassifier';

export interface SelectedTextCapture {
  text: string;
  title: string;
  url: string;
  metadata: SourceMetadata;
}

export function captureSelectedText(root: Document = document): SelectedTextCapture {
  const url = location.href;
  return {
    text: cleanText(root.getSelection?.()?.toString() ?? ''),
    title: root.title,
    url,
    metadata: {
      captureMode: 'selected_text',
      sourceUrl: url,
      sourceTitle: root.title,
      sourceType: isLinkedInLikeUrl(url) ? 'linkedin_selected_text' : 'selected_text',
      capturedAt: nowIso(),
      isLinkedInLike: isLinkedInLikeUrl(url),
    },
  };
}
