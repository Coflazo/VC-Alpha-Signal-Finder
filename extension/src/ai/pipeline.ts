import { createDeal } from '../lib/scoring';
import type {
  AnalysisRunRecord,
  AnalysisTask,
  GithubRepoRecord,
  HnCommentRecord,
  HnStoryRecord,
  TreeoDeal,
  TreeoSettings,
  ExtractedProfile,
  YcSignalRecord,
} from '../lib/types';
import { makeId, nowIso } from '../lib/utils';
import { callStructured, type RouterResult } from './modelRouter';
import {
  FounderClassificationSchema,
  HnSignalSchema,
  InvestorSignalsSchema,
  MarketPainSchema,
  RiskAnalysisSchema,
  StartupAnalysisSchema,
  TechnicalCredibilitySchema,
  VcMemoSchema,
  type FounderClassificationOutput,
} from './schemas';
import { analyzeStartupPrompt } from './prompts/analyzeStartup';
import { classifyFounderPrompt } from './prompts/classifyFounder';
import { hnSignalAnalysisPrompt } from './prompts/hnSignalAnalysis';
import { investorSignalsPrompt } from './prompts/investorSignals';
import { marketPainPrompt } from './prompts/marketPain';
import { riskAnalysisPrompt } from './prompts/riskAnalysis';
import { technicalCredibilityPrompt } from './prompts/technicalCredibility';
import { vcMemoPrompt } from './prompts/vcMemo';

export interface ResearchBundle {
  hnStories: HnStoryRecord[];
  hnComments: HnCommentRecord[];
  githubRepos: GithubRepoRecord[];
  ycSignals: YcSignalRecord[];
}

const EMPTY_RESEARCH: ResearchBundle = {
  hnStories: [],
  hnComments: [],
  githubRepos: [],
  ycSignals: [],
};

/**
 * Should the LLM pipeline run? Mock provider counts: local-only mode is fine
 * because `enabledProviderOrder` routes to mock. External providers require
 * the LLM disclosure to be explicitly accepted.
 */
function shouldRunLlmPipeline(settings: TreeoSettings): boolean {
  if (settings.localOnlyMode) return true;
  return settings.llmDisclosureAccepted;
}

function clamp01(value: number): number {
  if (Number.isNaN(value)) return 0;
  if (value < 0) return 0;
  if (value > 1) return 1;
  return value;
}

function blend(deterministic: number, llm: number, confidence: number): number {
  const alpha = clamp01(confidence);
  return Math.round((1 - alpha) * deterministic + alpha * llm);
}

function mergeFounderClassification(deal: TreeoDeal, parsed: FounderClassificationOutput): TreeoDeal {
  const blendedFounder = blend(deal.score.founderLikelihoodScore, parsed.founderLikelihoodScore, parsed.confidence);
  const blendedConfidence = clamp01(
    (1 - clamp01(parsed.confidence)) * deal.score.confidence + clamp01(parsed.confidence),
  );
  return {
    ...deal,
    score: {
      ...deal.score,
      founderLikelihoodScore: blendedFounder,
      founderLabel: parsed.label,
      confidence: Number(blendedConfidence.toFixed(2)),
      missingEvidence: [...new Set([...deal.score.missingEvidence, ...parsed.missingEvidence])],
    },
  };
}

function recordFromRouterResult<T>(
  task: AnalysisTask,
  result: RouterResult<T>,
  dealId: string,
  personId?: string,
): AnalysisRunRecord {
  return {
    id: makeId('run'),
    dealId,
    task,
    personId,
    companyId: undefined,
    createdAt: nowIso(),
    modelProvider: result.provider,
    modelName: result.model,
    promptHash: result.promptHash,
    outputJson: result.parsed,
    warnings: [
      `latencyMs:${result.latencyMs}`,
      result.servedFromCache ? 'served_from_cache' : 'fresh',
      ...result.warnings,
    ],
  };
}

function recordFromError(
  task: AnalysisTask,
  error: unknown,
  dealId: string,
  personId?: string,
): AnalysisRunRecord {
  return {
    id: makeId('run'),
    dealId,
    task,
    personId,
    companyId: undefined,
    createdAt: nowIso(),
    modelProvider: 'deterministic',
    modelName: 'failed',
    promptHash: '',
    outputJson: null,
    warnings: [`error:${error instanceof Error ? error.message : String(error)}`],
  };
}

export interface PipelineOutput {
  deal: TreeoDeal;
  runs: AnalysisRunRecord[];
}

export async function runFounderAnalysis(
  profile: ExtractedProfile,
  settings: TreeoSettings,
  research: Partial<ResearchBundle> = {},
): Promise<PipelineOutput> {
  let deal = createDeal(profile, settings);
  const bundle = { ...EMPTY_RESEARCH, ...research };
  const runs: AnalysisRunRecord[] = [];

  if (!shouldRunLlmPipeline(settings)) {
    return {
      deal: {
        ...deal,
        riskAnalysis: {
          redFlags: deal.score.risks,
          inconsistencies: [],
          overclaimingRisk: 'LLM synthesis is disabled until provider disclosure is accepted.',
          dataQualityWarnings: deal.score.missingEvidence,
          privacyWarnings: profile.sourceMetadata?.isLinkedInLike ? ['LinkedIn-like source captured. Only process data you are permitted to analyze.'] : [],
        },
        updatedAt: nowIso(),
      },
      runs,
    };
  }

  const dealId = deal.id;
  const personId = deal.profile.id;

  const runTask = async <T>(
    task: AnalysisTask,
    invoke: () => Promise<RouterResult<T>>,
    onSuccess: (result: T) => void,
  ): Promise<void> => {
    try {
      const result = await invoke();
      runs.push(recordFromRouterResult(task, result, dealId, personId));
      onSuccess(result.parsed);
    } catch (error) {
      runs.push(recordFromError(task, error, dealId, personId));
    }
  };

  await runTask('founder_classification', () =>
    callStructured(settings, 'founder_classification', classifyFounderPrompt(deal.profile, deal.evidence), FounderClassificationSchema),
    (parsed) => { deal = mergeFounderClassification(deal, parsed); });

  await runTask('startup_analysis', () =>
    callStructured(settings, 'startup_analysis', analyzeStartupPrompt(deal), StartupAnalysisSchema),
    (parsed) => {
      deal = {
        ...deal,
        startupAnalysis: {
          companySummary: parsed.companySummary,
          productHypothesis: parsed.productHypothesis,
          stageEstimate: {
            stage: parsed.stageEstimate.stage,
            confidence: parsed.stageEstimate.confidence,
            evidenceIds: parsed.stageEstimate.evidence_ids,
            missingEvidence: parsed.stageEstimate.missingEvidence,
          },
          tractionSignals: parsed.tractionSignals,
          businessModel: parsed.businessModel,
          credibilitySignals: parsed.credibilitySignals,
          technicalCredibility: parsed.technicalCredibility,
          missingInfo: parsed.missingInfo,
        },
      };
    });

  await runTask('technical_credibility', () =>
    callStructured(settings, 'technical_credibility', technicalCredibilityPrompt(deal, bundle.githubRepos), TechnicalCredibilitySchema),
    (parsed) => {
      deal = {
        ...deal,
        technicalCredibility: {
          repoQuality: parsed.repoQuality,
          technicalDepth: parsed.technicalDepth,
          builderProof: parsed.builderProof,
          dependencyRisk: parsed.dependencyRisk,
          moat: parsed.moat,
          score: parsed.score,
          evidenceIds: parsed.evidence_ids,
        },
      };
    });

  await runTask('hn_signal_analysis', () =>
    callStructured(settings, 'hn_signal_analysis', hnSignalAnalysisPrompt(deal, bundle.hnStories, bundle.hnComments), HnSignalSchema),
    (parsed) => { deal = { ...deal, hnSignals: { ...parsed, evidenceIds: parsed.evidence_ids } }; });

  await runTask('market_pain', () =>
    callStructured(settings, 'market_pain', marketPainPrompt(deal, bundle.hnStories, bundle.hnComments), MarketPainSchema),
    (parsed) => { deal = { ...deal, marketPain: { ...parsed, evidenceIds: parsed.evidence_ids } }; });

  await runTask('investor_signals', () =>
    callStructured(settings, 'investor_signals', investorSignalsPrompt(deal, settings), InvestorSignalsSchema),
    (parsed) => { deal = { ...deal, investorSignals: { ...parsed, evidenceIds: parsed.evidence_ids } }; });

  await runTask('risk_analysis', () =>
    callStructured(settings, 'risk_analysis', riskAnalysisPrompt(deal), RiskAnalysisSchema),
    (parsed) => { deal = { ...deal, riskAnalysis: parsed }; });

  await runTask('vc_memo', () =>
    callStructured(settings, 'vc_memo', vcMemoPrompt(deal), VcMemoSchema),
    (parsed) => { deal = { ...deal, memo: parsed }; });

  return {
    deal: { ...deal, updatedAt: nowIso() },
    runs,
  };
}
