import type { ProductHuntLaunchRecord } from '../../lib/types';

export function productHuntLaunchStrength(launch: ProductHuntLaunchRecord): number {
  return Math.min(100, Math.round(
    Math.min(launch.votes, 1000) * 0.055 +
    Math.min(launch.comments, 200) * 0.16 +
    (launch.makerNames.length ? 8 : 0) +
    (launch.tagline.length > 20 ? 6 : 0),
  ));
}

export function summarizeProductHuntLaunches(launches: ProductHuntLaunchRecord[]): string[] {
  return launches
    .sort((a, b) => productHuntLaunchStrength(b) - productHuntLaunchStrength(a))
    .slice(0, 5)
    .map((launch) => `${launch.name}: ${launch.tagline || 'no tagline'} (${launch.votes} votes, ${launch.comments} comments)`);
}
