import { normalizeRawProfile } from '../adapters/genericProfileAdapter';
import { profileFromLinkedInVisibleText } from '../adapters/linkedinSafeVisibleAdapter';
import type { RuntimeMessage } from '../lib/types';
import { captureSelectedText } from './selectedTextCapture';
import { captureVisiblePage } from './visiblePageCapture';

chrome.runtime.onMessage.addListener((message: RuntimeMessage, _sender, sendResponse) => {
  if (message.type === 'TREEO_GET_VISIBLE_PAGE') {
    sendResponse(captureVisiblePage());
    return false;
  }

  if (message.type === 'TREEO_GET_SELECTED_TEXT') {
    sendResponse(captureSelectedText());
    return false;
  }

  if (message.type === 'TREEO_GET_PROFILE') {
    const capture = captureVisiblePage();
    const profile = capture.metadata.isLinkedInLike
      ? profileFromLinkedInVisibleText(capture.rawText, capture.metadata, capture.links)
      : normalizeRawProfile(capture.rawText, capture.metadata, capture.links);
    sendResponse(profile);
    return false;
  }

  return false;
});
