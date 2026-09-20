import { toApiCase } from '../../../api/datasets';
import type { DatasetVersion } from '../types/index';

export function exportSamples(version: DatasetVersion, ids?: string[]) {
  const selected = ids ? new Set(ids) : null;
  const cases = version.cases.filter((item) => !selected || selected.has(item.id)).map(toApiCase);
  if (!cases.length) throw new Error('请选择至少一个样本');
  // A subset is a sample collection, not a published version with its original content hash.
  return { dataset_name: version.dataset_name, source_version: version.version, cases };
}
export function sampleRows(
  version: DatasetVersion,
  ids?: string[],
): Record<string, string | number>[] {
  return exportSamples(version, ids).cases.flatMap((item) =>
    item.turns.map((turn, index) => ({
      case_id: item.id,
      case_name: item.name,
      category: item.category,
      difficulty: item.difficulty,
      tags_json: JSON.stringify(item.tags),
      case_notes: item.notes,
      initial_state_json: JSON.stringify(item.initial_state),
      turn_id: turn.id,
      turn_order: index + 1,
      input_json: JSON.stringify(turn.input),
      expectations_json: JSON.stringify(turn.expectations),
      turn_notes: turn.notes,
    })),
  );
}
export async function sampleExportBlob(
  version: DatasetVersion,
  ids: string[] | undefined,
  format: 'json' | 'xlsx',
): Promise<Blob> {
  if (format === 'json')
    return new Blob([JSON.stringify(exportSamples(version, ids), null, 2)], {
      type: 'application/json',
    });
  const ExcelJS = await import('exceljs');
  const book = new ExcelJS.default.Workbook();
  const sheet = book.addWorksheet('Cases');
  const rows = sampleRows(version, ids);
  sheet.columns = Object.keys(rows[0]).map((key) => ({
    header: key,
    key,
    width: key.includes('json') ? 45 : 24,
  }));
  rows.forEach((row) => sheet.addRow(row));
  sheet.getRow(1).font = { bold: true };
  sheet.views = [{ state: 'frozen', ySplit: 1 }];
  return new Blob([new Uint8Array(await book.xlsx.writeBuffer())], {
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  });
}
