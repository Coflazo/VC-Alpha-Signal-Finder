import Papa from 'papaparse';
import { z } from 'zod';
import type { ExtractedProfile } from '../lib/types';
import { profileFromApprovedApiRecord, type ApprovedApiProfileRecord } from './approvedApiAdapterStub';

/**
 * Header-mapped CSV path. A name column is required; everything else is
 * optional but checked for type. Header variants are normalized
 * (`name`/`Name`/`full_name`) before validation.
 */
const RowSchema = z.object({
  name: z.string().min(1, 'name is required'),
  headline: z.string().optional().default(''),
  location: z.string().optional().default(''),
  about: z.string().optional().default(''),
  profileUrl: z.string().optional().default(''),
  companyName: z.string().optional().default(''),
  companyUrl: z.string().optional().default(''),
  website: z.string().optional().default(''),
  experience: z.string().optional().default(''),
  education: z.string().optional().default(''),
  skills: z.string().optional().default(''),
  posts: z.string().optional().default(''),
});

function pickFirst(row: Record<string, unknown>, keys: string[]): string {
  for (const key of keys) {
    const value = row[key];
    if (typeof value === 'string' && value.trim().length > 0) return value.trim();
  }
  return '';
}

function normalizeRow(row: Record<string, unknown>): Record<string, string> {
  return {
    name: pickFirst(row, ['name', 'Name', 'full_name', 'Full Name']),
    headline: pickFirst(row, ['headline', 'Headline', 'title', 'Title']),
    location: pickFirst(row, ['location', 'Location']),
    about: pickFirst(row, ['about', 'About', 'bio', 'Bio', 'summary', 'Summary']),
    profileUrl: pickFirst(row, ['profileUrl', 'profile_url', 'linkedin_url', 'LinkedIn URL', 'url']),
    companyName: pickFirst(row, ['companyName', 'company', 'Company', 'company_name']),
    companyUrl: pickFirst(row, ['companyUrl', 'company_url']),
    website: pickFirst(row, ['website', 'Website', 'domain', 'Domain']),
    experience: pickFirst(row, ['experience', 'Experience']),
    education: pickFirst(row, ['education', 'Education']),
    skills: pickFirst(row, ['skills', 'Skills']),
    posts: pickFirst(row, ['posts', 'Posts', 'activity']),
  };
}

function toApprovedRecord(parsed: z.infer<typeof RowSchema>): ApprovedApiProfileRecord {
  return {
    name: parsed.name,
    headline: parsed.headline,
    location: parsed.location,
    about: parsed.about,
    profileUrl: parsed.profileUrl,
    companyName: parsed.companyName,
    companyUrl: parsed.companyUrl,
    website: parsed.website,
    experience: parsed.experience.split(/\n|;/).filter(Boolean),
    education: parsed.education.split(/\n|;/).filter(Boolean),
    skills: parsed.skills.split(/,|;/).map((item) => item.trim()).filter(Boolean),
    posts: parsed.posts.split(/\n---\n|;/).filter(Boolean),
  };
}

export interface CsvImportReport {
  profiles: ExtractedProfile[];
  errors: Array<{ rowIndex: number; message: string }>;
  errorCsv?: string;
}

/**
 * Parse a CSV and return both the valid profiles and a per-row error report.
 * Bad rows are skipped, not silently mangled like before.
 */
export function profilesFromCsvWithReport(text: string): CsvImportReport {
  const parsed = Papa.parse<Record<string, unknown>>(text, { header: true, skipEmptyLines: true });
  if (parsed.errors.length) {
    return {
      profiles: [],
      errors: parsed.errors.map((err, index) => ({ rowIndex: index, message: err.message })),
    };
  }
  const profiles: ExtractedProfile[] = [];
  const errors: Array<{ rowIndex: number; message: string }> = [];
  parsed.data.forEach((row, index) => {
    const normalized = normalizeRow(row);
    const result = RowSchema.safeParse(normalized);
    if (!result.success) {
      errors.push({ rowIndex: index + 1, message: result.error.issues.map((issue) => issue.message).join('; ') });
      return;
    }
    profiles.push(profileFromApprovedApiRecord(toApprovedRecord(result.data)));
  });
  const errorCsv = errors.length
    ? Papa.unparse(errors.map((e) => ({ row: e.rowIndex, error: e.message })), { quotes: true })
    : undefined;
  return { profiles, errors, errorCsv };
}

/**
 * Back-compat: same signature as before, throws if every row failed.
 * Service worker code paths that handled the previous error shape keep working.
 */
export function profilesFromCsv(text: string): ExtractedProfile[] {
  const report = profilesFromCsvWithReport(text);
  if (!report.profiles.length && report.errors.length) {
    throw new Error(`Could not import CSV: ${report.errors[0].message}`);
  }
  return report.profiles;
}
