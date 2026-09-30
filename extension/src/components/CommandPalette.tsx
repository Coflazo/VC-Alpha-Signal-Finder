import * as Dialog from '@radix-ui/react-dialog';
import { Search } from 'lucide-react';
import React from 'react';

export interface Command {
  id: string;
  label: string;
  hint?: string;
  run: () => void | Promise<void>;
}

/**
 * ⌘K / Ctrl-K palette. Replaces mouse-only tab nav with a keyboard-first
 * surface for "Analyze visible page", "Switch deal X", "Export memo MD",
 * "Toggle theme", "Open settings". Pure Radix Dialog + native input; no new
 * dependencies.
 */
export function CommandPalette({ commands }: { commands: Command[] }) {
  const [open, setOpen] = React.useState(false);
  const [query, setQuery] = React.useState('');

  React.useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        setOpen((value) => !value);
      }
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const filtered = React.useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return commands;
    return commands.filter((cmd) => cmd.label.toLowerCase().includes(q) || (cmd.hint ?? '').toLowerCase().includes(q));
  }, [commands, query]);

  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/30" />
        <Dialog.Content
          aria-describedby={undefined}
          className="fixed left-1/2 top-1/3 z-50 w-[480px] -translate-x-1/2 rounded-md border border-[var(--line)] bg-[var(--surface)] shadow-panel"
        >
          <Dialog.Title className="sr-only">Command palette</Dialog.Title>
          <div className="flex items-center gap-2 border-b border-[var(--line)] px-3 py-2">
            <Search size={16} className="text-[var(--muted)]" />
            <input
              autoFocus
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Type a command…"
              className="h-9 flex-1 bg-transparent text-sm outline-none placeholder:text-[var(--muted)]"
            />
            <kbd className="rounded border border-[var(--line)] px-1.5 py-0.5 text-[10px] text-[var(--muted)]">esc</kbd>
          </div>
          <div className="max-h-72 overflow-auto py-1">
            {filtered.length === 0 ? (
              <div className="px-3 py-4 text-sm text-[var(--muted)]">No commands match.</div>
            ) : (
              filtered.map((cmd) => (
                <button
                  key={cmd.id}
                  type="button"
                  onClick={() => {
                    setOpen(false);
                    setQuery('');
                    void cmd.run();
                  }}
                  className="focus-ring flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm hover:bg-[var(--surface-strong)]"
                >
                  <span>{cmd.label}</span>
                  {cmd.hint ? <span className="text-xs text-[var(--muted)]">{cmd.hint}</span> : null}
                </button>
              ))
            )}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
