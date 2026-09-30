import { afterEach, describe, expect, it, vi } from 'vitest';
import { ENGINE_URL, isPrivateHost, sendCapture } from '../../engine/engineClient';
import type { EngineVerdict } from '../../lib/types';

const verdict: EngineVerdict = {
  id: 'abc',
  status: 'scored',
  source: 'extension',
  thesis: { id: 'treeo', name: 'Treeo VC' },
  similarity: 0.42,
  confidence: 0.71,
  score: 0.55,
  stage: 'pre-seed',
  summary: 'AI procurement for manufacturers.',
  signals: [{ key: 'is_building', score: 0.9, quote: 'we built' }],
  note: '',
};

const request = { text: 'Show HN: we built a thing', url: 'https://news.ycombinator.com/item?id=1', private: false, thesis: 'treeo' };

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('sendCapture', () => {
  it('posts the capture to the local engine and returns its verdict', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(verdict), { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);

    const result = await sendCapture(request);

    expect(result).toEqual({ ok: true, verdict });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(`${ENGINE_URL}/api/capture`);
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body)).toEqual(request);
  });

  it('passes on the reason the engine gives for refusing', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "No fund called 'x' is configured." }), { status: 404 })));

    expect(await sendCapture(request)).toEqual({ ok: false, reason: "No fund called 'x' is configured." });
  });

  it('reports the status when the engine fails without a reason', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('oops', { status: 500 })));

    const result = await sendCapture(request);
    expect(result.ok).toBe(false);
    expect(!result.ok && result.reason).toContain('500');
  });

  it('says the engine is not running when nothing answers', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));

    const result = await sendCapture(request);
    expect(!result.ok && result.reason).toMatch(/not running/i);
  });

  it('gives up after the timeout instead of hanging the analysis', async () => {
    vi.stubGlobal('fetch', vi.fn((_url: string, init: RequestInit) => new Promise((_resolve, reject) => {
      init.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
    })));

    const result = await sendCapture(request, 10);
    expect(!result.ok && result.reason).toMatch(/longer than/i);
  });
});

describe('isPrivateHost', () => {
  it.each([
    'https://mail.google.com/mail/u/0/#inbox/1',
    'https://outlook.live.com/mail/0/',
    'https://outlook.office.com/mail/',
    'https://outlook.office365.com/mail/',
  ])('treats %s as private', (url) => {
    expect(isPrivateHost(url)).toBe(true);
  });

  it.each([
    'https://news.ycombinator.com/item?id=1',
    'https://www.linkedin.com/in/someone',
    'https://google.com/mail.google.com',
    'not a url',
    undefined,
  ])('treats %s as public', (url) => {
    expect(isPrivateHost(url)).toBe(false);
  });
});
