import type { FounderGraph, TreeoDeal } from '../lib/types';

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (char) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  }[char] ?? char));
}

export function exportGraphJson(graph: FounderGraph): string {
  return JSON.stringify(graph, null, 2);
}

export function exportGraphSvg(graph: FounderGraph): string {
  const width = 980;
  const height = 640;
  const centerX = width / 2;
  const centerY = height / 2;
  const radius = 230;
  const nodes = graph.nodes.map((node, index) => {
    if (index === 0) return { ...node, x: centerX, y: centerY };
    const angle = ((index - 1) / Math.max(1, graph.nodes.length - 1)) * Math.PI * 2;
    return { ...node, x: centerX + Math.cos(angle) * radius, y: centerY + Math.sin(angle) * radius };
  });
  const byId = Object.fromEntries(nodes.map((node) => [node.id, node]));
  const edgeSvg = graph.edges.map((edge) => {
    const source = byId[edge.source];
    const target = byId[edge.target];
    if (!source || !target) return '';
    return `<line x1="${source.x}" y1="${source.y}" x2="${target.x}" y2="${target.y}" stroke="#C7D2D9" stroke-width="1.5" />`;
  }).join('\n');
  const nodeSvg = nodes.map((node, index) => {
    const fill = index === 0 ? '#102A34' : node.type === 'risk' ? '#FDE68A' : node.type === 'evidence' ? '#E5E7EB' : '#E7F5F2';
    const textFill = index === 0 ? '#FFFFFF' : '#102A34';
    return `
      <g>
        <circle cx="${node.x}" cy="${node.y}" r="${index === 0 ? 44 : 30}" fill="${fill}" stroke="#78909C" stroke-width="1" />
        <text x="${node.x}" y="${node.y + (index === 0 ? 58 : 44)}" text-anchor="middle" font-family="Arial, sans-serif" font-size="12" fill="${textFill}">${escapeHtml(node.label.slice(0, 24))}</text>
      </g>`;
  }).join('\n');
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">${edgeSvg}${nodeSvg}</svg>`;
}

export function exportGraphHtml(deal: TreeoDeal): string {
  const graph = deal.graph ?? { nodes: [], edges: [] };
  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>${escapeHtml(deal.profile.name || 'Founder')} graph</title>
  <style>
    body { margin: 0; font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: #102A34; background: #F7F9FA; }
    main { max-width: 1120px; margin: 0 auto; padding: 32px; }
    h1 { margin: 0; font-size: 28px; letter-spacing: 0; }
    p { color: #54656E; line-height: 1.55; }
    .surface { margin-top: 24px; border: 1px solid #D9E2E7; background: #FFFFFF; border-radius: 8px; padding: 18px; }
    pre { white-space: pre-wrap; overflow-wrap: anywhere; }
  </style>
</head>
<body>
  <main>
    <h1>${escapeHtml(deal.profile.name || 'Founder')} relationship graph</h1>
    <p>${escapeHtml(deal.score.summary)}</p>
    <div class="surface">${exportGraphSvg(graph)}</div>
    <div class="surface"><pre>${escapeHtml(exportGraphJson(graph))}</pre></div>
  </main>
</body>
</html>`;
}
