import type { Evidence, TreeoDeal } from '../lib/types';

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (char) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  }[char] ?? char));
}

function list(items: string[]): string {
  return items.length ? items.map((item) => `- ${item}`).join('\n') : '- unknown';
}

function citationForEvidence(item: Evidence): string {
  // Stable short token to embed inline; the footnote target uses `ev_` so
  // anchor links resolve in both Markdown footnotes and HTML hrefs.
  return `ev_${item.id.split('_').pop() ?? item.id}`;
}

function evidenceFootnotes(evidence: Evidence[]): string {
  return evidence
    .slice(0, 12)
    .map((item) => `[^${citationForEvidence(item)}]: ${item.fieldPath}: "${item.quote}" (${item.sourceType})`)
    .join('\n');
}

function withCitations(text: string, evidenceIds: string[] | undefined, evidence: Evidence[]): string {
  if (!evidenceIds?.length) return text;
  const indexById = new Map(evidence.map((item) => [item.id, item] as const));
  const refs = evidenceIds
    .map((id) => indexById.get(id))
    .filter((item): item is Evidence => Boolean(item))
    .map((item) => `[^${citationForEvidence(item)}]`)
    .join('');
  return refs ? `${text} ${refs}` : text;
}

export function buildMemoMarkdown(deal: TreeoDeal): string {
  const memo = deal.memo;
  const evidence = deal.evidence;
  const startupCitation = withCitations(
    deal.startupAnalysis?.companySummary || 'unknown',
    deal.score.stageEstimate.evidenceIds,
    evidence,
  );
  const technicalCitation = withCitations(
    deal.technicalCredibility?.technicalDepth || 'unknown',
    deal.technicalCredibility?.evidenceIds,
    evidence,
  );

  return `# ${deal.profile.name || 'Unknown founder'} VC memo

## 30-second summary
${memo?.thirtySecondSummary || deal.score.summary}

## Recommendation
${memo?.recommendation || deal.score.recommendation}

## Scorecard
- Founder likelihood: ${deal.score.founderLikelihoodScore}/100
- Technical credibility: ${deal.score.technicalCredibility}/100
- Market pain: ${deal.score.marketPain}/100
- Market timing: ${deal.score.marketTiming}/100
- Investor fit: ${deal.score.investorFit}/100
- Outreach urgency: ${deal.score.outreachUrgency}/100
- Data quality: ${deal.score.dataQuality}/100

## Startup read
${startupCitation}

Product hypothesis: ${deal.startupAnalysis?.productHypothesis || 'unknown'}

Stage: ${deal.score.stageEstimate.stage} (${Math.round(deal.score.stageEstimate.confidence * 100)}% confidence)

## Technical proof
${technicalCitation}

Builder proof:
${list(deal.technicalCredibility?.builderProof ?? [])}

## Market pain
${deal.marketPain?.marketCategory || 'unknown'} for ${deal.marketPain?.customerSegment || 'unknown'}

Workarounds:
${list(deal.marketPain?.existingWorkarounds ?? [])}

## Investor signals
Confirmed investors:
${list(deal.investorSignals?.confirmedInvestors ?? [])}

Possible investor interest, not confirmed investor approach:
${list(deal.investorSignals?.possibleInvestorInterest ?? [])}

## Risks and missing evidence
${list([...(deal.riskAnalysis?.redFlags ?? []), ...deal.score.missingEvidence])}

## First-call questions
${list(memo?.firstCallQuestions ?? [
  'What exact customer pain triggered the product?',
  'What proof exists beyond the profile or public launch page?',
  'What current raise status, if any, can be confirmed?',
])}

## Evidence
${list(evidence.slice(0, 12).map((item) => `[${citationForEvidence(item)}] ${item.fieldPath}: "${item.quote}" (${item.sourceType})`))}

${evidenceFootnotes(evidence)}
`;
}

/**
 * Walk the markdown line-by-line and accumulate list items into proper
 * `<ul>` containers so the rendered HTML never has orphan `<li>` tags.
 * Headings still bubble out, paragraphs are wrapped, and a hand-rolled
 * footnote section anchors evidence backlinks.
 */
export function buildMemoHtml(deal: TreeoDeal): string {
  const markdown = buildMemoMarkdown(deal);
  const lines = markdown.split('\n');
  const parts: string[] = [];
  let inList = false;
  for (const line of lines) {
    if (line.startsWith('# ')) {
      if (inList) { parts.push('</ul>'); inList = false; }
      parts.push(`<h1>${escapeHtml(line.slice(2))}</h1>`);
    } else if (line.startsWith('## ')) {
      if (inList) { parts.push('</ul>'); inList = false; }
      parts.push(`<h2>${escapeHtml(line.slice(3))}</h2>`);
    } else if (line.startsWith('- ')) {
      if (!inList) { parts.push('<ul>'); inList = true; }
      parts.push(`<li>${escapeHtml(line.slice(2))}</li>`);
    } else if (line.startsWith('[^')) {
      // Footnote line. Render as anchored definition list entry.
      if (inList) { parts.push('</ul>'); inList = false; }
      const match = line.match(/^\[\^([^\]]+)\]:\s*(.*)$/);
      if (match) {
        const [, key, body] = match;
        parts.push(`<p id="${escapeHtml(key)}"><strong>[${escapeHtml(key)}]</strong> ${escapeHtml(body)}</p>`);
      }
    } else if (!line.trim()) {
      if (inList) { parts.push('</ul>'); inList = false; }
    } else {
      if (inList) { parts.push('</ul>'); inList = false; }
      // Linkify inline footnote refs `[^ev_X]` so HTML readers can jump.
      const linkified = escapeHtml(line).replace(/\[\^([\w-]+)\]/g, '<sup><a href="#$1">[$1]</a></sup>');
      parts.push(`<p>${linkified}</p>`);
    }
  }
  if (inList) parts.push('</ul>');

  const body = parts.join('\n');
  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>${escapeHtml(deal.profile.name || 'Founder')} memo</title>
  <style>
    body { margin: 0; background: #F7F9FA; color: #102A34; font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    main { max-width: 840px; margin: 0 auto; padding: 40px 24px 64px; }
    h1 { font-size: 30px; line-height: 1.1; letter-spacing: 0; }
    h2 { margin-top: 32px; font-size: 18px; }
    p, li { color: #4B5D66; line-height: 1.6; }
    li { margin: 6px 0; }
    sup a { color: #0E7C66; text-decoration: none; }
  </style>
</head>
<body><main>${body}</main></body>
</html>`;
}
