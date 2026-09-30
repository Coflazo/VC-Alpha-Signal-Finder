import {
  classifyHttpStatus,
  messagesToOpenAiBody,
  parseRetryAfter,
  ProviderError,
  type AiProvider,
  type ProviderRequest,
  type ProviderResponse,
} from './types';

interface OpenAiCompatibleConfig {
  name: AiProvider['name'];
  defaultModel: string;
  endpoint: string;
  timeoutMs: number;
  headers?: Record<string, string>;
}

export function createOpenAiCompatibleProvider(config: OpenAiCompatibleConfig): AiProvider {
  return {
    name: config.name,
    defaultModel: config.defaultModel,
    timeoutMs: config.timeoutMs,
    async complete(request: ProviderRequest): Promise<ProviderResponse> {
      const apiKey = request.apiKey ?? '';
      if (!apiKey && config.name !== 'localhost') {
        throw new ProviderError(`${config.name} API key is not configured.`, config.name, 'permanent', 401);
      }

      const controller = new AbortController();
      const timeout = globalThis.setTimeout(() => controller.abort(), config.timeoutMs);
      const started = performance.now();
      try {
        const response = await fetch(request.endpoint || config.endpoint, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(apiKey ? { Authorization: `Bearer ${apiKey}` } : {}),
            ...(config.headers ?? {}),
          },
          body: JSON.stringify(messagesToOpenAiBody(request, config.defaultModel)),
          signal: controller.signal,
        });
        if (!response.ok) {
          const kind = classifyHttpStatus(response.status);
          const retryAfterMs = parseRetryAfter(response.headers.get('retry-after') ?? response.headers.get('Retry-After'));
          throw new ProviderError(
            `${config.name} returned HTTP ${response.status}`,
            config.name,
            kind,
            response.status,
            retryAfterMs,
          );
        }
        const json = await response.json();
        const content = json?.choices?.[0]?.message?.content;
        if (typeof content !== 'string' || content.trim().length === 0) {
          throw new ProviderError(`${config.name} returned an empty response.`, config.name, 'transient');
        }
        return {
          provider: config.name,
          model: String(json?.model ?? request.model ?? config.defaultModel),
          content,
          latencyMs: Math.round(performance.now() - started),
        };
      } catch (error) {
        if (error instanceof ProviderError) throw error;
        const message = error instanceof Error ? error.message : String(error);
        const isAbort = (error as { name?: string })?.name === 'AbortError';
        throw new ProviderError(
          isAbort ? `${config.name} request timed out` : message,
          config.name,
          'transient',
        );
      } finally {
        globalThis.clearTimeout(timeout);
      }
    },
  };
}
