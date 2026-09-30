import type { ExtractedProfile, SourceMetadata } from '../lib/types';
import { nowIso } from '../lib/utils';
import { normalizeRawProfile } from './genericProfileAdapter';

export interface ApprovedApiProfileRecord {
  name?: string;
  headline?: string;
  location?: string;
  about?: string;
  profileUrl?: string;
  companyName?: string;
  companyUrl?: string;
  website?: string;
  experience?: string[];
  education?: string[];
  skills?: string[];
  posts?: string[];
}

export function profileFromApprovedApiRecord(record: ApprovedApiProfileRecord, sourceUrl = ''): ExtractedProfile {
  const metadata: SourceMetadata = {
    captureMode: 'approved_api_stub',
    sourceUrl,
    sourceTitle: 'Approved API import',
    sourceType: 'approved_api_stub',
    capturedAt: nowIso(),
  };
  const text = [
    record.name,
    record.headline,
    record.location,
    record.about,
    record.companyName,
    record.companyUrl,
    record.website,
    ...(record.experience ?? []),
    ...(record.education ?? []),
    ...(record.skills ?? []),
    ...(record.posts ?? []),
  ].filter(Boolean).join('\n');
  return {
    ...normalizeRawProfile(text, metadata, [record.profileUrl, record.companyUrl, record.website].filter(Boolean) as string[]),
    name: record.name ?? '',
    headline: record.headline ?? '',
    location: record.location ?? '',
    about: record.about ?? '',
    profileUrl: record.profileUrl ?? sourceUrl,
    companyName: record.companyName ?? '',
    companyUrl: record.companyUrl ?? '',
    companyWebsite: record.website ?? '',
    experience: record.experience ?? [],
    education: record.education ?? [],
    skills: record.skills ?? [],
    posts: record.posts ?? [],
  };
}
