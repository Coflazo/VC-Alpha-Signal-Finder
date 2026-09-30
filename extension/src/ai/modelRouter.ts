import type { ZodSchema } from 'zod';
import type { AnalysisTask, ProviderName, TreeoSettings } from '../lib/types';
import { hashString } from '../lib/utils';
import { TASK_TEMPERATURE } from './prompts/base';
import { parseJsonObject } from './schemas';
import { geminiProvider } from './providers/geminiProvider';
import { mockProvider } from './providers/mockProvider';
import { createOpenAiCompatibleProvider } from './providers/openAiCompatible';
import { ProviderError, type AiProvider, type ChatMessage, type ProviderResponse } from './providers/types';

interface CircuitState {
  failures: number;
  openUntil: number;
  halfOpen: boolean;
}

interface CacheEntry {
  response: ProviderResponse;
  rawJson: unknown;
  createdAt: number;
  schemaName: string;
}

const CACHE_TTL_MS = 1000 * 60 * 60 * 12;
const BACKOFF_BASE_MS = 250;
const BACKOFF_CAP_MS = 4_000;
const COOLDOWN_BASE_MS = 30_000;
const COOLDOWN_CAP_MS = 5 * 60_000;

const providers: Record<ProviderName, AiProvider> = {
  mock: mockProvider,
  groq: createOpenAiCompatibleProvider({
    name: 'groq',
    defaultModel: 'llama-3.3-70b-versatile',
    endpoint: 'https://api.groq.com/openai/v1/chat/completions',
    timeoutMs: 20_000,
  }),
  openrouter: createOpenAiCompatibleProvider({
    name: 'openrouter',
    defaultModel: 'qwen/qwen3-235b-a22b:free',
    endpoint: 'https://openrouter.ai/api/v1/chat/completions',
    timeoutMs: 45_000,
    headers: {
      'HTTP-Referer': 'chrome-extension://treeo-vc-scout',
      'X-Title': 'Treeo VC Scout',
    },
  }),
  localhost: createOpenAiCompatibleProvider({
    name: 'localhost',
    defaultModel: 'auto',
    endpoint: 'http://localhost:4000/v1/chat/completions',
    timeoutMs: 45_000,
  }),
  gemini: geminiProvider,
};

const circuit: Partial<Record<ProviderName, CircuitState>> = {};
const rateLimitedUntil: Partial<Record<ProviderName, number>> = {};
const responseCache = new Map<string, CacheEntry>();

/**
 * Best-effort session-scoped cache backed by `chrome.storage.session` so that
 * re-opening the sidepanel does not retrigger every analysis. Falls through
 * to the in-memory `responseCache` when not in an extension context.
 */
async function sessionCacheGet(key: string): Promise<CacheEntry | undefined> {
  const fromMemory = responseCache.get(key);
  if (fromMemory) return fromMemory;
  if (typeof chrome === 'undefined' || !chrome.storage?.session) return undefined;
  try {
    const got = await chrome.storage.session.get(key);
    const entry = got[key] as CacheEntry | undefined;
    if (entry) responseCache.set(key, entry);
    return entry;
  } catch {
    return undefined;
  }
}

async function sessionCacheSet(key: string, entry: CacheEntry): Promise<void> {
  responseCache.set(key, entry);
  if (typeof chrome === 'undefined' || !chrome.storage?.session) return;
  try {
    await chrome.storage.session.set({ [key]: entry });
  } catch {
    // session storage may be unavailable; in-memory cache still wins.
  }
}

function recordSuccess(provider: ProviderName): void {
  circuit[provider] = { failures: 0, openUntil: 0, halfOpen: false };
}

function recordFailure(provider: ProviderName, kind: 'transient' | 'permanent' | 'rate_limit', retryAfterMs?: number): void {
  if (kind === 'rate_limit') {
    const wait = retryAfterMs && retryAfterMs > 0 ? retryAfterMs : COOLDOWN_BASE_MS;
    rateLimitedUntil[provider] = Date.now() + Math.min(wait, COOLDOWN_CAP_MS);
  }
  const current = circuit[provider] ?? { failures: 0, openUntil: 0, halfOpen: false };
  const failures = current.failures + 1;
  const cooldown = Math.min(COOLDOWN_BASE_MS * Math.pow(2, Math.max(0, failures - 3)), COOLDOWN_CAP_MS);
  circuit[provider] = {
    failures,
    openUntil: failures >= 3 ? Date.now() + cooldown : 0,
    halfOpen: false,
  };
}

/**
 * Half-open semantics: when `openUntil` passes, mark the breaker half-open
 * and allow exactly one probe through. On probe success, close. On probe
 * failure, re-open with a longer cooldown.
 */
function isAvailable(provider: ProviderName): boolean {
  const limitedUntil = rateLimitedUntil[provider] ?? 0;
  if (Date.now() < limitedUntil) return false;
  const state = circuit[provider];
  if (!state) return true;
  if (state.openUntil && Date.now() < state.openUntil) return false;
  if (state.openUntil && Date.now() >= state.openUntil && !state.halfOpen) {
    circuit[provider] = { ...state, halfOpen: true };
  }
  return true;
}

function enabledProviderOrder(settings: TreeoSettings): ProviderName[] {
  if (settings.localOnlyMode) return ['mock'];
  const ordered = settings.providerOrder.filter((provider) => settings.providers[provider]?.enabled);
  const realProviders = ordered.filter((provider) => provider !== 'mock');
  if (realProviders.length) return realProviders;
  return ordered.length ? ordered : ['mock'];
}

function cacheKey(task: AnalysisTask, messages: ChatMessage[], schemaName: string): string {
  return hashString(JSON.stringify({ task, messages, schemaName }));
}

function jitter(ms: number): number {
  return Math.round(ms * (0.5 + Math.random() * 0.5));
}

function isTransient(error: unknown): boolean {
  return error instanceof ProviderError && (error.kind === 'transient' || error.kind === 'rate_limit');
}

export interface RouterResult<T> {
  parsed: T;
  provider: ProviderName;
  model: string;
  promptHash: string;
  raw: string;
  latencyMs: number;
  warnings: string[];
  servedFromCache: boolean;
}

export interface CallOptions {
  maxTokens?: number;
  temperature?: number;
  cache?: boolean;
  maxRetriesPerProvider?: number;
}

export async function callStructured<T>(
  settings: TreeoSettings,
  task: AnalysisTask,
  messages: ChatMessage[],
  schema: ZodSchema<T>,
  options: CallOptions = {},
): Promise<RouterResult<T>> {
  const schemaName = (schema as { description?: string }).description ?? (schema as { constructor: { name: string } }).constructor.name;
  const promptHash = cacheKey(task, messages, schemaName);
  const cached = options.cache !== false ? await sessionCacheGet(promptHash) : undefined;
  if (cached && Date.now() - cached.createdAt < CACHE_TTL_MS && cached.schemaName === schemaName) {
    try {
      const reparsed = schema.parse(cached.rawJson);
      return {
        parsed: reparsed,
        provider: cached.response.provider,
        model: cached.response.model,
        promptHash,
        raw: cached.response.content,
        latencyMs: cached.response.latencyMs,
        warnings: [],
        servedFromCache: true,
      };
    } catch {
      // Cache holds output that no longer matches the schema; treat as miss.
    }
  }

  const order = enabledProviderOrder(settings);
  const errors: string[] = [];
  const maxRetries = options.maxRetriesPerProvider ?? 2;

  for (const providerName of order) {
    if (!isAvailable(providerName)) {
      errors.push(`${providerName}: unavailable`);
      continue;
    }
    const provider = providers[providerName];
    const providerSettings = settings.providers[providerName];
    const temperature = options.temperature ?? TASK_TEMPERATURE[task] ?? 0.2;
    let attempt = 0;
    while (true) {
      try {
        const response = await provider.complete({
          task,
          messages,
          maxTokens: options.maxTokens ?? 1800,
          temperature,
          apiKey: providerSettings.apiKey || settings.aiApiKey,
          model: providerSettings.model || provider.defaultModel,
          endpoint: providerName === 'localhost' ? settings.aiEndpoint : undefined,
        });
        const rawJson = parseJsonObject(response.content);
        const parsed = schema.parse(rawJson);
        recordSuccess(providerName);
        await sessionCacheSet(promptHash, {
          response,
          rawJson,
          createdAt: Date.now(),
          schemaName,
        });
        return {
          parsed,
          provider: providerName,
          model: response.model,
          promptHash,
          raw: response.content,
          latencyMs: response.latencyMs,
          warnings: errors,
          servedFromCache: false,
        };
      } catch (error) {
        const isProvErr = error instanceof ProviderError;
        const kind = isProvErr ? error.kind : 'permanent';
        const retryAfterMs = isProvErr ? error.retryAfterMs : undefined;
        const message = error instanceof Error ? error.message : String(error);
        errors.push(`${providerName}: ${message}`);
        recordFailure(providerName, kind === 'transient' ? 'transient' : kind === 'rate_limit' ? 'rate_limit' : 'permanent', retryAfterMs);
        if (kind === 'permanent') break;
        attempt += 1;
        if (attempt > maxRetries) break;
        if (!isTransient(error)) break;
        const backoff = Math.min(BACKOFF_CAP_MS, BACKOFF_BASE_MS * Math.pow(2, attempt));
        await new Promise<void>((resolve) => globalThis.setTimeout(resolve, jitter(backoff)));
      }
    }
  }

  throw new Error(`All AI providers failed. ${errors.join(' | ')}`);
}

export function providerHealth(): Record<ProviderName, string> {
  return (Object.keys(providers) as ProviderName[]).reduce<Record<ProviderName, string>>((acc, provider) => {
    if (!isAvailable(provider)) {
      const openUntil = circuit[provider]?.openUntil ?? 0;
      const limitedUntil = rateLimitedUntil[provider] ?? 0;
      const remaining = Math.max(openUntil, limitedUntil) - Date.now();
      acc[provider] = `cooldown ${Math.max(0, Math.ceil(remaining / 1000))}s`;
    } else if (circuit[provider]?.halfOpen) {
      acc[provider] = 'probing';
    } else {
      acc[provider] = 'ok';
    }
    return acc;
  }, {} as Record<ProviderName, string>);
}
