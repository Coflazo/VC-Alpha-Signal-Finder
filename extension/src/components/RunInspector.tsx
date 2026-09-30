import * as Dialog from '@radix-ui/react-dialog';
import { Activity, X } from 'lucide-react';
import React from 'react';
import type { AnalysisRunRecord, RuntimeMessage } from '../lib/types';

function fetchRuns(dealId: string): Promise<AnalysisRunRecord[]> {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage({ type: 'TREEO_GET_RUNS', payload: { dealId } } satisfies RuntimeMessage, (response) => {
      if (chrome.runtime.lastError || !response?.ok) resolve([]);
      else resolve((response.runs as AnalysisRunRecord[]) ?? []);
    });
  });
}

function tagValue(run: AnalysisRunRecord, prefix: string): string | undefined {
  const tag = run.warnings.find((line) => line.startsWith(prefix));
  return tag ? tag.slice(prefix.length) : undefined;
}

/**
 * Per-deal audit trail. For every analysis task the pipeline ran, show the
 * provider, model, latency, parse status, and a snippet of the raw output.
 * Renders nothing if no runs exist (e.g. deterministic-only mode).
 */
export function RunInspector({ dealId }: { dealId: string }) {
  const [open, setOpen] = React.useState(false);
  const [runs, setRuns] = React.useState<AnalysisRunRecord[]>([]);

  React.useEffect(() => {
    if (!open) return;
    void fetchRuns(dealId).then(setRuns);
  }, [open, dealId]);

  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger asChild>
        <button
          type="button"
          className="focus-ring inline-flex items-center gap-2 rounded-md border border-[var(--line)] px-3 py-1.5 text-xs font-semibold text-[var(--muted)] hover:border-[var(--line-strong)] hover:text-[var(--text)]"
        >
          <Activity size={13} /> Audit runs
        </button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/40" />
        <Dialog.Content
          aria-describedby={undefined}
          className="fixed right-0 top-0 z-50 h-full w-[480px] overflow-y-auto border-l border-[var(--line)] bg-[var(--surface)] p-5 shadow-panel"
        >
          <div className="flex items-center justify-between">
            <Dialog.Title className="text-base font-semibold">AI run inspector</Dialog.Title>
            <Dialog.Close className="rounded-md border border-[var(--line)] p-1 text-[var(--muted)]">
              <X size={14} />
            </Dialog.Close>
          </div>
          <p className="mt-2 text-xs leading-5 text-[var(--muted)]">
            Per-task provider, model, latency, and parse status. Runs are stamped with `dealId` and `task` columns
            (Dexie v2) and replay safely from `chrome.storage.session` cache.
          </p>
          <div className="mt-4 grid gap-3">
            {runs.length === 0 ? (
              <div className="rounded-md border border-dashed border-[var(--line-strong)] p-4 text-sm text-[var(--muted)]">
                No analysis runs are stored for this deal. The pipeline writes one record per task; runs persist after browser restarts.
              </div>
            ) : (
              runs.map((run) => (
                <div key={run.id} className="rounded-md border border-[var(--line)] p-3 text-xs">
                  <div className="flex items-center justify-between font-semibold">
                    <span>{run.task ?? tagValue(run, 'task:') ?? 'unknown task'}</span>
                    <span className="text-[var(--muted)]">{run.modelProvider} · {run.modelName}</span>
                  </div>
                  <div className="mt-1 flex items-center gap-2 text-[var(--muted)]">
                    <span>latency {tagValue(run, 'latencyMs:') ?? '?'}ms</span>
                    <span>{run.warnings.includes('served_from_cache') ? 'cached' : 'fresh'}</span>
                    <span>hash {run.promptHash.slice(0, 8)}</span>
                  </div>
                  {run.outputJson ? (
                    <pre className="mt-2 max-h-40 overflow-auto rounded bg-[var(--surface-strong)] p-2 font-mono text-[10px] leading-snug text-[var(--text)]">
                      {JSON.stringify(run.outputJson, null, 2).slice(0, 1400)}
                    </pre>
                  ) : (
                    <div className="mt-2 text-red-500">{tagValue(run, 'error:')}</div>
                  )}
                </div>
              ))
            )}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
