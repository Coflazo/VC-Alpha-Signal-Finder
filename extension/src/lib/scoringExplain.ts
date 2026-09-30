import { extractFeatures, logistic } from './scoringFeatures';
import { DIMENSION_MODELS } from './scoringModel';
import type { TreeoDeal, TreeoSettings } from './types';

export interface DimensionExplanation {
  dimension: string;
  weight?: number;
  contribution: number;
  formula: string;
  inputs: Array<{ name: string; value: number; weight: number; contribution: number }>;
  evidenceIds: string[];
}

export interface ScoreExplanation {
  total: number;
  confidence: number;
  dataQualityGate: number;
  dimensions: DimensionExplanation[];
  recommendation: TreeoDeal['score']['recommendation'];
  rationale: string;
}

/**
 * Recompute the per-dimension breakdown for `deal` without mutating it.
 * Used by the UI ScoreBreakdown drawer so the analyst can see, for every dimension,
 * which features fired, with what weight, and what they contributed.
 */
export function explainScore(deal: TreeoDeal, settings: TreeoSettings): ScoreExplanation {
  const features = extractFeatures(deal.profile, deal.evidence, settings);
  features.lowFounderFlag = deal.score.founderLikelihoodScore < 35 ? 1 : 0;

  const dimensions = DIMENSION_MODELS.map((model) => {
    const inputs = model.terms.map((term) => {
      const value = term.feature(features);
      const contribution = value * term.weight;
      return { name: term.label, value: Number(value.toFixed(2)), weight: term.weight, contribution: Number(contribution.toFixed(2)) };
    });
    const linear = inputs.reduce((sum, input) => sum + input.contribution, 0) + model.bias;
    const dimensionScore = Math.round(100 * logistic(linear));
    return {
      dimension: model.label,
      contribution: dimensionScore,
      formula: `100 · σ(${model.terms.map((t) => `${t.weight}·${t.label}`).join(' + ')} ${model.bias >= 0 ? '+' : '−'} ${Math.abs(model.bias).toFixed(2)})`,
      inputs,
      evidenceIds: model.evidenceFeatureKeys
        .flatMap((key) => features.evidenceIdsByFeature[key] ?? [])
        .filter((id, index, all) => all.indexOf(id) === index),
    } satisfies DimensionExplanation;
  });

  const dataQualityGate = 0.85 + 0.25 * (deal.score.dataQuality / 100);

  return {
    total: deal.score.total,
    confidence: deal.score.confidence,
    dataQualityGate: Number(dataQualityGate.toFixed(3)),
    dimensions,
    recommendation: deal.score.recommendation,
    rationale: buildRationale(deal),
  };
}

function buildRationale(deal: TreeoDeal): string {
  const { total, confidence, redFlagRisk, recommendation } = deal.score;
  const conf = Math.round(confidence * 100) / 100;
  return `${recommendation}: total ${total}, confidence ${conf}, risk ${redFlagRisk}. ` +
    'total = weighted dimension sum × dataQualityGate. ' +
    'dataQualityGate = 0.85 + 0.25 · dataQuality/100. ' +
    'recommendation tier requires total, confidence, and risk to clear named thresholds.';
}
