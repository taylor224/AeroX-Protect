import type { DashboardLayout } from '@/types/axp';

const ROW_SPAN = 4;

/** Build a uniform C×R grid layout on the 12-column system (presets 1/4/6/9/16). */
export function makeUniformLayout(cols: number, rows: number, existing?: (string | null | undefined)[]): DashboardLayout {
  const colSpan = Math.floor(12 / cols);
  const gridCols = colSpan * cols;
  const gridRows = ROW_SPAN * rows;
  const cells = [];
  let idx = 0;
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      cells.push({
        i: `c${idx}`,
        camera_uuid: existing?.[idx] ?? null,
        x: c * colSpan,
        y: r * ROW_SPAN,
        w: colSpan,
        h: ROW_SPAN,
      });
      idx++;
    }
  }
  return { version: 1, grid: { cols: gridCols, rows: gridRows, gap: 4 }, ratio_mode: 'fit', cells };
}

export const LAYOUT_PRESETS = [
  { key: '1', label: '1', cols: 1, rows: 1 },
  { key: '4', label: '4', cols: 2, rows: 2 },
  { key: '6', label: '6', cols: 3, rows: 2 },
  { key: '9', label: '9', cols: 3, rows: 3 },
  { key: '16', label: '16', cols: 4, rows: 4 },
];

export function presetLayout(key: string, existing?: (string | null | undefined)[]): DashboardLayout {
  const preset = LAYOUT_PRESETS.find((p) => p.key === key) ?? LAYOUT_PRESETS[1];
  return makeUniformLayout(preset.cols, preset.rows, existing);
}
