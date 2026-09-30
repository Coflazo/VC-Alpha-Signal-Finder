import {
  classifyHttpStatus,
  parseRetryAfter,
  ProviderError,
  type AiProvider,
  type ProviderRequest,
  type ProviderResponse,
} from './types';

export const geminiProvider: AiProvider = {
  name: 'gemini',
  defaultModel: 'gemini-2.5-flash-lite',
  timeoutMs: 30_000,
  async complete(request: ProviderRequest): Promise<ProviderResponse> {
    if (!request.apiKey) throw new ProviderError('Gemini API key is not configured.', 'gemini', 'permanent', 401);
    const model = request.model || this.defaultModel;
    const controller = new AbortController();
    const timeout = globalThis.setTimeout(() => controller.abort(), this.timeoutMs);
    const started = performance.now();
    const contents = request.messages
      .filter((message) => message.role !== 'system')
      .map((message) => ({
        role: message.role === 'assistant' ? 'model' : 'user',
        parts: [{ text: message.content }],
      }));
    const systemInstruction = request.messages.find((message) => message.role === 'system')?.content;

    try {
      const response = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent?key=${request.apiKey}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          contents,
          ...(systemInstruction ? { systemInstruction: { parts: [{ text: systemInstruction }] } } : {}),
          generationConfig: {
            temperature: request.temperature,
            maxOutputTokens: request.maxTokens,
            responseMimeType: 'application/json',
          },
        }),
        signal: controller.signal,
      });
      if (!response.ok) {
        const kind = classifyHttpStatus(response.status);
        const retryAfterMs = parseRetryAfter(response.headers.get('retry-after') ?? response.headers.get('Retry-After'));
        throw new ProviderError(`Gemini returned HTTP ${response.status}`, 'gemini', kind, response.status, retryAfterMs);
      }
      const json = await response.json();
      const content = json?.candidates?.[0]?.content?.parts?.map((part: { text?: string }) => part.text ?? '').join('');
      if (!content) throw new ProviderError('Gemini returned an empty response.', 'gemini', 'transient');
      return {
        provider: 'gemini',
        model,
        content,
        latencyMs: Math.round(performance.now() - started),
      };
    } catch (error) {
      if (error instanceof ProviderError) throw error;
      const isAbort = (error as { name?: string })?.name === 'AbortError';
      const message = error instanceof Error ? error.message : String(error);
      throw new ProviderError(isAbort ? 'Gemini request timed out' : message, 'gemini', 'transient');
    } finally {
      globalThis.clearTimeout(timeout);
    }
  },
};
