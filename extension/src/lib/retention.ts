import { db } from '../db/schema';
import { getSettings } from './storage';

export const RETENTION_ALARM = 'treeo-retention-purge';

/**
 * Daily retention purge. Runs in the service worker via `chrome.alarms` and
 * deletes deals whose `updatedAt` is older than `settings.retentionDays`.
 * Pure functions are exposed for testing with a fake clock.
 */
export function shouldPurge(updatedAt: string, retentionDays: number, now = Date.now()): boolean {
  if (!retentionDays || retentionDays <= 0) return false;
  const ts = Date.parse(updatedAt);
  if (Number.isNaN(ts)) return false;
  const cutoff = now - retentionDays * 86_400_000;
  return ts < cutoff;
}

export async function runRetentionPurge(now = Date.now()): Promise<{ purgedDeals: number; purgedEvidence: number; purgedRuns: number }> {
  const settings = await getSettings();
  const all = await db.deals.toArray();
  const stale = all.filter((deal) => shouldPurge(deal.updatedAt || deal.createdAt, settings.retentionDays, now));
  if (!stale.length) return { purgedDeals: 0, purgedEvidence: 0, purgedRuns: 0 };
  const ids = new Set(stale.map((deal) => deal.id));
  let purgedEvidence = 0;
  let purgedRuns = 0;
  await db.transaction('rw', db.deals, db.evidence, db.claims, db.analysisRuns, async () => {
    await db.deals.bulkDelete(stale.map((deal) => deal.id));
    purgedEvidence = await db.evidence.where('dealId').anyOf([...ids]).delete().catch(() => 0);
    await db.claims.where('dealId').anyOf([...ids]).delete().catch(() => undefined);
    purgedRuns = await db.analysisRuns.where('dealId').anyOf([...ids]).delete().catch(() => 0);
  });
  return { purgedDeals: stale.length, purgedEvidence, purgedRuns };
}

/**
 * Wire the daily alarm. Idempotent: re-registers without duplicating. Call
 * from the service worker's onInstalled/onStartup paths.
 */
export function installRetentionAlarm(): void {
  if (typeof chrome === 'undefined' || !chrome.alarms?.create) return;
  chrome.alarms.create(RETENTION_ALARM, {
    when: Date.now() + 60_000,
    // ~24 hours; the actual fire moment drifts by Chrome's alarm jitter.
    periodInMinutes: 24 * 60,
  });
}
