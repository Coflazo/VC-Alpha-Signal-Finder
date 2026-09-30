import Papa from 'papaparse';
import writeXlsxFile, { type Sheet, type SheetData } from 'write-excel-file/browser';
import type { TreeoDeal } from '../lib/types';
import { buildCsvExports } from './csvExport';

type Cell = SheetData[number][number];

function headerCell(value: string): Cell {
  return { value, fontWeight: 'bold', backgroundColor: '#0E7C66', wrap: true };
}

function bodyCell(value: string | number | boolean): Cell {
  if (typeof value === 'number') return { type: Number, value };
  return { value: String(value), wrap: true };
}

function csvToSheetData(csv: string): SheetData {
  const parsed = Papa.parse<string[]>(csv, { skipEmptyLines: false });
  if (parsed.errors.length) throw new Error(parsed.errors[0]?.message ?? 'Could not parse CSV for XLSX export.');
  return parsed.data.map((row, rowIndex) => row.map((cell) => (rowIndex === 0 ? headerCell(cell) : bodyCell(cell))));
}

function buildSummarySheet(deals: TreeoDeal[]): SheetData {
  const rows: Cell[][] = [];
  rows.push([headerCell('Founder'), headerCell('Total'), headerCell('Confidence'), headerCell('Risk'), headerCell('Recommendation')]);
  for (const deal of deals) {
    rows.push([
      { value: deal.profile.name || 'Unknown founder', wrap: true },
      { type: Number, value: deal.score.total, backgroundColor: colorForScore(deal.score.total) },
      { type: Number, value: Number(deal.score.confidence.toFixed(2)) },
      { type: Number, value: deal.score.redFlagRisk, backgroundColor: colorForRisk(deal.score.redFlagRisk) },
      { value: String(deal.score.recommendation).replace(/_/g, ' '), wrap: true },
    ]);
  }
  // Averages row, precomputed. write-excel-file's TS shape does not expose
  // formula cells, so we materialize the math instead of writing AVERAGE().
  if (deals.length) {
    const avg = (selector: (deal: TreeoDeal) => number): number => Math.round(
      (deals.reduce((sum, deal) => sum + selector(deal), 0) / deals.length) * 100,
    ) / 100;
    rows.push([
      { value: 'Averages', fontWeight: 'bold' },
      { type: Number, value: avg((d) => d.score.total) },
      { type: Number, value: avg((d) => d.score.confidence) },
      { type: Number, value: avg((d) => d.score.redFlagRisk) },
      { value: '' },
    ]);
  }
  return rows;
}

/**
 * Soft color scale on `total`. Aligns with the recommendation thresholds in
 * `scoring.ts` so analyst eyes match the math.
 */
function colorForScore(total: number): string {
  if (total >= 80) return '#D4EDD8';
  if (total >= 72) return '#E8F2DD';
  if (total >= 64) return '#FFF6D6';
  if (total >= 42) return '#FFE9CC';
  return '#FFE0E0';
}

function colorForRisk(risk: number): string {
  if (risk >= 60) return '#FFE0E0';
  if (risk >= 40) return '#FFF6D6';
  return '#E8F2DD';
}

function sheet(name: string, data: SheetData, opts: { columns?: Array<{ width?: number }> } = {}): Sheet<Blob> {
  return {
    sheet: name.slice(0, 31),
    data,
    columns: opts.columns,
    stickyRowsCount: 1,
  };
}

const STANDARD_COLUMNS = [{ width: 26 }, { width: 18 }, { width: 18 }, { width: 18 }, { width: 28 }];

export async function buildXlsxExport(deals: TreeoDeal[]): Promise<Blob> {
  const csv = buildCsvExports(deals);
  return writeXlsxFile([
    sheet('Summary', buildSummarySheet(deals), { columns: STANDARD_COLUMNS }),
    sheet('Scorecard', csvToSheetData(csv.scorecard), { columns: STANDARD_COLUMNS }),
    sheet('People', csvToSheetData(csv.people)),
    sheet('Companies', csvToSheetData(csv.companies)),
    sheet('Relationships', csvToSheetData(csv.relationships)),
    sheet('Investor Signals', csvToSheetData(csv.investorSignals)),
    sheet('HN Signals', csvToSheetData(csv.hnSignals)),
    sheet('GitHub Signals', csvToSheetData(csv.githubSignals)),
    sheet('YC Fit', csvToSheetData(csv.ycSignals)),
    sheet('Evidence', csvToSheetData(csv.evidence)),
  ]).toBlob();
}
