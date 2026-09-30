import { describe, expect, it } from 'vitest';
import { extractLinkedInProfile } from '../../adapters/linkedinExtractor';
import { profileFromManualPaste } from '../../adapters/manualPasteAdapter';

// Verbatim paste from a real Sarp Türker LinkedIn capture, exactly as it
// arrives from the visible-text adapter (no newlines between sections, ad
// chrome and footer included).
const SARP_LINKEDIN_PASTE = `Sarp Türker· 1st· 2ndCofounder of Merlon | Junior at University of ChicagoStealth · University of ChicagoIstanbul, Istanbul, Türkiye·Contact infoStealthUniversity of Chicago500+ connectionsBartu, Toprak and 258 other mutual connectionsMessageMessageHighlightsYou both studied at Robert CollegeYou both studied at Robert College from Sep 1, 2018 to Jun 1, 2023MessageAboutThird year Computer Science student at the University of Chicago, studying Computer Science and Statistics. Working on AI but have mixed opinions on its ethical implications. Co-founder of an international college counseling company. Fond of nice cafes, cities without grid systems, reading lists, (actually) good coffee, and cooking (and watching videos of people cooking).Activity1,212 followersPostsCommentsSarp Türker • 1stCofounder of Merlon | Junior at University of Chicago1mo • Edited • Mehmet Can and I are building Merlon.AI's rapid integration into society necessitates a new mechanism of risk distribution, and we are excited to build the quantification, pricing & underwriting layer for the generative AI and agentic insurance economy.ExperienceCo-founderStealth · Full-timeApr 2026 - Present · 3 mosCo-FounderIvy Danışmanlık · Self-employedAug 2023 - Present · 2 yrs 11 mosIstanbul, TürkiyeVice PresidentTürkiye Öğrenci SenatosuJan 2021 - Jan 2023 · 2 yrs 1 moIstanbul, TürkiyeEducationUniversity of ChicagoBachelor's degree, Computer Science and Statistics Double MajorJun 2023 – Jun 2027Activities and societies: Turkish Student Association: PresidentUChicago Association for Computing Machinery (ACM): Co-director of FinanceUChicago Coffee Lab: Co-founderRobert CollegeHigh School DiplomaSep 2018 – Jun 2023Activities and societies: Student Council President, RC Business and Economics Society President, started RC Scholars.Honors & awardsInternational Economics Olympiad Alternate Team Member for TurkeyIssued by International Economics Olympiad · Apr 2023University of Rochester: George Eastman Young Leaders AwardApr 2022Associated with Robert KolejShow all 3 honors & awardsLanguagesAlmancaElementary proficiencyTürkçeNative or bilingual proficiencyShow all 3 languagesInterestsTop VoicesCompaniesSchoolsJason M. Lemkin · 2ndSaaStr AI 2027 is May 11-12 in SF Bay!! See You There!!309,266 followersFollowAd OptionsWhy am I seeing this ad?More profiles for youAral Cay · 2ndComputer Science @ Dartmouth CollegeConnectShow allPeople you may knowMingge Deng · 2ndCo-founder@Stealth, Ex-Confluent, Ex-GooglerConnectShow allYou might likePages for youFastnedRenewable Energy Semiconductor Manufacturing57,720 followersFollowShow allAd OptionsAboutAccessibilityTalent SolutionsLinkedIn Corporation © 2026`;

const META = {
  captureMode: 'manual_paste' as const,
  sourceUrl: 'https://www.linkedin.com/in/sarp-turker',
  sourceTitle: 'Sarp Türker',
  sourceType: 'linkedin_visible_page',
  capturedAt: '2026-06-19T00:00:00.000Z',
  isLinkedInLike: true,
};

describe('LinkedIn extractor', () => {
  it('pulls a clean name and headline from the connection-chip header', () => {
    const profile = extractLinkedInProfile(SARP_LINKEDIN_PASTE, META);
    expect(profile.name).toBe('Sarp Türker');
    expect(profile.headline).toMatch(/Cofounder of Merlon/);
    expect(profile.headline).not.toMatch(/1st|2nd/);
    expect(profile.headline).not.toMatch(/Contact info/);
  });

  it('extracts a clean About section that does not contain page chrome', () => {
    const profile = extractLinkedInProfile(SARP_LINKEDIN_PASTE, META);
    expect(profile.about).toMatch(/Third year Computer Science student/);
    expect(profile.about).not.toMatch(/More profiles for you/);
    expect(profile.about).not.toMatch(/LinkedIn Corporation/);
    expect(profile.about).not.toMatch(/Ad Options/);
    expect(profile.about).not.toMatch(/Show all/);
  });

  it('finds experience and education entries', () => {
    const profile = extractLinkedInProfile(SARP_LINKEDIN_PASTE, META);
    expect(profile.experience.length).toBeGreaterThan(0);
    expect(profile.education.length).toBeGreaterThan(0);
    expect(profile.education.some((entry) => /University of Chicago/.test(entry))).toBe(true);
  });

  it('infers the current company from the headline', () => {
    const profile = extractLinkedInProfile(SARP_LINKEDIN_PASTE, META);
    expect(profile.companyName).toBe('Merlon');
  });

  it('routes a LinkedIn-shaped manual paste through the LinkedIn extractor', () => {
    const profile = profileFromManualPaste(SARP_LINKEDIN_PASTE);
    expect(profile.sourceMetadata?.isLinkedInLike).toBe(true);
    expect(profile.name).toBe('Sarp Türker');
    expect(profile.about).not.toMatch(/LinkedIn Corporation/);
  });

  it('does not leak the page footer into rawText that the LLM digest reads', () => {
    const profile = extractLinkedInProfile(SARP_LINKEDIN_PASTE, META);
    expect(profile.rawText).not.toMatch(/LinkedIn Corporation/);
    expect(profile.rawText).not.toMatch(/More profiles for you/);
  });
});
