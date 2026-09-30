import type { TreeoDeal } from '../lib/types';

export function buildJsonExport(deals: TreeoDeal[]): string {
  return JSON.stringify({
    exportedAt: new Date().toISOString(),
    product: 'Treeo VC Scout',
    version: 1,
    deals,
  }, null, 2);
}
