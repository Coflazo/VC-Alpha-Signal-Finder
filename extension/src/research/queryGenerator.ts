import type { ExtractedProfile } from '../lib/types';

export function generateResearchQueries(profile: ExtractedProfile): string[] {
  const founder = profile.name;
  const company = profile.companyName;
  const productWords = [profile.companyName, profile.headline, profile.about]
    .join(' ')
    .split(/\W+/)
    .filter((word) => word.length > 4)
    .slice(0, 6)
    .join(' ');
  return [
    company ? `"${company}" startup founder product` : '',
    company ? `"${company}" funding pre-seed seed investor` : '',
    founder && company ? `"${founder}" "${company}"` : founder ? `"${founder}" founder startup` : '',
    company ? `"${company}" co-founder team` : '',
    company ? `"${company}" alternatives competitors` : '',
    productWords ? `"${productWords}" market size startup` : '',
    company ? `"${company}" demo waitlist product launch` : '',
    company ? `"${company}" "VC" "angel" "investor"` : '',
    company ? `site:news.ycombinator.com "${company}"` : '',
    founder ? `site:news.ycombinator.com "${founder}"` : '',
  ].filter(Boolean);
}
