import { QueryClient, QueryClientProvider, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { FileUp, PanelRightOpen, RefreshCcw, Scissors, Settings, Sparkles, TextCursorInput } from 'lucide-react';
import React from 'react';
import { createRoot } from 'react-dom/client';
import '../styles/globals.css';
import { Badge, Button, Card, IconButton, LogoLockup, RadixProgress, RadixSwitch, Recommendation, ScoreRing, Textarea, Toast } from '../components/ui';
import { isPrivateHost } from '../engine/engineClient';
import { applyTheme, getLastDeal, getSettings } from '../lib/storage';
import type { CaptureMode, RuntimeMessage, TreeoDeal, TreeoSettings } from '../lib/types';
import { isLinkedInLikeUrl } from '../content/pageClassifier';

const queryClient = new QueryClient();

function analyze(mode: CaptureMode, rawText?: string, sourceTitle?: string, isPrivate?: boolean): Promise<TreeoDeal> {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendMessage({
      type: 'TREEO_ANALYZE_CURRENT',
      payload: { mode, rawText, sourceTitle, private: isPrivate },
    } satisfies RuntimeMessage, (response) => {
      if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
      else if (!response?.ok) reject(new Error(response?.error ?? 'Analysis failed'));
      else resolve(response.deal as TreeoDeal);
    });
  });
}

/**
 * Open the side panel as a direct response to the user click. Chrome only
 * honors `chrome.sidePanel.open` from a user-gesture context, so the popup
 * must call it itself — messaging the service worker drops the gesture and
 * the call is silently rejected.
 */
async function openSidePanelFromPopup(): Promise<void> {
  try {
    if (chrome.sidePanel?.open) {
      const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
      const windowId = tab?.windowId ?? (await chrome.windows.getCurrent()).id;
      if (windowId !== undefined) await chrome.sidePanel.open({ windowId });
    }
  } catch {
    // Chrome rejected the open (no gesture context or panel already shown).
    // Fall back to ferrying through the service worker.
    chrome.runtime.sendMessage({ type: 'TREEO_OPEN_PANEL' } satisfies RuntimeMessage).catch(() => undefined);
  }
}

function useBootTheme() {
  React.useEffect(() => {
    getSettings().then((settings) => applyTheme(settings.theme)).catch(() => undefined);
  }, []);
}

function useActiveTabUrl() {
  return useQuery({
    queryKey: ['activeTab'],
    queryFn: async () => {
      const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
      return tab?.url ?? '';
    },
    staleTime: 5000,
  });
}

function activeProviderLabel(settings: TreeoSettings | undefined): string {
  if (!settings) return 'Loading';
  if (settings.localOnlyMode) return 'Mock · offline';
  if (!settings.llmDisclosureAccepted) return 'Mock · disclosure off';
  const enabled = settings.providerOrder.find((name) => settings.providers[name]?.enabled && name !== 'mock');
  if (!enabled) return 'Mock · no provider enabled';
  return `${enabled} · ${settings.providers[enabled].model ?? 'default'}`;
}

function CaptureButton({ mode, label, pending, onClick, icon }: { mode: CaptureMode; label: string; pending: boolean; onClick: (mode: CaptureMode) => void; icon: React.ReactNode }) {
  return (
    <Button variant={mode === 'visible_page' ? 'primary' : 'ghost'} className="w-full justify-start" disabled={pending} onClick={() => onClick(mode)}>
      {pending ? <RefreshCcw className="animate-spin" size={16} /> : icon}
      {label}
    </Button>
  );
}

function ProgressStrip({ visible }: { visible: boolean }) {
  const [pct, setPct] = React.useState(0);
  React.useEffect(() => {
    if (!visible) { setPct(0); return; }
    let cancelled = false;
    let value = 5;
    function tick() {
      if (cancelled) return;
      value = Math.min(95, value + (95 - value) * 0.06);
      setPct(value);
      window.setTimeout(tick, 250);
    }
    tick();
    return () => { cancelled = true; };
  }, [visible]);
  if (!visible) return null;
  return (
    <RadixProgress.Root value={pct} className="relative h-1 overflow-hidden rounded-full bg-[var(--line)]" aria-label="Running analysis">
      <RadixProgress.Indicator className="h-full bg-[var(--accent)]" style={{ width: `${pct}%`, transition: 'width 300ms var(--ease-emil)' }} />
    </RadixProgress.Root>
  );
}

/**
 * Minimalist deal slip. No tile row, no chrome — name and headline lead,
 * then a single hairline-divided stat row, then the recommendation pill and
 * a primary CTA. The card itself is one surface, not nested cards.
 */
function DealSlip({ deal, llmLabel, onOpenDashboard }: { deal: TreeoDeal; llmLabel: string; onOpenDashboard: () => void }) {
  const total = deal.score.total;
  const conf = Math.round(deal.score.confidence * 100);
  return (
    <Card className="grid gap-5 p-5">
      <header className="grid grid-cols-[1fr_auto] items-start gap-4">
        <div className="min-w-0">
          <h2 className="truncate text-lg font-semibold tracking-tight">{deal.profile.name || 'Unknown founder'}</h2>
          {deal.profile.headline ? (
            <p className="mt-1 line-clamp-2 text-sm leading-snug text-[var(--muted)]">{deal.profile.headline}</p>
          ) : null}
          {deal.profile.companyName ? (
            <p className="mt-1 truncate text-xs text-[var(--muted)]">{deal.profile.companyName}{deal.profile.location ? ` · ${deal.profile.location}` : ''}</p>
          ) : null}
        </div>
        <ScoreRing score={total} confidence={deal.score.confidence} size={80} />
      </header>

      <p className="text-sm leading-relaxed text-[var(--text)]">{deal.score.summary}</p>

      <div className="grid grid-cols-3 divide-x divide-[var(--line)] border-y border-[var(--line)] py-3 text-center">
        <div>
          <div className="data-font text-base font-semibold">{total}</div>
          <div className="mt-0.5 text-[10px] uppercase tracking-[0.16em] text-[var(--muted)]">Total</div>
        </div>
        <div>
          <div className="data-font text-base font-semibold">{conf}%</div>
          <div className="mt-0.5 text-[10px] uppercase tracking-[0.16em] text-[var(--muted)]">Confidence</div>
        </div>
        <div>
          <div className="data-font text-base font-semibold">{deal.score.redFlagRisk}</div>
          <div className="mt-0.5 text-[10px] uppercase tracking-[0.16em] text-[var(--muted)]">Risk</div>
        </div>
      </div>

      <div className="grid gap-3">
        <div className="flex items-center justify-between gap-2 text-xs">
          <Recommendation value={String(deal.score.recommendation)} />
          <span className="truncate text-[var(--muted)]">{llmLabel}</span>
        </div>
        <p className="text-sm leading-relaxed text-[var(--muted)]">{deal.score.nextAction}</p>
        <Button onClick={onOpenDashboard}>
          <PanelRightOpen size={16} />
          Open dashboard
        </Button>
      </div>
    </Card>
  );
}

function PopupApp() {
  useBootTheme();
  const qc = useQueryClient();
  const activeTab = useActiveTabUrl();
  const settingsQuery = useQuery({ queryKey: ['settings'], queryFn: getSettings });
  const lastDeal = useQuery({ queryKey: ['lastDeal'], queryFn: getLastDeal });
  const [pasteOpen, setPasteOpen] = React.useState(false);
  const [pasteText, setPasteText] = React.useState('');
  const fileInputRef = React.useRef<HTMLInputElement>(null);
  const [lastRequest, setLastRequest] = React.useState<{ mode: CaptureMode; rawText?: string; sourceTitle?: string } | null>(null);
  // Null until the analyst touches the switch; until then webmail defaults to private.
  const [privateChoice, setPrivateChoice] = React.useState<boolean | null>(null);
  const isPrivate = privateChoice ?? isPrivateHost(activeTab.data);

  const analyzeMutation = useMutation({
    mutationFn: ({ mode, rawText, sourceTitle }: { mode: CaptureMode; rawText?: string; sourceTitle?: string }) => analyze(mode, rawText, sourceTitle, isPrivate),
    onMutate: (payload) => { setLastRequest(payload); },
    onSuccess: (deal) => {
      qc.setQueryData(['lastDeal'], deal);
      setPasteOpen(false);
      setPasteText('');
    },
  });

  const deal = analyzeMutation.data ?? lastDeal.data;
  const isLinkedInLike = isLinkedInLikeUrl(activeTab.data ?? '');
  const settings = settingsQuery.data;
  const llmLabel = `LLM: ${activeProviderLabel(settings)}`;
  const errorMessage = analyzeMutation.isError ? (analyzeMutation.error instanceof Error ? analyzeMutation.error.message : String(analyzeMutation.error)) : '';

  async function handleFile(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    const text = await file.text();
    analyzeMutation.mutate({ mode: 'file_import', rawText: text, sourceTitle: file.name });
    event.currentTarget.value = '';
  }

  return (
    <main className="treeo-shell w-[420px] overflow-hidden">
      <div className="stagger min-h-[560px] p-5" style={{ ['--stagger-step' as string]: '40ms' } as React.CSSProperties}>
        <header style={{ ['--index' as string]: 0 } as React.CSSProperties} className="flex items-start justify-between gap-3">
          <LogoLockup compact />
          <div className="flex gap-2">
            <IconButton label="Open dashboard" onClick={() => void openSidePanelFromPopup()}>
              <PanelRightOpen size={17} />
            </IconButton>
            <IconButton label="Settings" onClick={() => chrome.runtime.openOptionsPage()}>
              <Settings size={17} />
            </IconButton>
          </div>
        </header>

        <section style={{ ['--index' as string]: 1 } as React.CSSProperties} className="mt-6">
          <Badge tone="teal">{llmLabel}</Badge>
          <h1 className="mt-3 text-xl font-semibold tracking-tight">Evidence-linked startup alpha.</h1>
          <p className="mt-2 text-sm leading-snug text-[var(--muted)]">
            Capture only what you choose. Treeo scores founder proof, stage, public signal, fit, and urgency from the captured evidence.
          </p>
        </section>

        {isLinkedInLike ? (
          <div style={{ ['--index' as string]: 2 } as React.CSSProperties} className="mt-4 rounded-md border border-amber-400/35 bg-amber-400/10 p-3 text-xs leading-5 text-amber-800 dark:text-amber-200">
            LinkedIn detected. The capture is cleaned client-side before any analysis. Visible-page captures only.
          </div>
        ) : null}

        <section style={{ ['--index' as string]: 3 } as React.CSSProperties} className="mt-5 grid gap-2">
          {settings?.engineEnabled ? (
            <label className="flex items-center justify-between gap-3 rounded-md border border-[var(--line)] px-3 py-2">
              <span>
                <span className="block text-sm font-semibold">Private page</span>
                <span className="block text-xs leading-5 text-[var(--muted)]">Email or internal doc. The engine only sees a redacted fragment.</span>
              </span>
              <RadixSwitch.Root checked={isPrivate} onCheckedChange={setPrivateChoice} className="relative h-6 w-11 shrink-0 rounded-full bg-[var(--line-strong)] data-[state=checked]:bg-[var(--accent)]">
                <RadixSwitch.Thumb className="block h-5 w-5 translate-x-0.5 rounded-full bg-white shadow transition data-[state=checked]:translate-x-[22px]" />
              </RadixSwitch.Root>
            </label>
          ) : null}
          <CaptureButton mode="visible_page" label="Analyze visible page" pending={analyzeMutation.isPending} onClick={(mode) => analyzeMutation.mutate({ mode })} icon={<Sparkles size={16} />} />
          <CaptureButton mode="selected_text" label="Analyze selected text" pending={analyzeMutation.isPending} onClick={(mode) => analyzeMutation.mutate({ mode })} icon={<Scissors size={16} />} />
          <Button variant="ghost" className="w-full justify-start" disabled={analyzeMutation.isPending} onClick={() => setPasteOpen((open) => !open)}>
            <TextCursorInput size={16} />
            Paste profile text
          </Button>
          <Button variant="ghost" className="w-full justify-start" disabled={analyzeMutation.isPending} onClick={() => fileInputRef.current?.click()}>
            <FileUp size={16} />
            Import CSV or JSON
          </Button>
          <input ref={fileInputRef} type="file" accept=".csv,.json,text/csv,application/json" className="hidden" onChange={(event) => void handleFile(event)} />
        </section>

        <div style={{ ['--index' as string]: 4 } as React.CSSProperties} className="mt-4 grid gap-2">
          <ProgressStrip visible={analyzeMutation.isPending} />
          {errorMessage ? (
            <Toast tone="error" action={lastRequest ? <Button variant="ghost" onClick={() => analyzeMutation.mutate(lastRequest)}>Retry</Button> : null}>
              {errorMessage}
            </Toast>
          ) : null}
        </div>

        {pasteOpen ? (
          <Card className="mt-4 p-4" style={{ ['--index' as string]: 5 } as React.CSSProperties}>
            <Textarea
              className="min-h-32 w-full"
              value={pasteText}
              onChange={(event) => setPasteText(event.target.value)}
              placeholder="Paste a LinkedIn profile, a company blurb, a HN launch post, or an analyst note. LinkedIn dumps are cleaned automatically."
            />
            <Button className="mt-3 w-full" disabled={analyzeMutation.isPending || !pasteText.trim()} onClick={() => analyzeMutation.mutate({ mode: 'manual_paste', rawText: pasteText, sourceTitle: 'Manual paste' })}>
              {analyzeMutation.isPending ? <RefreshCcw className="animate-spin" size={16} /> : <Sparkles size={16} />}
              Analyze pasted text
            </Button>
          </Card>
        ) : null}

        <section style={{ ['--index' as string]: 6 } as React.CSSProperties} className="mt-5">
          {deal ? (
            <DealSlip deal={deal} llmLabel={llmLabel} onOpenDashboard={() => void openSidePanelFromPopup()} />
          ) : (
            <div className="rounded-md border border-dashed border-[var(--line-strong)] p-6 text-center text-sm leading-relaxed text-[var(--muted)]">
              Capture a profile to begin. {settings?.localOnlyMode ? 'Mock analysis runs offline; switch to a real provider in Settings.' : 'Real LLM provider is enabled.'}
            </div>
          )}
        </section>
      </div>
    </main>
  );
}

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <PopupApp />
    </QueryClientProvider>
  </React.StrictMode>,
);
