import type { ProviderName } from '../../lib/types';

export interface ChatMessage {
  role: 'system' | 'user' | 'assistant';
  content: string;
}

/**
 * Typed provider error. `kind` lets the router decide whether to retry the
 * same provider, fall back to the next provider, or bail. `retryAfterMs`
 * carries the `Retry-After` header for 429s so the router cools the right
 * provider for the right window.
 */
export type ProviderErrorKind = 'transient' | 'permanent' | 'rate_limit';

export class ProviderError extends Error {
  constructor(
    message: string,
    public provider: ProviderName,
    public kind: ProviderErrorKind,
    public statusCode?: number,
    public retryAfterMs?: number,
  ) {
    super(message);
    this.name = 'ProviderError';
  }
}

/**
 * Parse a `Retry-After` value (seconds or HTTP-date) into milliseconds, or
 * undefined if the header is absent or unparseable.
 */
export function parseRetryAfter(value: string | null | undefined): number | undefined {
  if (!value) return undefined;
  const trimmed = value.trim();
  if (/^\d+$/.test(trimmed)) return Number(trimmed) * 1000;
  const asDate = Date.parse(trimmed);
  if (Number.isNaN(asDate)) return undefined;
  return Math.max(0, asDate - Date.now());
}

export function classifyHttpStatus(status: number): ProviderErrorKind {
  if (status === 429) return 'rate_limit';
  if (status >= 500) return 'transient';
  if (status === 408) return 'transient';
  return 'permanent';
}

export interface ProviderRequest {
  task: string;
  messages: ChatMessage[];
  maxTokens: number;
  temperature: number;
  model?: string;
  apiKey?: string;
  endpoint?: string;
}

export interface ProviderResponse {
  provider: ProviderName;
  model: string;
  content: string;
  latencyMs: number;
}

export interface AiProvider {
  name: ProviderName;
  defaultModel: string;
  timeoutMs: number;
  complete(request: ProviderRequest): Promise<ProviderResponse>;
}

export function messagesToOpenAiBody(request: ProviderRequest, model: string): Record<string, unknown> {
  return {
    model: request.model || model,
    messages: request.messages,
    max_tokens: request.maxTokens,
    temperature: request.temperature,
  };
}
