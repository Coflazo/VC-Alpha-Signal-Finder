import type { EngineResult, EngineVerdict } from '../lib/types';

/**
 * The local VC Alpha engine (`uv run vc-alpha`). Fixed rather than a setting,
 * because the manifest grants the extension exactly this host and no other.
 */
export const ENGINE_URL = 'http://127.0.0.1:8420';

/** Triage on a slow free-tier provider can take half a minute; a hung engine should not hang the panel. */
const TIMEOUT_MS = 90_000;

/** Webmail. A page here is someone's inbox, so it defaults to private. */
const PRIVATE_HOSTS = [/^mail\.google\.com$/, /^outlook\.(live|office|office365)\.com$/];

export interface CaptureRequest {
  text: string;
  url?: string;
  title?: string;
  /** Private pages are embedded only locally and triaged on a redacted fragment. */
  private: boolean;
  thesis?: string;
}

export function isPrivateHost(url: string | undefined): boolean {
  if (!url) return false;
  try {
    const host = new URL(url).hostname;
    return PRIVATE_HOSTS.some((pattern) => pattern.test(host));
  } catch {
    return false;
  }
}

/** Never throws: an engine that is off or failing is a note on the deal, not a failed analysis. */
export async function sendCapture(request: CaptureRequest, timeoutMs = TIMEOUT_MS): Promise<EngineResult> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${ENGINE_URL}/api/capture`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(request),
      signal: controller.signal,
    });
    if (!response.ok) {
      const detail = await response.json().then((body) => body?.detail).catch(() => undefined);
      return { ok: false, reason: typeof detail === 'string' ? detail : `The engine answered ${response.status}.` };
    }
    return { ok: true, verdict: (await response.json()) as EngineVerdict };
  } catch {
    if (controller.signal.aborted) {
      return { ok: false, reason: `The engine took longer than ${Math.round(timeoutMs / 1000)} s to answer.` };
    }
    return { ok: false, reason: 'The engine is not running. Start it with `uv run vc-alpha`.' };
  } finally {
    clearTimeout(timer);
  }
}
