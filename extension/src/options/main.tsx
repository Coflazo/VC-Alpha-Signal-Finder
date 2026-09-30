import * as Select from '@radix-ui/react-select';
import * as Slider from '@radix-ui/react-slider';
import * as Switch from '@radix-ui/react-switch';
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query';
import { Check, ChevronDown, Database, KeyRound, ShieldCheck, Trash2 } from 'lucide-react';
import React from 'react';
import { createRoot } from 'react-dom/client';
import { z } from 'zod';
import '../styles/globals.css';
import { Badge, Button, Card, Input, LogoLockup, Textarea } from '../components/ui';
import { DEFAULT_SETTINGS, applyTheme, deleteAllLocalData, getSettings, saveSettings } from '../lib/storage';
import type { ProviderName, ThemeMode, TreeoSettings } from '../lib/types';

const queryClient = new QueryClient();
const PROVIDERS: ProviderName[] = ['mock', 'groq', 'gemini', 'openrouter', 'localhost'];

function listText(values: string[]): string {
  return values.join(', ');
}

function parseList(value: string): string[] {
  return value.split(',').map((item) => item.trim()).filter(Boolean);
}

/**
 * Zod schema that enforces field-level constraints. Used by the options page
 * to render inline errors and to refuse to persist invalid settings — the
 * old form silently saved comma-split junk.
 */
const SettingsSchema = z.object({
  retentionDays: z.number().int().min(1).max(3650),
  minScoreForReview: z.number().int().min(40).max(95),
  aiEndpoint: z.string().url().or(z.literal('')),
  fundProfile: z.object({
    fundName: z.string().min(1, 'Fund name is required'),
    checkSize: z.string().min(1, 'Check size is required'),
    geographyFocus: z.array(z.string()).min(1, 'At least one geography'),
    sectorThesis: z.array(z.string()).min(1, 'At least one sector'),
    outreachStyle: z.string().min(1, 'Outreach style is required'),
  }),
});

type FieldErrors = Partial<Record<'retentionDays' | 'minScoreForReview' | 'aiEndpoint' | 'fundName' | 'checkSize' | 'geographyFocus' | 'sectorThesis' | 'outreachStyle', string>>;

function validate(settings: TreeoSettings): FieldErrors {
  const result = SettingsSchema.safeParse({
    retentionDays: settings.retentionDays,
    minScoreForReview: settings.minScoreForReview,
    aiEndpoint: settings.aiEndpoint,
    fundProfile: {
      fundName: settings.fundProfile.fundName,
      checkSize: settings.fundProfile.checkSize,
      geographyFocus: settings.fundProfile.geographyFocus,
      sectorThesis: settings.fundProfile.sectorThesis,
      outreachStyle: settings.fundProfile.outreachStyle,
    },
  });
  if (result.success) return {};
  const errors: FieldErrors = {};
  for (const issue of result.error.issues) {
    const path = issue.path.join('.');
    if (path === 'retentionDays') errors.retentionDays = issue.message;
    if (path === 'minScoreForReview') errors.minScoreForReview = issue.message;
    if (path === 'aiEndpoint') errors.aiEndpoint = 'Provide a full URL or leave blank.';
    if (path === 'fundProfile.fundName') errors.fundName = issue.message;
    if (path === 'fundProfile.checkSize') errors.checkSize = issue.message;
    if (path === 'fundProfile.geographyFocus') errors.geographyFocus = issue.message;
    if (path === 'fundProfile.sectorThesis') errors.sectorThesis = issue.message;
    if (path === 'fundProfile.outreachStyle') errors.outreachStyle = issue.message;
  }
  return errors;
}

function Toggle({ checked, onCheckedChange, label, description }: { checked: boolean; onCheckedChange: (checked: boolean) => void; label: string; description: string }) {
  return (
    <div className="flex items-center justify-between gap-4 rounded-md border border-[var(--line)] p-4">
      <div>
        <div className="font-semibold">{label}</div>
        <p className="mt-1 text-sm leading-6 text-[var(--muted)]">{description}</p>
      </div>
      <Switch.Root checked={checked} onCheckedChange={onCheckedChange} className="relative h-6 w-11 shrink-0 rounded-full bg-[var(--line-strong)] data-[state=checked]:bg-[var(--accent)]">
        <Switch.Thumb className="block h-5 w-5 translate-x-0.5 rounded-full bg-white shadow transition data-[state=checked]:translate-x-[22px]" />
      </Switch.Root>
    </div>
  );
}

function ThemeSelect({ value, onChange }: { value: ThemeMode; onChange: (value: ThemeMode) => void }) {
  return (
    <Select.Root value={value} onValueChange={(next) => onChange(next as ThemeMode)}>
      <Select.Trigger className="focus-ring inline-flex h-10 min-w-36 items-center justify-between gap-2 rounded-md border border-[var(--line)] bg-[var(--surface-strong)] px-3 text-sm font-semibold">
        <Select.Value />
        <Select.Icon><ChevronDown size={16} /></Select.Icon>
      </Select.Trigger>
      <Select.Portal>
        <Select.Content className="z-50 overflow-hidden rounded-md border border-[var(--line)] bg-[var(--surface-strong)] shadow-panel">
          <Select.Viewport>
            {(['system', 'light', 'dark'] as ThemeMode[]).map((mode) => (
              <Select.Item key={mode} value={mode} className="flex cursor-pointer items-center gap-2 px-3 py-2 text-sm outline-none data-[highlighted]:bg-[var(--surface)]">
                <Select.ItemText>{mode}</Select.ItemText>
              </Select.Item>
            ))}
          </Select.Viewport>
        </Select.Content>
      </Select.Portal>
    </Select.Root>
  );
}

function WeightSlider({ label, value, onChange }: { label: string; value: number; onChange: (value: number) => void }) {
  return (
    <div className="rounded-md border border-[var(--line)] p-4">
      <div className="flex items-center justify-between text-sm font-semibold">
        <span>{label}</span>
        <span className="data-font text-[var(--muted)]">{Math.round(value * 100)}%</span>
      </div>
      <Slider.Root value={[value * 100]} max={60} min={5} step={1} onValueChange={([next]) => onChange(next / 100)} className="relative mt-4 flex h-5 touch-none items-center">
        <Slider.Track className="relative h-2 grow overflow-hidden rounded-full bg-[var(--line)]">
          <Slider.Range className="absolute h-full bg-[var(--accent)]" />
        </Slider.Track>
        <Slider.Thumb className="focus-ring block h-5 w-5 rounded-full border border-[var(--accent)] bg-white shadow-panel" />
      </Slider.Root>
    </div>
  );
}

function OptionsApp() {
  const settingsQuery = useQuery({ queryKey: ['settings'], queryFn: getSettings });
  const [settings, setSettings] = React.useState<TreeoSettings>(DEFAULT_SETTINGS);
  const [pristine, setPristine] = React.useState<TreeoSettings>(DEFAULT_SETTINGS);
  const [saved, setSaved] = React.useState(false);
  const [deleted, setDeleted] = React.useState(false);
  const errors = React.useMemo(() => validate(settings), [settings]);
  const isValid = Object.keys(errors).length === 0;
  const isDirty = JSON.stringify(settings) !== JSON.stringify(pristine);

  React.useEffect(() => {
    if (settingsQuery.data) {
      setSettings(settingsQuery.data);
      setPristine(settingsQuery.data);
      applyTheme(settingsQuery.data.theme);
    }
  }, [settingsQuery.data]);

  function update<K extends keyof TreeoSettings>(key: K, value: TreeoSettings[K]) {
    setSettings((current) => ({ ...current, [key]: value }));
  }

  function updateProvider(provider: ProviderName, patch: Partial<TreeoSettings['providers'][ProviderName]>) {
    setSettings((current) => ({
      ...current,
      providers: {
        ...current.providers,
        [provider]: {
          ...current.providers[provider],
          ...patch,
        },
      },
    }));
  }

  async function persist() {
    if (!isValid) return;
    await saveSettings(settings);
    applyTheme(settings.theme);
    setPristine(settings);
    setSaved(true);
    window.setTimeout(() => setSaved(false), 1800);
  }

  async function clearLocalData() {
    if (!window.confirm('Delete all locally stored deals, evidence, graphs, and exports? Settings are kept.')) return;
    await deleteAllLocalData();
    setDeleted(true);
    window.setTimeout(() => setDeleted(false), 1800);
  }

  return (
    <main className="treeo-shell min-h-screen px-5 py-6">
      <div className="mx-auto max-w-6xl">
        <header className="flex items-start justify-between gap-6">
          <div>
            <LogoLockup />
            <h1 className="mt-6 max-w-3xl text-4xl font-semibold">Treeo VC Scout settings</h1>
            <p className="mt-3 max-w-3xl text-base leading-7 text-[var(--muted)]">
              Configure the local-first founder intelligence workflow, provider routing, public research, and fund-fit model.
            </p>
          </div>
          <Badge tone="teal">Manifest V3</Badge>
        </header>

        <div className="mt-8 grid gap-5">
          <Card>
            <div className="mb-5 flex items-center justify-between gap-4">
              <div>
                <h2 className="text-xl font-semibold">Experience</h2>
                <p className="mt-1 text-sm text-[var(--muted)]">Theme, panel behavior, and analyst-controlled capture defaults.</p>
              </div>
              <ThemeSelect value={settings.theme} onChange={(theme) => update('theme', theme)} />
            </div>
            <div className="grid gap-3 md:grid-cols-2">
              <Toggle checked={settings.autoOpenSidePanel} onCheckedChange={(checked) => update('autoOpenSidePanel', checked)} label="Open dashboard after analysis" description="Shows the full evidence graph after a capture completes." />
              <Toggle checked={settings.publicResearchEnabled} onCheckedChange={(checked) => update('publicResearchEnabled', checked)} label="Enable public research" description="Allows read-only Hacker News, GitHub, and YC signal lookups. Keep off for local-only operation." />
              <Toggle checked={settings.exportIncludesRawEvidence} onCheckedChange={(checked) => update('exportIncludesRawEvidence', checked)} label="Include raw evidence in exports" description="When off, exports emphasize quotes and normalized fields instead of full captured text." />
              <Toggle checked={settings.redactionBeforeLlm} onCheckedChange={(checked) => update('redactionBeforeLlm', checked)} label="Redact before LLM calls" description="Keeps the disclosure path conservative before sending profile text to any external provider." />
            </div>
          </Card>

          <Card>
            <div className="flex items-start gap-3">
              <ShieldCheck className="mt-1 text-[var(--accent)]" size={22} />
              <div>
                <h2 className="text-xl font-semibold">Privacy and platform boundary</h2>
                <p className="mt-2 max-w-4xl text-sm leading-6 text-[var(--muted)]">
                  Treeo VC Scout is not a stealth scraper. For LinkedIn-like pages, use manual paste, selected text, visible-page capture after a click, file import, or future approved API adapters. The extension does not bypass access controls, automate browsing, auto-scroll, crawl profiles, copy cookies, or run account actions.
                </p>
              </div>
            </div>
          </Card>

          <Card>
            <div className="flex items-start gap-3">
              <KeyRound className="mt-1 text-[var(--accent)]" size={22} />
              <div>
                <h2 className="text-xl font-semibold">LLM provider router</h2>
                <p className="mt-1 text-sm leading-6 text-[var(--muted)]">
                  Mock mode runs locally. External providers are BYOK and require disclosure acceptance before any profile text is sent.
                </p>
              </div>
            </div>
            <div className="mt-5 grid gap-3 md:grid-cols-2">
              <Toggle checked={settings.localOnlyMode} onCheckedChange={(checked) => update('localOnlyMode', checked)} label="Local-only mode" description="Uses deterministic scoring and mock model output only. No external LLM calls." />
              <Toggle checked={settings.llmDisclosureAccepted} onCheckedChange={(checked) => update('llmDisclosureAccepted', checked)} label="Accept LLM disclosure" description="Required before sending captured text to Groq, Gemini, OpenRouter, or a local AI server endpoint." />
            </div>
            <div className="mt-5 grid gap-3">
              {PROVIDERS.map((provider) => (
                <div key={provider} className="rounded-md border border-[var(--line)] p-4">
                  <div className="flex items-center justify-between gap-4">
                    <div>
                      <div className="font-semibold capitalize">{provider}</div>
                      <p className="mt-1 text-sm text-[var(--muted)]">{provider === 'mock' ? 'Deterministic local output for tests and privacy-first use.' : 'Stored locally in Chrome extension storage.'}</p>
                    </div>
                    <Switch.Root checked={settings.providers[provider].enabled} onCheckedChange={(checked) => updateProvider(provider, { enabled: checked })} className="relative h-6 w-11 rounded-full bg-[var(--line-strong)] data-[state=checked]:bg-[var(--accent)]">
                      <Switch.Thumb className="block h-5 w-5 translate-x-0.5 rounded-full bg-white shadow transition data-[state=checked]:translate-x-[22px]" />
                    </Switch.Root>
                  </div>
                  <div className="mt-4 grid gap-3 md:grid-cols-2">
                    <Input placeholder="Model" value={settings.providers[provider].model ?? ''} onChange={(event) => updateProvider(provider, { model: event.target.value })} />
                    {provider === 'mock' ? null : <Input type="password" placeholder="API key" value={settings.providers[provider].apiKey} onChange={(event) => updateProvider(provider, { apiKey: event.target.value })} />}
                  </div>
                </div>
              ))}
            </div>
            <div className="mt-5">
              <label className="text-sm font-semibold" htmlFor="local-ai-endpoint">Local AI server endpoint</label>
              <Input
                id="local-ai-endpoint"
                className="mt-2 w-full"
                value={settings.aiEndpoint}
                invalid={Boolean(errors.aiEndpoint)}
                helperText={errors.aiEndpoint}
                onChange={(event) => update('aiEndpoint', event.target.value)}
              />
            </div>
            <div className="mt-5 grid gap-4 md:grid-cols-2">
              <div>
                <label className="text-sm font-semibold" htmlFor="github-token">GitHub token (optional)</label>
                <Input
                  id="github-token"
                  className="mt-2 w-full"
                  type="password"
                  value={settings.githubToken}
                  helperText="Raises the public-research rate limit from 60/hr to 5000/hr. Read-only scope is enough."
                  onChange={(event) => update('githubToken', event.target.value)}
                />
              </div>
              <div>
                <label className="text-sm font-semibold" htmlFor="ph-token">Product Hunt token (optional)</label>
                <Input
                  id="ph-token"
                  className="mt-2 w-full"
                  type="password"
                  value={settings.producthuntToken}
                  helperText="When blank, Product Hunt research is silently skipped instead of erroring."
                  onChange={(event) => update('producthuntToken', event.target.value)}
                />
              </div>
            </div>
          </Card>

          <Card>
            <h2 className="text-xl font-semibold">Scoring weights</h2>
            <p className="mt-1 text-sm leading-6 text-[var(--muted)]">The final score blends founder proof, market demand, technical credibility, fund fit, and urgency.</p>
            <div className="mt-5 grid gap-3 md:grid-cols-3">
              <WeightSlider label="Collaborative Edge" value={settings.weighting.collaborativeEdge} onChange={(value) => setSettings((current) => ({ ...current, weighting: { ...current.weighting, collaborativeEdge: value } }))} />
              <WeightSlider label="Structural Demand" value={settings.weighting.structuralDemand} onChange={(value) => setSettings((current) => ({ ...current, weighting: { ...current.weighting, structuralDemand: value } }))} />
              <WeightSlider label="Mutual Value" value={settings.weighting.mutualValue} onChange={(value) => setSettings((current) => ({ ...current, weighting: { ...current.weighting, mutualValue: value } }))} />
              <WeightSlider label="Technical Credibility" value={settings.weighting.technicalCredibility} onChange={(value) => setSettings((current) => ({ ...current, weighting: { ...current.weighting, technicalCredibility: value } }))} />
              <WeightSlider label="Market Pain" value={settings.weighting.marketPain} onChange={(value) => setSettings((current) => ({ ...current, weighting: { ...current.weighting, marketPain: value } }))} />
              <WeightSlider label="Outreach Urgency" value={settings.weighting.outreachUrgency} onChange={(value) => setSettings((current) => ({ ...current, weighting: { ...current.weighting, outreachUrgency: value } }))} />
            </div>
            <div className="mt-5 max-w-sm">
              <label className="text-sm font-semibold" htmlFor="min-score">Partner review threshold</label>
              <Input
                id="min-score"
                className="mt-2 w-full"
                type="number"
                min={40}
                max={95}
                value={settings.minScoreForReview}
                invalid={Boolean(errors.minScoreForReview)}
                helperText={errors.minScoreForReview}
                onChange={(event) => update('minScoreForReview', Number(event.target.value))}
              />
            </div>
          </Card>

          <Card>
            <h2 className="text-xl font-semibold">Fund profile</h2>
            <p className="mt-1 text-sm leading-6 text-[var(--muted)]">Used to compute investor fit, conflict risk, partner routing, and outreach style.</p>
            <div className="mt-5 grid gap-4 md:grid-cols-2">
              <div>
                <label className="text-sm font-semibold" htmlFor="fund-name">Fund name</label>
                <Input
                  id="fund-name"
                  className="mt-2 w-full"
                  value={settings.fundProfile.fundName}
                  invalid={Boolean(errors.fundName)}
                  helperText={errors.fundName}
                  onChange={(event) => setSettings((current) => ({ ...current, fundProfile: { ...current.fundProfile, fundName: event.target.value } }))}
                />
              </div>
              <div>
                <label className="text-sm font-semibold" htmlFor="check-size">Check size</label>
                <Input
                  id="check-size"
                  className="mt-2 w-full"
                  value={settings.fundProfile.checkSize}
                  invalid={Boolean(errors.checkSize)}
                  helperText={errors.checkSize}
                  onChange={(event) => setSettings((current) => ({ ...current, fundProfile: { ...current.fundProfile, checkSize: event.target.value } }))}
                />
              </div>
              <div>
                <label className="text-sm font-semibold" htmlFor="geography">Geography focus</label>
                <Input
                  id="geography"
                  className="mt-2 w-full"
                  value={listText(settings.fundProfile.geographyFocus)}
                  invalid={Boolean(errors.geographyFocus)}
                  helperText={errors.geographyFocus}
                  onChange={(event) => setSettings((current) => ({ ...current, fundProfile: { ...current.fundProfile, geographyFocus: parseList(event.target.value) } }))}
                />
              </div>
              <div>
                <label className="text-sm font-semibold" htmlFor="thesis">Sector thesis</label>
                <Input
                  id="thesis"
                  className="mt-2 w-full"
                  value={listText(settings.fundProfile.sectorThesis)}
                  invalid={Boolean(errors.sectorThesis)}
                  helperText={errors.sectorThesis}
                  onChange={(event) => setSettings((current) => ({ ...current, fundProfile: { ...current.fundProfile, sectorThesis: parseList(event.target.value) }, focusMarkets: parseList(event.target.value) }))}
                />
              </div>
              <div>
                <label className="text-sm font-semibold" htmlFor="portfolio">Portfolio companies</label>
                <Textarea id="portfolio" className="mt-2 w-full" value={listText(settings.fundProfile.portfolioCompanies)} onChange={(event) => setSettings((current) => ({ ...current, fundProfile: { ...current.fundProfile, portfolioCompanies: parseList(event.target.value) } }))} />
              </div>
              <div>
                <label className="text-sm font-semibold" htmlFor="excluded">Excluded sectors or conflicts</label>
                <Textarea id="excluded" className="mt-2 w-full" value={listText(settings.fundProfile.excludedSectors)} onChange={(event) => setSettings((current) => ({ ...current, fundProfile: { ...current.fundProfile, excludedSectors: parseList(event.target.value) } }))} />
              </div>
              <div className="md:col-span-2">
                <label className="text-sm font-semibold" htmlFor="outreach-style">Outreach style</label>
                <Textarea
                  id="outreach-style"
                  className="mt-2 w-full"
                  value={settings.fundProfile.outreachStyle}
                  invalid={Boolean(errors.outreachStyle)}
                  helperText={errors.outreachStyle}
                  onChange={(event) => setSettings((current) => ({ ...current, fundProfile: { ...current.fundProfile, outreachStyle: event.target.value } }))}
                />
              </div>
            </div>
          </Card>

          <Card>
            <div className="flex items-start gap-3">
              <Database className="mt-1 text-[var(--accent)]" size={22} />
              <div className="flex-1">
                <h2 className="text-xl font-semibold">Local data controls</h2>
                <p className="mt-1 text-sm leading-6 text-[var(--muted)]">Deals, evidence, graphs, API keys, and settings are stored locally in the browser. Retention is analyst-controlled.</p>
                <div className="mt-4 max-w-sm">
                  <label className="text-sm font-semibold" htmlFor="retention">Retention days</label>
                  <Input
                    id="retention"
                    className="mt-2 w-full"
                    type="number"
                    min={1}
                    value={settings.retentionDays}
                    invalid={Boolean(errors.retentionDays)}
                    helperText={errors.retentionDays}
                    onChange={(event) => update('retentionDays', Number(event.target.value))}
                  />
                </div>
              </div>
              <Button variant="danger" onClick={() => void clearLocalData()}>
                <Trash2 size={16} />
                {deleted ? 'Deleted' : 'Delete data'}
              </Button>
            </div>
          </Card>
        </div>

        <div className="sticky bottom-4 mt-6 flex items-center justify-between gap-3">
          <div className="text-xs text-[var(--muted)]">
            {!isValid ? (
              <span className="text-red-500">Fix highlighted fields before saving.</span>
            ) : isDirty ? 'Unsaved changes' : saved ? 'Saved' : 'All changes saved'}
          </div>
          <Button onClick={() => void persist()} disabled={!isValid || !isDirty}>
            {saved ? <Check size={16} /> : null}
            {saved ? 'Saved' : 'Save settings'}
          </Button>
        </div>
      </div>
    </main>
  );
}

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <OptionsApp />
    </QueryClientProvider>
  </React.StrictMode>,
);
