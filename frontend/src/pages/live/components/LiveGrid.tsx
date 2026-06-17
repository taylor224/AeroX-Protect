import { useEffect, useRef, useState } from 'react';
import GridLayout, { WidthProvider, type Layout } from 'react-grid-layout';

import { CameraTile } from '@/pages/live/components/CameraTile';
import type { Camera, DashboardLayout } from '@/types/axp';

import 'react-grid-layout/css/styles.css';
import 'react-resizable/css/styles.css';

const RGL = WidthProvider(GridLayout);
const MARGIN = 4;

/**
 * Live camera wall. In view mode the grid is static (just plays). In edit mode every tile can
 * be dragged to rearrange and resized from its edges/corners to span more cells (react-grid-layout).
 * Row height is derived so the whole wall fills the available height without scrolling.
 */
export function LiveGrid({
  layout,
  cameras,
  editMode = false,
  showNames = false,
  spotlightUuids,
  audioOn,
  onToggleAudio,
  onChange,
  onAssignCell,
  onEnlarge,
}: {
  layout: DashboardLayout;
  cameras: Map<string, Camera>;
  editMode?: boolean;
  showNames?: boolean;
  spotlightUuids?: Set<string>;
  audioOn?: Set<string>;
  onToggleAudio?: (cameraUuid: string) => void;
  onChange?: (layout: DashboardLayout) => void;
  onAssignCell?: (cellId: string) => void;
  onEnlarge?: (cameraUuid: string) => void;
}) {
  const cols = layout.grid?.cols ?? 12;
  const rows = Math.max(1, layout.grid?.rows ?? 8);
  const cells = layout.cells ?? [];

  const ref = useRef<HTMLDivElement>(null);
  const [rowHeight, setRowHeight] = useState(80);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const update = () => setRowHeight(Math.max(20, (el.clientHeight - (rows + 1) * MARGIN) / rows));
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, [rows]);

  const rglLayout: Layout[] = cells.map((c) => ({ i: c.i, x: c.x, y: c.y, w: c.w, h: c.h }));

  const handleLayoutChange = (next: Layout[]) => {
    if (!editMode || !onChange) return;
    const byId = new Map(next.map((l) => [l.i, l]));
    let changed = false;
    const merged = cells.map((c) => {
      const l = byId.get(c.i);
      if (l && (l.x !== c.x || l.y !== c.y || l.w !== c.w || l.h !== c.h)) {
        changed = true;
        return { ...c, x: l.x, y: l.y, w: l.w, h: l.h };
      }
      return c;
    });
    if (changed) onChange({ ...layout, cells: merged });
  };

  return (
    <div ref={ref} className="h-full w-full overflow-hidden">
      <RGL
        className="h-full"
        layout={rglLayout}
        cols={cols}
        maxRows={rows}
        rowHeight={rowHeight}
        margin={[MARGIN, MARGIN]}
        containerPadding={[0, 0]}
        isDraggable={editMode}
        isResizable={editMode}
        compactType="vertical"
        resizeHandles={['se', 'e', 's']}
        draggableCancel=".rgl-no-drag"
        onLayoutChange={handleLayoutChange}
      >
        {cells.map((cell) => (
          <div key={cell.i} className="overflow-hidden">
            <CameraTile
              camera={cell.camera_uuid ? cameras.get(cell.camera_uuid) : undefined}
              ratioMode={cell.ratio_mode ?? layout.ratio_mode ?? 'fit'}
              editMode={editMode}
              showName={showNames}
              spotlight={!!cell.camera_uuid && !!spotlightUuids?.has(cell.camera_uuid)}
              audioOn={!!cell.camera_uuid && !!audioOn?.has(cell.camera_uuid)}
              onToggleAudio={() => cell.camera_uuid && onToggleAudio?.(cell.camera_uuid)}
              onEnlarge={() => cell.camera_uuid && onEnlarge?.(cell.camera_uuid)}
              onRemove={() =>
                onChange?.({
                  ...layout,
                  cells: cells.map((c) => (c.i === cell.i ? { ...c, camera_uuid: null } : c)),
                })
              }
              onClickEmpty={() => onAssignCell?.(cell.i)}
            />
          </div>
        ))}
      </RGL>
    </div>
  );
}
