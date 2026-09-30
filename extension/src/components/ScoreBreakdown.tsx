import { ChevronDown, ChevronRight } from 'lucide-react';
import React from 'react';
import { explainScore, type ScoreExplanation } from '../lib/scoringExplain';
import type { TreeoDeal, TreeoSettings } from '../lib/types';
import { Card } from './ui';

/**
 * Render the per-dimension breakdown so the analyst can see exactly which
 * features moved each dimension and by how much. Replaces the opaque
 * `* 1.18 + dataQuality * 0.08` magic line.
 */
export function ScoreBreakdown({ deal, settings, defaultOpen = false }: { deal: TreeoDeal; settings: TreeoSettings; defaultOpen?: boolean }) {
  const explanation = React.useMemo<ScoreExplanation>(() => explainScore(deal, settings), [deal, settings]);
  const [open, setOpen] = React.useState(defaultOpen);

  return (
    <Card>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="focus-ring flex w-full items-center justify-between rounded-md text-left"
        aria-expanded={open}
      >
        <div>
          <h3 className="text-sm font-semibold">Score breakdown</h3>
          <p className="mt-1 text-xs text-[var(--muted)]">
            total = Σ wᵢ · dimᵢ × dataQualityGate ({explanation.dataQualityGate.toFixed(2)}). {explanation.rationale}
          </p>
        </div>
        {open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
      </button>
      {open ? (
        <div className="mt-4 overflow-x-auto rounded-md border border-[var(--line)]">
          <table className="w-full text-sm">
            <thead className="bg-[var(--surface-strong)] text-xs uppercase tracking-[0.12em] text-[var(--muted)]">
              <tr>
                <th className="px-3 py-3 text-left">Dimension</th>
                <th className="px-3 py-3 text-left">Score</th>
                <th className="px-3 py-3 text-left">Top inputs</th>
                <th className="px-3 py-3 text-left">Formula</th>
              </tr>
            </thead>
            <tbody>
              {explanation.dimensions.map((row) => (
                <tr key={row.dimension} className="border-t border-[var(--line)] align-top">
                  <td className="px-3 py-3 font-semibold">{row.dimension}</td>
                  <td className="px-3 py-3 data-font">{row.contribution}</td>
                  <td className="px-3 py-3 text-[var(--muted)]">
                    {row.inputs
                      .filter((input) => Math.abs(input.contribution) > 0.05)
                      .sort((a, b) => Math.abs(b.contribution) - Math.abs(a.contribution))
                      .slice(0, 3)
                      .map((input) => `${input.name} ${input.contribution >= 0 ? '+' : ''}${input.contribution.toFixed(2)}`)
                      .join(', ') || 'no inputs above noise threshold'}
                  </td>
                  <td className="px-3 py-3 font-mono text-xs text-[var(--muted)]">{row.formula}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </Card>
  );
}
