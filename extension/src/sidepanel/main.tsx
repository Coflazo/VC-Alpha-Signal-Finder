import { QueryClient, QueryClientProvider, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Background, Controls, MarkerType, ReactFlow, type Edge, type Node } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import {
  AlertTriangle,
  Brain,
  Compass,
  Download,
  ExternalLink,
  FileJson,
  FileText,
  GitBranch,
  Network,
  RefreshCcw,
  Search,
  Settings,
  Sparkles,
  Sun,
  Table2,
} from 'lucide-react';
import React from 'react';
import { createRoot } from 'react-dom/client';
import '../styles/globals.css';
import { buildCsvExports } from '../export/csvExport';
import { buildHtmlGraphExport } from '../export/htmlGraphExport';
import { buildJsonExport } from '../export/jsonExport';
import { buildMemoHtml, buildMemoMarkdown } from '../export/memoExport';
import { buildXlsxExport } from '../export/xlsxExport';
import { buildFounderGraph } from '../graph/graphBuilder';
import { exportGraphJson, exportGraphSvg } from '../graph/exportGraph';
import { CommandPalette, type Command } from '../components/CommandPalette';
import { EvidencePopover } from '../components/EvidencePopover';
import { RunInspector } from '../components/RunInspector';
import { ScoreBreakdown } from '../components/ScoreBreakdown';
import { applyTheme, getDeals, getLastDeal, getSettings, updateDeal } from '../lib/storage';
import type { CaptureMode, Evidence, GraphNode, GraphNodeType, ProviderName, RuntimeMessage, TreeoDeal, TreeoSettings } from '../lib/types';
import { nowIso, truncateMiddle } from '../lib/utils';
import { Badge, Button, Card, IconButton, LogoLockup, Metric, Recommendation, ScoreRing, Skeleton, Textarea, Toast, recommendationLabel } from '../components/ui';

const queryClient = new QueryClient();

const SECTIONS: Array<{ id: string; label: string }> = [
  { id: 'investment-read', label: 'Investment read' },
  { id: 'score-math', label: 'Score math' },
  { id: 'founder', label: 'Founder' },
  { id: 'startup', label: 'Startup' },
  { id: 'technical', label: 'Technical' },
  { id: 'public', label: 'Public signal' },
  { id: 'risk', label: 'Risk' },
  { id: 'evidence', label: 'Evidence' },
  { id: 'graph', label: 'Graph' },
  { id: 'exports', label: 'Exports' },
  { id: 'notes', label: 'Notes' },
];

function sendAnalyze(mode: CaptureMode = 'visible_page', rawText?: string): Promise<TreeoDeal> {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendMessage({
      type: 'TREEO_ANALYZE_CURRENT',
      payload: { mode, rawText },
    } satisfies RuntimeMessage, (response) => {
      if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
      else if (!response?.ok) reject(new Error(response?.error ?? 'Analysis failed'));
      else resolve(response.deal as TreeoDeal);
    });
  });
}

function downloadBlob(filename: string, blob: Blob): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

function downloadText(filename: string, text: string, type = 'text/plain'): void {
  downloadBlob(filename, new Blob([text], { type }));
}

function slug(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 48) || 'treeo-export';
}

function useBootTheme() {
  const [theme, setTheme] = React.useState<'system' | 'light' | 'dark'>('system');
  React.useEffect(() => {
    getSettings().then((settings) => {
      applyTheme(settings.theme);
      setTheme(settings.theme);
    }).catch(() => undefined);
  }, []);
  return {
    theme,
    toggle: () => {
      const next = theme === 'dark' ? 'light' : 'dark';
      applyTheme(next);
      setTheme(next);
    },
  };
}

function EmptyState({ working, onAnalyze }: { working: boolean; onAnalyze: () => void }) {
  return (
    <div className="grid place-items-center rounded-md border border-dashed border-[var(--line-strong)] p-8 text-center">
      <div className="grid h-12 w-12 place-items-center rounded-md bg-[var(--surface-strong)] text-[var(--accent)]"><Sparkles size={22} /></div>
      <h2 className="mt-4 text-lg font-semibold">No analysis selected</h2>
      <p className="mt-2 max-w-md text-sm leading-6 text-[var(--muted)]">Analyze a visible page or paste founder text from the popup to start a local evidence graph.</p>
      <Button className="mt-4" disabled={working} onClick={onAnalyze}>
        {working ? <RefreshCcw className="animate-spin" size={16} /> : <Sparkles size={16} />}
        Analyze visible page
      </Button>
    </div>
  );
}

function DealRail({ deals, activeId, onSelect }: { deals: TreeoDeal[]; activeId?: string; onSelect: (deal: TreeoDeal) => void }) {
  return (
    <aside className="h-[calc(100vh-112px)] overflow-auto rounded-md border border-[var(--line)] bg-[var(--surface)] p-2">
      <div className="mb-2 px-2 text-xs font-semibold uppercase tracking-[0.14em] text-[var(--muted)]">Watchlist</div>
      <div className="space-y-1">
        {deals.map((deal) => {
          const isActive = activeId === deal.id;
          return (
            <button
              key={deal.id}
              className={`focus-ring w-full rounded-md px-3 py-2 text-left text-sm transition ${isActive ? 'bg-[var(--accent-soft)] text-[var(--text)] ring-1 ring-[var(--accent)]' : 'text-[var(--muted)] hover:bg-[var(--surface-strong)] hover:text-[var(--text)]'}`}
              onClick={() => onSelect(deal)}
              aria-pressed={isActive}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="truncate font-semibold">{deal.profile.name || 'Unknown founder'}</span>
                <span className="data-font text-xs">{deal.score.total}</span>
              </div>
              <div className="mt-1 truncate text-xs">{deal.profile.companyName || deal.score.stageEstimate.stage}</div>
            </button>
          );
        })}
      </div>
    </aside>
  );
}

function AnchorNav({ activeId, onJump }: { activeId: string; onJump: (id: string) => void }) {
  return (
    <nav aria-label="Deal sections" className="sticky top-4 hidden h-[calc(100vh-160px)] overflow-auto rounded-md border border-[var(--line)] bg-[var(--surface)] p-2 xl:block">
      <div className="px-2 pb-2 text-xs font-semibold uppercase tracking-[0.14em] text-[var(--muted)]">On this deal</div>
      <ul className="grid gap-0.5">
        {SECTIONS.map((section) => (
          <li key={section.id}>
            <button
              type="button"
              onClick={() => onJump(section.id)}
              className={`focus-ring w-full rounded-md px-3 py-1.5 text-left text-xs transition ${activeId === section.id ? 'bg-[var(--accent-soft)] text-[var(--accent)]' : 'text-[var(--muted)] hover:bg-[var(--surface-strong)] hover:text-[var(--text)]'}`}
            >
              {section.label}
            </button>
          </li>
        ))}
      </ul>
    </nav>
  );
}

function StickyHeader({ deal, llmLabel }: { deal: TreeoDeal; llmLabel: string }) {
  const supportingEvidence = deal.evidence.slice(0, 8);
  return (
    <Card className="sticky top-2 z-10 grid gap-5 p-6 backdrop-blur">
      {/* Asymmetric header: score ring left, identity flows right. No tile
          row underneath — the stats line uses hairline dividers instead. */}
      <div className="grid gap-5 lg:grid-cols-[auto_1fr_auto] lg:items-start">
        <ScoreRing score={deal.score.total} confidence={deal.score.confidence} size={104} />
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <Recommendation value={String(deal.score.recommendation)} />
            <Badge tone="teal">{String(deal.score.stageEstimate.stage).replace(/_/g, ' ')}</Badge>
            {deal.score.version === 'v1' ? <Badge tone="warn">v1 scoring</Badge> : null}
            <Badge tone="neutral">{llmLabel}</Badge>
          </div>
          <h2 className="mt-3 text-display font-semibold tracking-tight">{deal.profile.name || 'Unknown founder'}</h2>
          <p className="mt-1 text-sm leading-snug text-[var(--muted)]">
            {deal.profile.headline || (deal.profile.companyName ? deal.profile.companyName : 'No headline extracted')}
            {deal.profile.location ? ` · ${deal.profile.location}` : ''}
          </p>
          <p className="mt-3 max-w-[65ch] text-sm leading-relaxed">{deal.memo?.thirtySecondSummary || deal.score.summary}</p>
        </div>
        <div className="flex gap-2 lg:flex-col lg:items-end">
          <EvidencePopover
            evidence={supportingEvidence}
            trigger={<span className="text-xs underline-offset-2 hover:underline">{supportingEvidence.length} evidence ↗</span>}
          />
          <RunInspector dealId={deal.id} />
        </div>
      </div>

      <div className="grid grid-cols-4 divide-x divide-[var(--line)] border-y border-[var(--line)] py-3 text-center">
        <div>
          <div className="data-font text-base font-semibold">{deal.score.total}</div>
          <div className="mt-0.5 text-[10px] uppercase tracking-[0.16em] text-[var(--muted)]">Total</div>
        </div>
        <div>
          <div className="data-font text-base font-semibold">{Math.round(deal.score.confidence * 100)}%</div>
          <div className="mt-0.5 text-[10px] uppercase tracking-[0.16em] text-[var(--muted)]">Confidence</div>
        </div>
        <div>
          <div className="data-font text-base font-semibold">{deal.score.founderLikelihoodScore}</div>
          <div className="mt-0.5 text-[10px] uppercase tracking-[0.16em] text-[var(--muted)]">Founder</div>
        </div>
        <div>
          <div className="data-font text-base font-semibold">{deal.score.redFlagRisk}</div>
          <div className="mt-0.5 text-[10px] uppercase tracking-[0.16em] text-[var(--muted)]">Risk</div>
        </div>
      </div>

      <p className="text-xs leading-relaxed text-[var(--muted)]">
        <span className="font-semibold text-[var(--text)]">Next:</span> {deal.score.nextAction}
      </p>
    </Card>
  );
}

function Section({ id, title, children, action }: { id: string; title: string; children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <section id={id} className="scroll-mt-24 grid gap-3">
      <header className="flex items-center justify-between gap-3">
        <h3 className="text-lg font-semibold">{title}</h3>
        {action}
      </header>
      {children}
    </section>
  );
}

/**
 * Layered graph layout. Each node type gets its own column; nodes are
 * distributed vertically by index inside the column. xyflow's `fitView` then
 * scales it to the visible area. Replaces the hardcoded circular layout that
 * collapsed for graphs over ~50 nodes.
 */
function layoutNodes(nodes: GraphNode[]): Record<string, { x: number; y: number }> {
  const columns: Record<string, GraphNode[]> = {
    left: [],
    center: [],
    right: [],
    farRight: [],
  };
  for (const node of nodes) {
    const col = (() => {
      if (node.type === 'founder' || node.type === 'company' || node.type === 'cofounder') return 'center';
      if (node.type === 'hn_story' || node.type === 'hn_comment' || node.type === 'producthunt_launch') return 'left';
      if (node.type === 'github_repo' || node.type === 'yc_rfs_topic' || node.type === 'market' || node.type === 'competitor') return 'right';
      return 'farRight';
    })();
    columns[col].push(node);
  }
  const xByCol: Record<string, number> = { left: 0, center: 320, right: 640, farRight: 960 };
  const positions: Record<string, { x: number; y: number }> = {};
  for (const [col, items] of Object.entries(columns)) {
    items.forEach((node, index) => {
      positions[node.id] = { x: xByCol[col], y: 80 * index };
    });
  }
  return positions;
}

function GraphMap({ deal }: { deal: TreeoDeal }) {
  const graph = deal.graph ?? buildFounderGraph(deal);
  const [selectedTypes, setSelectedTypes] = React.useState<Set<GraphNodeType>>(new Set());
  const visibleNodes = selectedTypes.size ? graph.nodes.filter((node) => selectedTypes.has(node.type)) : graph.nodes;
  const visibleIds = new Set(visibleNodes.map((node) => node.id));
  const positions = React.useMemo(() => layoutNodes(visibleNodes), [visibleNodes]);
  const nodes = React.useMemo<Node[]>(() => visibleNodes.map((node) => {
    const isFounder = node.type === 'founder';
    const isRisk = node.type === 'risk';
    return {
      id: node.id,
      position: positions[node.id] ?? { x: 0, y: 0 },
      data: { label: node.label },
      style: {
        border: '1px solid var(--line-strong)',
        borderRadius: 8,
        background: isFounder ? 'var(--accent-soft)' : isRisk ? '#FEF3C7' : 'var(--surface-strong)',
        color: isFounder ? 'var(--accent-strong)' : 'var(--text)',
        padding: 10,
        minWidth: isFounder ? 160 : 120,
        fontSize: 12,
        fontWeight: isFounder ? 600 : 400,
      },
    };
  }), [visibleNodes, positions]);
  const edges = React.useMemo<Edge[]>(() => graph.edges
    .filter((edge) => visibleIds.has(edge.source) && visibleIds.has(edge.target))
    .map((edge) => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      label: edge.label ?? edge.type.replace(/_/g, ' '),
      type: 'smoothstep',
      markerEnd: { type: MarkerType.ArrowClosed },
      style: { strokeWidth: Math.max(1, edge.confidence * 2.5) },
    })), [graph.edges, visibleIds]);
  const types = [...new Set(graph.nodes.map((node) => node.type))];

  return (
    <div className="grid gap-4 lg:grid-cols-[220px_1fr]">
      <Card>
        <h4 className="text-sm font-semibold">Filters</h4>
        <div className="mt-3 grid gap-2">
          {types.map((type) => (
            <button
              key={type}
              className={`focus-ring rounded-md border px-3 py-1.5 text-left text-xs ${selectedTypes.has(type) ? 'border-[var(--accent)] bg-[var(--accent-soft)] text-[var(--accent-strong)]' : 'border-[var(--line)] text-[var(--muted)]'}`}
              onClick={() => setSelectedTypes((current) => {
                const next = new Set(current);
                if (next.has(type)) next.delete(type);
                else next.add(type);
                return next;
              })}
              aria-pressed={selectedTypes.has(type)}
            >
              {type.replace(/_/g, ' ')}
            </button>
          ))}
          <Button variant="ghost" onClick={() => setSelectedTypes(new Set())}>Clear filters</Button>
        </div>
        <div className="mt-4 text-xs leading-5 text-[var(--muted)]">
          Legend: founder is accent-tinted, risk is amber, everything else uses the neutral surface. Width of an edge encodes its
          confidence. Drag nodes to rearrange; layout is layered so it scales beyond 50 nodes.
        </div>
      </Card>
      <Card className="p-0" style={{ height: 'min(720px, 70vh)' }}>
        <ReactFlow nodes={nodes} edges={edges} fitView>
          <Background />
          <Controls />
        </ReactFlow>
      </Card>
    </div>
  );
}

function EvidenceLedger({ deal }: { deal: TreeoDeal }) {
  return (
    <Card>
      <div className="overflow-x-auto rounded-md border border-[var(--line)]">
        <table className="w-full min-w-[640px] text-sm">
          <thead className="bg-[var(--surface-strong)] text-xs uppercase tracking-[0.12em] text-[var(--muted)]">
            <tr>
              <th className="px-3 py-3 text-left">Field</th>
              <th className="px-3 py-3 text-left">Quote</th>
              <th className="px-3 py-3 text-left">Source</th>
              <th className="px-3 py-3 text-left">Reliability</th>
            </tr>
          </thead>
          <tbody>
            {deal.evidence.map((item) => (
              <tr key={item.id} className="border-t border-[var(--line)] align-top">
                <td id={`evidence-${item.id}`} className="px-3 py-3 font-semibold">{item.fieldPath}</td>
                <td className="px-3 py-3 text-[var(--muted)]">{item.quote}</td>
                <td className="px-3 py-3">{item.sourceUrl ? <a href={item.sourceUrl} target="_blank" rel="noreferrer" className="text-[var(--accent)]">{truncateMiddle(item.sourceUrl, 42)}</a> : item.sourceType}</td>
                <td className="px-3 py-3">{item.reliability}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function Exports({ deal, deals }: { deal: TreeoDeal; deals: TreeoDeal[] }) {
  const base = slug(deal.profile.name || 'founder');
  return (
    <Card>
      <p className="text-sm leading-6 text-[var(--muted)]">Preview what leaves the browser: deal data, evidence quotes, graph nodes, and memo text are generated from local IndexedDB records.</p>
      <div className="mt-5 grid gap-2 md:grid-cols-2 lg:grid-cols-3">
        <Button variant="ghost" onClick={() => downloadText(`${base}.json`, buildJsonExport([deal]), 'application/json')}><FileJson size={16} /> Deal JSON</Button>
        <Button variant="ghost" onClick={() => {
          void buildXlsxExport(deals).then((blob) => downloadBlob('treeo-workbook.xlsx', blob));
        }}><Table2 size={16} /> XLSX workbook</Button>
        <Button variant="ghost" onClick={() => {
          const csv = buildCsvExports(deals);
          Object.entries(csv).forEach(([name, value]) => downloadText(`${name}.csv`, value, 'text/csv'));
        }}><Download size={16} /> CSV bundle</Button>
        <Button variant="ghost" onClick={() => downloadText(`${base}-memo.md`, buildMemoMarkdown(deal), 'text/markdown')}><FileText size={16} /> Memo MD</Button>
        <Button variant="ghost" onClick={() => downloadText(`${base}-memo.html`, buildMemoHtml(deal), 'text/html')}><FileText size={16} /> Memo HTML</Button>
        <Button variant="ghost" onClick={() => downloadText(`${base}-graph.json`, exportGraphJson(deal.graph ?? buildFounderGraph(deal)), 'application/json')}><Network size={16} /> Graph JSON</Button>
        <Button variant="ghost" onClick={() => downloadText(`${base}-graph.svg`, exportGraphSvg(deal.graph ?? buildFounderGraph(deal)), 'image/svg+xml')}><GitBranch size={16} /> Graph SVG</Button>
        <Button variant="ghost" onClick={() => downloadText(`${base}-graph.html`, buildHtmlGraphExport(deal), 'text/html')}><Network size={16} /> Graph HTML</Button>
      </div>
    </Card>
  );
}

function NotesEditor({ deal, onSave }: { deal: TreeoDeal; onSave: (deal: TreeoDeal) => Promise<void> }) {
  const [notes, setNotes] = React.useState(deal.notes);
  const [savedAt, setSavedAt] = React.useState<number | null>(null);
  const dirty = notes !== deal.notes;
  React.useEffect(() => setNotes(deal.notes), [deal.id, deal.notes]);
  return (
    <Card>
      <Textarea className="min-h-40 w-full" value={notes} onChange={(event) => setNotes(event.target.value)} placeholder="Add diligence notes, contradiction checks, outreach angle, or first-call context." />
      <div className="mt-3 flex items-center justify-between text-xs text-[var(--muted)]">
        <span>{dirty ? 'Unsaved changes' : savedAt ? 'Saved' : 'Up to date'}</span>
        <Button onClick={() => void onSave({ ...deal, notes, updatedAt: nowIso() }).then(() => setSavedAt(Date.now()))} disabled={!dirty}>
          Save notes
        </Button>
      </div>
      {deal.score.risks.length ? (
        <div className="mt-5 space-y-2">
          {deal.score.risks.map((risk) => (
            <div key={risk} className="flex gap-2 rounded-md border border-amber-400/30 bg-amber-400/10 p-3 text-sm text-amber-800 dark:text-amber-200">
              <AlertTriangle size={16} className="mt-0.5 shrink-0" /> {risk}
            </div>
          ))}
        </div>
      ) : null}
    </Card>
  );
}

function CommandCenter() {
  const { toggle: toggleTheme } = useBootTheme();
  const qc = useQueryClient();
  const settingsQuery = useQuery({ queryKey: ['settings'], queryFn: getSettings });
  const dealsQuery = useQuery({ queryKey: ['deals'], queryFn: getDeals, refetchInterval: 4000 });
  const lastDealQuery = useQuery({ queryKey: ['lastDeal'], queryFn: getLastDeal, refetchInterval: 4000 });
  const [selected, setSelected] = React.useState<TreeoDeal | null>(null);
  const [error, setError] = React.useState('');
  const [activeAnchor, setActiveAnchor] = React.useState('investment-read');
  const deals = dealsQuery.data ?? [];
  const active = selected ?? lastDealQuery.data ?? deals[0] ?? null;
  const settings: TreeoSettings = settingsQuery.data ?? null as unknown as TreeoSettings;
  const llmLabel = React.useMemo(() => {
    if (!settings) return 'LLM: loading';
    if (settings.localOnlyMode) return 'LLM: mock · offline';
    if (!settings.llmDisclosureAccepted) return 'LLM: mock · disclosure off';
    const enabled = (settings.providerOrder as ProviderName[]).find((name) => settings.providers[name]?.enabled && name !== 'mock');
    if (!enabled) return 'LLM: mock · no provider enabled';
    return `LLM: ${enabled} · ${settings.providers[enabled].model ?? 'default'}`;
  }, [settings]);

  const analyze = useMutation({
    mutationFn: () => sendAnalyze('visible_page'),
    onMutate: () => setError(''),
    onSuccess: async (deal) => {
      setSelected(deal);
      await qc.invalidateQueries({ queryKey: ['deals'] });
      await qc.invalidateQueries({ queryKey: ['lastDeal'] });
    },
    onError: (err) => setError(err instanceof Error ? err.message : String(err)),
  });

  async function saveDealNotes(next: TreeoDeal) {
    await updateDeal(next);
    setSelected(next);
    await qc.invalidateQueries({ queryKey: ['deals'] });
    await qc.invalidateQueries({ queryKey: ['lastDeal'] });
  }

  React.useEffect(() => {
    function onScroll() {
      const offset = window.scrollY + 120;
      for (const section of SECTIONS) {
        const el = document.getElementById(section.id);
        if (!el) continue;
        if (el.offsetTop <= offset && el.offsetTop + el.offsetHeight > offset) {
          setActiveAnchor(section.id);
          return;
        }
      }
    }
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  const stats = React.useMemo(() => {
    const urgent = deals.filter((deal) => deal.score.recommendation === 'immediate_outreach' || deal.score.outreachUrgency >= 70).length;
    const average = deals.length ? Math.round(deals.reduce((sum, deal) => sum + deal.score.total, 0) / deals.length) : 0;
    return { total: deals.length, urgent, average, evidence: deals.reduce((sum, deal) => sum + deal.evidence.length, 0) };
  }, [deals]);

  const commands: Command[] = React.useMemo(() => {
    const base: Command[] = [
      { id: 'analyze', label: 'Analyze visible page', hint: '⌘K', run: () => analyze.mutate() },
      { id: 'settings', label: 'Open settings', run: () => chrome.runtime.openOptionsPage() },
      { id: 'theme', label: 'Toggle theme', run: () => toggleTheme() },
    ];
    if (active) {
      base.push({
        id: 'memo-md',
        label: 'Export memo MD',
        run: () => downloadText(`${slug(active.profile.name || 'founder')}-memo.md`, buildMemoMarkdown(active), 'text/markdown'),
      });
    }
    return base.concat(
      deals.slice(0, 12).map((deal) => ({
        id: `deal-${deal.id}`,
        label: `Switch to ${deal.profile.name || 'unknown founder'}`,
        hint: `total ${deal.score.total}`,
        run: () => setSelected(deal),
      })),
    );
  }, [active, deals, analyze, toggleTheme]);

  function jumpTo(id: string) {
    const el = document.getElementById(id);
    if (!el) return;
    el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    setActiveAnchor(id);
  }

  return (
    <main className="treeo-shell min-h-screen p-4">
      <CommandPalette commands={commands} />

      <header className="flex items-center justify-between gap-4">
        <LogoLockup />
        <div className="flex gap-2">
          <IconButton label="Analyze visible page" onClick={() => analyze.mutate()}>
            {analyze.isPending ? <RefreshCcw className="animate-spin" size={17} /> : <Sparkles size={17} />}
          </IconButton>
          <IconButton label="Export all JSON" onClick={() => downloadText('treeo-vc-scout.json', buildJsonExport(deals), 'application/json')}>
            <Download size={17} />
          </IconButton>
          <IconButton label="Toggle theme" onClick={() => toggleTheme()}>
            <Sun size={17} />
          </IconButton>
          <IconButton label="Settings" onClick={() => chrome.runtime.openOptionsPage()}>
            <Settings size={17} />
          </IconButton>
        </div>
      </header>

      <section className="mt-5 grid grid-cols-4 gap-3">
        <Metric label="Deals" value={stats.total} detail="local database" />
        <Metric label="Urgent" value={stats.urgent} detail="reach-out signals" />
        <Metric label="Avg score" value={stats.average} detail="portfolio view" />
        <Metric label="Evidence" value={stats.evidence} detail="stored quotes" />
      </section>

      {error ? (
        <div className="mt-4">
          <Toast tone="error" action={<Button variant="ghost" onClick={() => analyze.mutate()}>Retry</Button>}>{error}</Toast>
        </div>
      ) : null}

      {analyze.isPending ? (
        <div className="mt-4">
          <Toast tone="neutral">Running multi-pass analysis — keep the popup open until done.</Toast>
        </div>
      ) : null}

      <div className="mt-5 grid grid-cols-[240px_1fr] gap-4 xl:grid-cols-[240px_1fr_200px]">
        <DealRail deals={deals} activeId={active?.id} onSelect={setSelected} />
        {!active ? (
          <EmptyState working={analyze.isPending} onAnalyze={() => analyze.mutate()} />
        ) : settings ? (
          <div className="stagger grid gap-5" style={{ ['--stagger-step' as string]: '60ms' } as React.CSSProperties}>
            <StickyHeader deal={active} llmLabel={llmLabel} />

            <Section id="investment-read" title="Investment read" action={<Badge tone="teal"><Compass size={11} className="mr-1" /> {recommendationLabel(active.score.recommendation)}</Badge>}>
              <Card>
                <p className="text-sm leading-6">{active.memo?.thirtySecondSummary || active.score.summary}</p>
                <div className="mt-4 grid gap-3 md:grid-cols-3">
                  <Metric label="HN nodes" value={(active.hnStories?.length ?? 0) + (active.hnComments?.length ?? 0)} />
                  <Metric label="GitHub repos" value={active.githubRepos?.length ?? 0} />
                  <Metric label="YC fits" value={active.ycSignals?.length ?? 0} />
                </div>
                <p className="mt-4 text-xs leading-5 text-[var(--muted)]">
                  Next action: <span className="text-[var(--text)]">{active.score.nextAction}</span>
                </p>
              </Card>
            </Section>

            <Section id="score-math" title="Score math">
              <ScoreBreakdown deal={active} settings={settings} defaultOpen />
            </Section>

            <Section id="founder" title="Founder">
              <Card>
                <p className="text-sm leading-6 text-[var(--muted)]">Founder likelihood {active.score.founderLikelihoodScore} · label {recommendationLabel(active.score.founderLabel)}.</p>
                <div className="mt-4 grid gap-3 md:grid-cols-2">
                  {active.score.signals.map((signal) => (
                    <div key={`${signal.label}-${signal.evidence}`} className="rounded-md border border-[var(--line)] p-3">
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-semibold">{signal.label}</span>
                        <span className="data-font text-xs text-[var(--muted)]">{Math.round(signal.confidence * 100)}%</span>
                      </div>
                      <div className="mt-1 text-xs font-semibold text-[var(--accent)]">{signal.principle}</div>
                      <p className="mt-2 text-sm leading-5 text-[var(--muted)]">{signal.evidence}</p>
                      <EvidencePopover
                        evidence={evidenceFromIds(active.evidence, signal.evidenceIds ?? [])}
                        trigger={<span className="mt-2 inline-flex text-xs">View evidence ↗</span>}
                      />
                    </div>
                  ))}
                </div>
              </Card>
            </Section>

            <Section id="startup" title="Startup">
              <div className="grid gap-4 md:grid-cols-2">
                <Card>
                  <p className="text-sm leading-6 text-[var(--muted)]">{active.startupAnalysis?.companySummary || active.score.summary}</p>
                  <div className="mt-3 rounded-md border border-[var(--line)] p-3">
                    <div className="text-sm font-semibold">Product hypothesis</div>
                    <p className="mt-2 text-sm leading-6 text-[var(--muted)]">{active.startupAnalysis?.productHypothesis || 'unknown'}</p>
                  </div>
                </Card>
                <Card>
                  <div className="grid gap-3">
                    <Metric label="Stage" value={String(active.score.stageEstimate.stage).replace(/_/g, ' ')} detail={`${Math.round(active.score.stageEstimate.confidence * 100)}% confidence`} />
                    <Metric label="Traction" value={active.score.scorecard.traction} detail="0..10" />
                  </div>
                  <div className="mt-3 text-xs text-[var(--muted)]">Missing: {active.score.stageEstimate.missingEvidence.join(', ') || 'unknown'}</div>
                </Card>
              </div>
            </Section>

            <Section id="technical" title="Technical">
              <div className="grid gap-4 md:grid-cols-[1fr_320px]">
                <Card>
                  <p className="text-sm leading-6 text-[var(--muted)]">{active.technicalCredibility?.technicalDepth || 'Technical credibility is inferred from captured builder language and optional GitHub data.'}</p>
                  <div className="mt-4 grid gap-2">
                    {(active.technicalCredibility?.builderProof ?? active.score.signals.filter((s) => s.principle === 'Technical Credibility').map((s) => s.evidence)).map((item) => (
                      <div key={item} className="rounded-md border border-[var(--line)] p-3 text-sm text-[var(--muted)]">{item}</div>
                    ))}
                  </div>
                </Card>
                <Card>
                  <h4 className="text-sm font-semibold">GitHub radar</h4>
                  <div className="mt-3 space-y-2">
                    {(active.githubRepos ?? []).length ? active.githubRepos?.map((repo) => (
                      <a key={repo.id} className="block rounded-md border border-[var(--line)] p-3 text-sm hover:border-[var(--line-strong)]" href={repo.url} target="_blank" rel="noreferrer">
                        <div className="font-semibold">{repo.owner}/{repo.name}</div>
                        <div className="mt-1 text-xs text-[var(--muted)]">{repo.language} | {repo.stars} stars | docs {repo.docsDetected ? 'yes' : 'no'} | tests {repo.testDetected ? 'yes' : 'no'}</div>
                      </a>
                    )) : <p className="text-sm leading-6 text-[var(--muted)]">Enable public research to fetch GitHub repository signals.</p>}
                  </div>
                </Card>
              </div>
            </Section>

            <Section id="public" title="Public signal">
              <div className="grid gap-4 lg:grid-cols-3">
                <Card>
                  <h4 className="text-sm font-semibold">Hacker News</h4>
                  <p className="mt-2 text-xs leading-5 text-[var(--muted)]">{active.hnSignals?.founderHnCredibility || 'HN is treated as YC Hacker News: developer taste, launch proof, pain language, objections, and category heat.'}</p>
                  <div className="mt-3 space-y-2">
                    {(active.hnStories ?? []).slice(0, 8).map((story) => (
                      <a key={story.id} className="block rounded-md border border-[var(--line)] p-3 text-sm hover:border-[var(--line-strong)]" href={story.url} target="_blank" rel="noreferrer">
                        <div className="font-semibold">{story.title}</div>
                        <div className="mt-1 text-xs text-[var(--muted)]">{story.score} points | {story.commentCount} comments</div>
                      </a>
                    ))}
                  </div>
                </Card>
                <Card>
                  <h4 className="text-sm font-semibold">YC fit</h4>
                  <div className="mt-3 space-y-2">
                    {(active.ycSignals ?? []).length ? active.ycSignals?.map((signal) => (
                      <div key={signal.id} className="rounded-md border border-[var(--line)] p-3 text-sm">
                        <div className="flex items-center justify-between gap-2">
                          <span className="font-semibold">{signal.rfsTopic}</span>
                          <span className="data-font text-xs text-[var(--muted)]">{signal.fitScore}</span>
                        </div>
                        <p className="mt-2 text-[var(--muted)]">{signal.rationale}</p>
                      </div>
                    )) : <p className="text-sm leading-6 text-[var(--muted)]">No YC Requests for Startups keyword match was found in captured evidence.</p>}
                  </div>
                </Card>
                <Card>
                  <h4 className="text-sm font-semibold">Investor attention</h4>
                  <div className="mt-3 space-y-3 text-sm">
                    <div>
                      <div className="font-semibold">Possible investor interest, not confirmed approach</div>
                      <p className="mt-1 text-[var(--muted)]">{active.investorSignals?.possibleInvestorInterest.join(', ') || 'unknown'}</p>
                    </div>
                    <div>
                      <div className="font-semibold">Warm intro paths</div>
                      <p className="mt-1 text-[var(--muted)]">{active.investorSignals?.warmIntroPaths.join(', ') || 'unknown'}</p>
                    </div>
                    <div>
                      <div className="font-semibold">Fund thesis fit</div>
                      <p className="mt-1 text-[var(--muted)]">{active.investorSignals?.fundThesisFit || 'unknown'}</p>
                    </div>
                  </div>
                </Card>
              </div>
            </Section>

            <Section id="risk" title="Risk">
              <Card>
                <div className="grid gap-2 text-sm">
                  {active.score.risks.length ? active.score.risks.map((risk) => (
                    <div key={risk} className="flex gap-2 rounded-md border border-amber-400/30 bg-amber-400/10 p-3 text-amber-800 dark:text-amber-200">
                      <AlertTriangle size={16} className="mt-0.5 shrink-0" /> {risk}
                    </div>
                  )) : <p className="text-[var(--muted)]">No risk flags from deterministic scoring.</p>}
                </div>
                {active.riskAnalysis ? (
                  <div className="mt-4 grid gap-2 text-xs text-[var(--muted)]">
                    {active.riskAnalysis.overclaimingRisk ? <div><strong>Overclaiming risk:</strong> {active.riskAnalysis.overclaimingRisk}</div> : null}
                    {active.riskAnalysis.inconsistencies.length ? <div><strong>Inconsistencies:</strong> {active.riskAnalysis.inconsistencies.join(', ')}</div> : null}
                    {active.riskAnalysis.privacyWarnings.length ? <div><strong>Privacy warnings:</strong> {active.riskAnalysis.privacyWarnings.join(', ')}</div> : null}
                  </div>
                ) : null}
              </Card>
            </Section>

            <Section id="evidence" title="Evidence ledger" action={<Badge tone="neutral">{active.evidence.length} rows</Badge>}>
              <EvidenceLedger deal={active} />
            </Section>

            <Section id="graph" title="Relationship graph">
              <GraphMap deal={active} />
            </Section>

            <Section id="exports" title="Exports">
              <Exports deal={active} deals={deals} />
            </Section>

            <Section id="notes" title="Analyst notes">
              <NotesEditor deal={active} onSave={saveDealNotes} />
            </Section>
          </div>
        ) : (
          <div className="grid gap-3">
            <Skeleton className="h-32 w-full" />
            <Skeleton className="h-24 w-full" />
            <Skeleton className="h-24 w-full" />
          </div>
        )}
        <AnchorNav activeId={activeAnchor} onJump={jumpTo} />
      </div>
    </main>
  );
}

function evidenceFromIds(evidence: Evidence[], ids: string[]): Evidence[] {
  if (!ids.length) return [];
  const map = new Map(evidence.map((item) => [item.id, item] as const));
  return ids.map((id) => map.get(id)).filter((item): item is Evidence => Boolean(item));
}

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <CommandCenter />
    </QueryClientProvider>
  </React.StrictMode>,
);
