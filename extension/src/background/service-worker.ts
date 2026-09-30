import { profileFromApprovedApiRecord } from '../adapters/approvedApiAdapterStub';
import { profilesFromCsv } from '../adapters/csvImportAdapter';
import { normalizeRawProfile } from '../adapters/genericProfileAdapter';
import { profileFromLinkedInVisibleText } from '../adapters/linkedinSafeVisibleAdapter';
import { profileFromManualPaste } from '../adapters/manualPasteAdapter';
import { runFounderAnalysis } from '../ai/pipeline';
import { isPrivateHost, sendCapture } from '../engine/engineClient';
import { buildFounderGraph } from '../graph/graphBuilder';
import { runResearch } from '../research/researchOrchestrator';
import { deleteAllLocalData, getDeals, getLastDeal, getRunsForDeal, getSettings, saveDeal, saveRuns, updateDeal } from '../lib/storage';
import { installRetentionAlarm, RETENTION_ALARM, runRetentionPurge } from '../lib/retention';
import type { CaptureMode, EngineResult, ExtractedProfile, RuntimeMessage, SourceMetadata, TreeoDeal } from '../lib/types';
import { cleanText, nowIso } from '../lib/utils';

interface CapturedPage {
  rawText: string;
  selectedText: string;
  links: string[];
  title: string;
  url: string;
  metadata: SourceMetadata;
}

interface AnalyzePayload {
  tabId?: number;
  mode?: CaptureMode;
  rawText?: string;
  sourceUrl?: string;
  sourceTitle?: string;
  private?: boolean;
}

/** The text the analyst chose, as the engine receives it. Absent for file imports. */
interface CapturedText {
  text: string;
  url?: string;
  title?: string;
}

async function getActiveTab(): Promise<chrome.tabs.Tab | undefined> {
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  return tabs[0];
}

async function openPanel(tabId?: number): Promise<void> {
  if (!chrome.sidePanel?.open) return;
  const tab = tabId ? await chrome.tabs.get(tabId).catch(() => undefined) : await getActiveTab();
  if (tab?.id) await chrome.sidePanel.open({ tabId: tab.id });
}

function parseFileProfile(rawText: string): ExtractedProfile {
  const trimmed = rawText.trim();
  if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
    const parsed = JSON.parse(trimmed) as unknown;
    const record = Array.isArray(parsed) ? parsed[0] : parsed;
    if (!record || typeof record !== 'object') throw new Error('Imported JSON must contain a profile object or array.');
    return profileFromApprovedApiRecord(record as Record<string, unknown>);
  }
  const [profile] = profilesFromCsv(rawText);
  if (!profile) throw new Error('Imported CSV did not contain a profile row.');
  return profile;
}

async function captureFromTab(tabId: number, mode: Extract<CaptureMode, 'visible_page' | 'selected_text'>): Promise<CapturedPage> {
  const [result] = await chrome.scripting.executeScript({
    target: { tabId },
    func: (captureMode: 'visible_page' | 'selected_text') => {
      const clean = (value: string | null | undefined) => (value ?? '').replace(/\s+/g, ' ').trim();
      const isLinkedInLike = (() => {
        try {
          return /(^|\.)linkedin\.com$/i.test(new URL(location.href).hostname);
        } catch {
          return false;
        }
      })();
      const main = document.querySelector('main') ?? document.body;
      const rawText = captureMode === 'selected_text'
        ? clean(document.getSelection?.()?.toString() ?? '')
        : clean(main?.textContent ?? document.body?.textContent ?? '');
      const selectedText = clean(document.getSelection?.()?.toString() ?? '');
      const links = Array.from(document.querySelectorAll<HTMLAnchorElement>('a[href]'))
        .map((anchor) => anchor.href)
        .filter((href) => /^https?:/.test(href))
        .filter((href, index, list) => list.indexOf(href) === index)
        .slice(0, 80);
      return {
        rawText,
        selectedText,
        links,
        title: document.title,
        url: location.href,
        metadata: {
          captureMode,
          sourceUrl: location.href,
          sourceTitle: document.title,
          sourceType: isLinkedInLike ? `linkedin_${captureMode}` : captureMode,
          capturedAt: new Date().toISOString(),
          isLinkedInLike,
        },
      };
    },
    args: [mode],
  });

  const capture = result?.result as CapturedPage | undefined;
  if (!capture?.rawText) {
    throw new Error(mode === 'selected_text' ? 'Select profile text before analyzing selected text.' : 'No visible page text was captured.');
  }
  return capture;
}

async function profileFromMessage(payload: AnalyzePayload | undefined, senderTabId?: number): Promise<{ profile: ExtractedProfile; tabId?: number; page?: CapturedText }> {
  const mode = payload?.mode ?? (payload?.rawText ? 'manual_paste' : 'visible_page');
  if (mode === 'manual_paste') {
    if (!payload?.rawText?.trim()) throw new Error('Paste profile text before analysis.');
    return {
      profile: profileFromManualPaste(payload.rawText, payload.sourceTitle || 'Manual paste'),
      tabId: payload.tabId ?? senderTabId,
      page: { text: payload.rawText, title: payload.sourceTitle },
    };
  }

  if (mode === 'file_import') {
    if (!payload?.rawText?.trim()) throw new Error('Import a CSV or JSON file before analysis.');
    return {
      profile: parseFileProfile(payload.rawText),
      tabId: payload.tabId ?? senderTabId,
    };
  }

  if (payload?.rawText?.trim()) {
    const metadata: SourceMetadata = {
      captureMode: mode,
      sourceUrl: payload.sourceUrl,
      sourceTitle: payload.sourceTitle,
      sourceType: mode,
      capturedAt: nowIso(),
      isLinkedInLike: Boolean(payload.sourceUrl && /linkedin\.com/i.test(payload.sourceUrl)),
    };
    return {
      profile: normalizeRawProfile(payload.rawText, metadata),
      tabId: payload.tabId ?? senderTabId,
      page: { text: payload.rawText, url: payload.sourceUrl, title: payload.sourceTitle },
    };
  }

  const active = payload?.tabId ? await chrome.tabs.get(payload.tabId) : await getActiveTab();
  const tabId = active?.id ?? senderTabId;
  if (!tabId) throw new Error('No active tab was available for capture.');
  const capture = await captureFromTab(tabId, mode === 'selected_text' ? 'selected_text' : 'visible_page');
  const profile = capture.metadata.isLinkedInLike
    ? profileFromLinkedInVisibleText(capture.rawText, capture.metadata, capture.links)
    : normalizeRawProfile(capture.rawText, capture.metadata, capture.links);
  return { profile, tabId, page: { text: capture.rawText, url: capture.url, title: capture.title } };
}

async function analyzeProfile(profile: ExtractedProfile, tabId?: number, page?: CapturedText & { private: boolean }): Promise<TreeoDeal> {
  const settings = await getSettings();
  // Started first and awaited last, so the engine's triage runs while the local
  // analysis does rather than after it.
  const engine: Promise<EngineResult | undefined> = page && settings.engineEnabled
    ? sendCapture({ ...page, thesis: settings.engineThesis.trim() || undefined })
    : Promise.resolve(undefined);
  const research = await runResearch(profile, settings);
  const { deal: analyzed, runs } = await runFounderAnalysis(profile, settings, research);
  let deal = {
    ...analyzed,
    researchQueries: research.queries,
    hnStories: research.hnStories,
    hnComments: research.hnComments,
    githubRepos: research.githubRepos,
    ycSignals: research.ycSignals,
    productHuntLaunches: research.productHuntLaunches,
    tags: [...new Set([...analyzed.tags, ...research.warnings])],
    engine: await engine,
  };
  deal = { ...deal, graph: buildFounderGraph(deal), updatedAt: nowIso() };
  await saveDeal(deal);
  await saveRuns(runs);
  if (settings.autoOpenSidePanel) await openPanel(tabId).catch(() => undefined);
  return deal;
}

chrome.runtime.onInstalled.addListener(async () => {
  if (chrome.sidePanel?.setPanelBehavior) {
    await chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: false });
  }
  installRetentionAlarm();
});

if (chrome.alarms?.onAlarm) {
  chrome.alarms.onAlarm.addListener((alarm) => {
    if (alarm.name === RETENTION_ALARM) {
      void runRetentionPurge();
    }
  });
}

chrome.runtime.onMessage.addListener((message: RuntimeMessage, sender, sendResponse) => {
  void (async () => {
    try {
      if (message.type === 'TREEO_ANALYZE_CURRENT') {
        const { profile, tabId, page } = await profileFromMessage(message.payload, sender.tab?.id);
        const isPrivate = message.payload?.private ?? isPrivateHost(page?.url);
        const deal = await analyzeProfile(profile, tabId, page && { ...page, private: isPrivate });
        sendResponse({ ok: true, deal });
        chrome.runtime.sendMessage({ type: 'TREEO_ANALYSIS_COMPLETE', payload: deal } satisfies RuntimeMessage).catch(() => undefined);
        return;
      }

      if (message.type === 'TREEO_SAVE_DEAL') {
        await saveDeal(message.payload);
        sendResponse({ ok: true });
        return;
      }

      if (message.type === 'TREEO_UPDATE_DEAL') {
        await updateDeal(message.payload);
        sendResponse({ ok: true });
        return;
      }

      if (message.type === 'TREEO_GET_DEALS') {
        sendResponse({ ok: true, deals: await getDeals() });
        return;
      }

      if (message.type === 'TREEO_GET_LAST_DEAL') {
        sendResponse({ ok: true, deal: await getLastDeal() });
        return;
      }

      if (message.type === 'TREEO_OPEN_PANEL') {
        await openPanel(sender.tab?.id);
        sendResponse({ ok: true });
        return;
      }

      if (message.type === 'TREEO_DELETE_ALL_DATA') {
        await deleteAllLocalData();
        sendResponse({ ok: true });
        return;
      }

      if (message.type === 'TREEO_GET_RUNS') {
        sendResponse({ ok: true, runs: await getRunsForDeal(message.payload.dealId) });
        return;
      }

      if (message.type === 'TREEO_GET_VISIBLE_PAGE' || message.type === 'TREEO_GET_SELECTED_TEXT' || message.type === 'TREEO_GET_PROFILE') {
        const tabId = sender.tab?.id ?? (await getActiveTab())?.id;
        if (!tabId) throw new Error('No active tab was available for capture.');
        const capture = await captureFromTab(tabId, message.type === 'TREEO_GET_SELECTED_TEXT' ? 'selected_text' : 'visible_page');
        sendResponse({ ok: true, capture });
        return;
      }
    } catch (error) {
      const messageText = error instanceof Error ? error.message : cleanText(String(error));
      sendResponse({ ok: false, error: messageText });
      chrome.runtime.sendMessage({ type: 'TREEO_ERROR', payload: { message: messageText } } satisfies RuntimeMessage).catch(() => undefined);
    }
  })();
  return true;
});
