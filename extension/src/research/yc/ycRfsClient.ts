import rfsData from './rfsTopics.json';

export interface YcRfsTopic {
  topic: string;
  keywords: string[];
  url: string;
}

/**
 * Curated YC Requests For Startups, sourced from `rfsTopics.json` at build
 * time. The JSON file carries a `version` + `updatedAt` so the UI can
 * surface staleness, and so a future scheduled task can refresh from
 * a remote feed without touching code.
 */
export const RFS_VERSION: string = rfsData.version;
export const RFS_UPDATED_AT: string = rfsData.updatedAt;
export const YC_RFS_TOPICS: YcRfsTopic[] = rfsData.topics;

export async function fetchYcRfsTopics(): Promise<YcRfsTopic[]> {
  return YC_RFS_TOPICS;
}
