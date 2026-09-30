import { ExternalLink } from 'lucide-react';
import React from 'react';
import type { Evidence } from '../lib/types';
import { truncateMiddle } from '../lib/utils';

/**
 * Lightweight evidence trail. Click on any score number to open an inline
 * panel that shows the evidence quotes that support it. Implemented without
 * adding @radix-ui/react-popover — minimal disclosure using React state and
 * absolute positioning, dismissed on outside-click or Escape.
 */
export function EvidencePopover({
  trigger,
  evidence,
  title = 'Supporting evidence',
}: {
  trigger: React.ReactNode;
  evidence: Evidence[];
  title?: string;
}) {
  const [open, setOpen] = React.useState(false);
  const containerRef = React.useRef<HTMLSpanElement | null>(null);

  React.useEffect(() => {
    if (!open) return;
    function onClick(event: MouseEvent) {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false);
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') setOpen(false);
    }
    window.addEventListener('mousedown', onClick);
    window.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('mousedown', onClick);
      window.removeEventListener('keydown', onKey);
    };
  }, [open]);

  return (
    <span ref={containerRef} className="relative inline-flex">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="focus-ring inline-flex items-center gap-1 rounded-md text-[var(--accent)] hover:underline"
      >
        {trigger}
      </button>
      {open ? (
        <span className="absolute left-0 top-full z-40 mt-2 inline-block w-80 rounded-md border border-[var(--line)] bg-[var(--surface)] p-3 shadow-panel" role="dialog" aria-label={title}>
          <span className="text-xs font-semibold uppercase tracking-[0.14em] text-[var(--muted)]">{title}</span>
          <span className="mt-2 grid gap-2">
            {evidence.length === 0 ? (
              <span className="text-sm text-[var(--muted)]">No supporting evidence captured for this signal.</span>
            ) : (
              evidence.slice(0, 6).map((item) => (
                <span key={item.id} className="block rounded-md border border-[var(--line)] p-2 text-xs">
                  <span className="block font-semibold">{item.fieldPath}</span>
                  <span className="mt-1 block text-[var(--muted)]">{item.quote || item.capturedText.slice(0, 240)}</span>
                  <span className="mt-1 flex items-center justify-between">
                    <span className="text-[10px] uppercase tracking-[0.14em] text-[var(--muted)]">{item.reliability}</span>
                    {item.sourceUrl ? (
                      <a className="inline-flex items-center gap-1 text-[var(--accent)]" href={item.sourceUrl} target="_blank" rel="noreferrer">
                        {truncateMiddle(item.sourceUrl, 32)} <ExternalLink size={10} />
                      </a>
                    ) : null}
                  </span>
                </span>
              ))
            )}
          </span>
        </span>
      ) : null}
    </span>
  );
}
