import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Shield, Trash2 } from 'lucide-react';
import { useRef, useState } from 'react';
import { useIntl } from 'react-intl';
import { toast } from 'sonner';

import { useConfirm } from '@/components/ConfirmProvider';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { createMask, deleteMask, listMasks } from '@/pages/cameras/mask.api';
import { frameUrl } from '@/pages/playback/playback.api';

const toPoints = (poly: [number, number][]) => poly.map(([x, y]) => `${x * 100},${y * 100}`).join(' ');

/** Draw privacy-mask polygons on a camera snapshot (click to add vertices). Mirrors the
 *  P4 ZoneEditor interaction. */
export function MaskEditButton({ cameraUuid }: { cameraUuid: string }) {
  const intl = useIntl();
  const confirm = useConfirm();
  const queryClient = useQueryClient();
  const boxRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [pts, setPts] = useState<[number, number][]>([]);
  const [name, setName] = useState('');
  const [anchor] = useState(() => Date.now() - 5000);

  const masksQuery = useQuery({ queryKey: ['masks', cameraUuid], queryFn: () => listMasks(cameraUuid), enabled: open });
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['masks', cameraUuid] });

  const saveMut = useMutation({
    mutationFn: () => createMask(cameraUuid, { name: name.trim() || 'mask', polygon: pts }),
    onSuccess: () => {
      toast.success(intl.formatMessage({ id: 'mask.saved' }));
      setPts([]);
      setName('');
      invalidate();
    },
    onError: () => toast.error(intl.formatMessage({ id: 'common.error' })),
  });
  const delMut = useMutation({ mutationFn: (id: string) => deleteMask(id), onSuccess: invalidate });

  const addPoint = (e: React.MouseEvent) => {
    const rect = boxRef.current?.getBoundingClientRect();
    if (!rect) return;
    const x = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
    const y = Math.min(1, Math.max(0, (e.clientY - rect.top) / rect.height));
    setPts((p) => [...p, [Number(x.toFixed(4)), Number(y.toFixed(4))]]);
  };

  const masks = masksQuery.data ?? [];

  return (
    <>
      <Button variant="ghost" size="icon" onClick={() => setOpen(true)}
        title={intl.formatMessage({ id: 'camera.masks' })} aria-label="masks">
        <Shield className="h-4 w-4" />
      </Button>

      <Dialog
        open={open}
        onOpenChange={(o) => {
          setOpen(o);
          if (!o) {
            setPts([]);
            setName('');
          }
        }}
      >
        <DialogContent className="max-h-[92vh] w-[95vw] max-w-5xl overflow-auto">
          <DialogHeader>
            <DialogTitle>{intl.formatMessage({ id: 'mask.title' })}</DialogTitle>
          </DialogHeader>

          <div
            ref={boxRef}
            onClick={addPoint}
            className="relative aspect-video w-full cursor-crosshair overflow-hidden rounded-lg bg-black"
          >
            <img
              src={frameUrl(cameraUuid, anchor)}
              alt=""
              className="h-full w-full object-contain opacity-80"
              onError={(e) => ((e.target as HTMLImageElement).style.visibility = 'hidden')}
            />
            <svg className="pointer-events-none absolute inset-0 h-full w-full" viewBox="0 0 100 100" preserveAspectRatio="none">
              {masks.map((m) => (
                <polygon key={m.id} points={toPoints(m.polygon)} fill="black" fillOpacity={0.7} stroke="white" strokeWidth={0.3} />
              ))}
              {pts.length > 0 && <polygon points={toPoints(pts)} fill="#3E6AE133" stroke="#3E6AE1" strokeWidth={0.5} />}
              {pts.map(([x, y], i) => (
                <circle key={i} cx={x * 100} cy={y * 100} r={0.7} fill="#3E6AE1" />
              ))}
            </svg>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={intl.formatMessage({ id: 'mask.name' })}
              className="w-44"
            />
            <Button variant="ghost" size="sm" onClick={() => setPts([])} disabled={!pts.length}>
              {intl.formatMessage({ id: 'mask.clear' })}
            </Button>
            <Button size="sm" onClick={() => saveMut.mutate()} disabled={pts.length < 3 || saveMut.isPending}>
              {intl.formatMessage({ id: 'common.save' })}
            </Button>
            <span className="text-xs text-muted-foreground">{intl.formatMessage({ id: 'mask.hint' })}</span>
          </div>

          <div className="max-h-40 space-y-1 overflow-auto">
            {masks.map((m) => (
              <div key={m.id} className="flex items-center justify-between rounded border border-border px-2 py-1 text-sm">
                <span className="flex items-center gap-2">
                  <span className="h-3 w-3 rounded-sm bg-black ring-1 ring-border" />
                  {m.name}
                  {!m.enabled && <span className="text-xs text-muted-foreground">(off)</span>}
                </span>
                <Button variant="ghost" size="icon" onClick={async () => {
                  if (await confirm({
                    title: intl.formatMessage({ id: 'confirm.delete.title' }),
                    description: intl.formatMessage({ id: 'confirm.delete.named' }, { name: m.name }),
                    confirmLabel: intl.formatMessage({ id: 'common.delete' }),
                    destructive: true,
                  }))
                    delMut.mutate(m.id);
                }} aria-label="delete">
                  <Trash2 className="h-4 w-4 text-destructive" />
                </Button>
              </div>
            ))}
            {masks.length === 0 && (
              <p className="py-3 text-center text-xs text-muted-foreground">
                {intl.formatMessage({ id: 'mask.empty' })}
              </p>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
