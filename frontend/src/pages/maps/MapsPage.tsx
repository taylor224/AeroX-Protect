import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { Plus, Save, Trash2 } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useIntl } from 'react-intl';
import { ImageOverlay, MapContainer, Marker, Popup, TileLayer, useMapEvents } from 'react-leaflet';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';

import { useAuthContext } from '@/auth/useAuthContext';
import { useConfirm } from '@/components/ConfirmProvider';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useFeatureFlag } from '@/lib/featureFlags';
import { CameraThumbnail } from '@/components/CameraThumbnail';
import { listCameras } from '@/pages/cameras/camera.api';
import { createGoogleSession, googleTileUrl } from '@/pages/maps/googleTiles';
import { createMap, deleteMap, getMap, getMapConfig, listMaps, replaceMarkers } from '@/pages/maps/map.api';
import type { MapMarker } from '@/types/p6';

const FP = 1000; // floorplan virtual extent (normalized x/y → [0,FP])
const SEOUL: [number, number] = [37.5665, 126.978];

const camIcon = (online: boolean) =>
  L.divIcon({
    className: '',
    html: `<div style="width:18px;height:18px;border-radius:50%;background:${online ? '#3E6AE1' : '#9CA3AF'};border:2px solid #fff;box-shadow:0 0 0 1px rgba(0,0,0,.35)"></div>`,
    iconSize: [18, 18],
    iconAnchor: [9, 9],
  });

function ClickToAdd({ onAdd }: { onAdd: (lat: number, lng: number) => void }) {
  useMapEvents({ click: (e) => onAdd(e.latlng.lat, e.latlng.lng) });
  return null;
}

export function MapsPage() {
  const intl = useIntl();
  const confirm = useConfirm();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { hasPermission } = useAuthContext();
  const enabled = useFeatureFlag('maps');
  const canEdit = hasPermission('maps', 'update');

  const [selectedId, setSelectedId] = useState('');
  const [editMode, setEditMode] = useState(false);
  const [placingCam, setPlacingCam] = useState('');
  const [markers, setMarkers] = useState<MapMarker[]>([]);
  const [createOpen, setCreateOpen] = useState(false);
  const [draft, setDraft] = useState({ name: '', kind: 'geo', image_url: '' });

  const mapsQuery = useQuery({ queryKey: ['maps'], queryFn: listMaps, enabled });
  const configQuery = useQuery({ queryKey: ['map-config'], queryFn: getMapConfig, enabled });
  const mapConfig = configQuery.data;
  const useGoogle = mapConfig?.provider === 'google' && !!mapConfig.google_api_key;

  // Google Map Tiles API needs a session token created once from the client key.
  const googleSessionQuery = useQuery({
    queryKey: ['google-tile-session'],
    queryFn: () => createGoogleSession(mapConfig!.google_api_key as string),
    enabled: enabled && useGoogle,
    staleTime: 60 * 60 * 1000, // sessions are long-lived; refetch hourly at most
    retry: 1,
  });
  const camerasQuery = useQuery({ queryKey: ['cameras'], queryFn: () => listCameras() });
  const cameras = camerasQuery.data?.items ?? [];
  const cameraById = useMemo(() => new Map(cameras.map((c) => [String(c.id), c])), [cameras]);

  const maps = mapsQuery.data ?? [];
  const mapId = selectedId || maps[0]?.id || '';
  const mapQuery = useQuery({ queryKey: ['map', mapId], queryFn: () => getMap(mapId), enabled: enabled && !!mapId });
  const theMap = mapQuery.data;

  useEffect(() => {
    setMarkers(theMap?.markers ?? []);
    setEditMode(false);
  }, [theMap]);

  const saveMut = useMutation({
    mutationFn: () => replaceMarkers(mapId, markers),
    onSuccess: () => {
      toast.success(intl.formatMessage({ id: 'map.saved' }));
      setEditMode(false);
      void queryClient.invalidateQueries({ queryKey: ['map', mapId] });
    },
    onError: () => toast.error(intl.formatMessage({ id: 'common.error' })),
  });
  const createMut = useMutation({
    mutationFn: () =>
      createMap({
        name: draft.name,
        kind: draft.kind as 'geo' | 'floorplan',
        image_url: draft.kind === 'floorplan' ? draft.image_url : undefined,
        config: draft.kind === 'geo' ? { center_lat: SEOUL[0], center_lng: SEOUL[1], zoom: 15 } : {},
      }),
    onSuccess: (m) => {
      setCreateOpen(false);
      setDraft({ name: '', kind: 'geo', image_url: '' });
      setSelectedId(m.id);
      void queryClient.invalidateQueries({ queryKey: ['maps'] });
    },
  });

  if (!enabled) {
    return (
      <Card className="mx-auto mt-10 max-w-lg p-10 text-center text-sm text-muted-foreground">
        {intl.formatMessage({ id: 'map.disabled' })}
      </Card>
    );
  }

  const isFloor = theMap?.kind === 'floorplan';
  const toPos = (m: MarkerLike): [number, number] => (isFloor ? [m.y * FP, m.x * FP] : [m.y, m.x]);
  const addMarker = (lat: number, lng: number) => {
    if (!editMode || !placingCam) return;
    const [y, x] = isFloor ? [lat / FP, lng / FP] : [lat, lng];
    setMarkers((prev) => [...prev, { camera_id: placingCam, x, y, label: cameraById.get(placingCam)?.name }]);
  };

  const center: [number, number] = theMap?.config?.center_lat
    ? [theMap.config.center_lat, theMap.config.center_lng ?? SEOUL[1]]
    : SEOUL;

  return (
    <div className="flex h-full flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="text-xl font-semibold tracking-tight text-foreground">{intl.formatMessage({ id: 'menu.maps' })}</h1>
        <select
          className="h-9 rounded border border-input bg-background px-2 text-sm"
          value={mapId}
          onChange={(e) => setSelectedId(e.target.value)}
        >
          {maps.length === 0 && <option value="">{intl.formatMessage({ id: 'map.none' })}</option>}
          {maps.map((m) => (
            <option key={m.id} value={m.id}>{m.name}</option>
          ))}
        </select>
        <div className="flex-1" />
        {canEdit && (
          <>
            <Button variant="outline" size="sm" onClick={() => setCreateOpen(true)}>
              <Plus className="mr-1 h-4 w-4" />
              {intl.formatMessage({ id: 'map.new' })}
            </Button>
            {theMap && (
              <>
                <Button variant={editMode ? 'ghost' : 'outline'} size="sm" onClick={() => setEditMode((v) => !v)}>
                  {intl.formatMessage({ id: editMode ? 'common.cancel' : 'map.edit' })}
                </Button>
                {editMode && (
                  <Button size="sm" onClick={() => saveMut.mutate()}>
                    <Save className="mr-1 h-4 w-4" />
                    {intl.formatMessage({ id: 'common.save' })}
                  </Button>
                )}
                <Button variant="ghost" size="icon" onClick={async () => {
                  if (await confirm({
                    title: intl.formatMessage({ id: 'confirm.delete.title' }),
                    description: intl.formatMessage({ id: 'confirm.delete.named' }, { name: theMap.name }),
                    confirmLabel: intl.formatMessage({ id: 'common.delete' }),
                    destructive: true,
                  }))
                    deleteMap(theMap.id).then(() => { setSelectedId(''); void queryClient.invalidateQueries({ queryKey: ['maps'] }); });
                }}>
                  <Trash2 className="h-4 w-4 text-destructive" />
                </Button>
              </>
            )}
          </>
        )}
      </div>

      {editMode && (
        <Card className="flex flex-wrap items-center gap-2 p-2 text-sm">
          <span className="text-muted-foreground">{intl.formatMessage({ id: 'map.place_hint' })}</span>
          <select className="h-8 rounded border border-input bg-background px-2 text-sm" value={placingCam}
            onChange={(e) => setPlacingCam(e.target.value)}>
            <option value="">{intl.formatMessage({ id: 'map.pick_camera' })}</option>
            {cameras.map((c) => <option key={c.uuid} value={String(c.id)}>{c.name}</option>)}
          </select>
        </Card>
      )}

      <div className="min-h-0 flex-1 overflow-hidden rounded-lg border border-border">
        {!theMap ? (
          <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
            {intl.formatMessage({ id: 'map.empty' })}
          </div>
        ) : (
          <MapContainer
            key={`${theMap.id}-${isFloor}`}
            center={isFloor ? [FP / 2, FP / 2] : center}
            zoom={isFloor ? 0 : (theMap.config?.zoom ?? 15)}
            crs={isFloor ? L.CRS.Simple : L.CRS.EPSG3857}
            minZoom={isFloor ? -2 : 3}
            className="h-full w-full"
            style={{ background: '#0b0b0c' }}
          >
            {isFloor ? (
              theMap.image_url && (
                <ImageOverlay url={theMap.image_url} bounds={[[0, 0], [FP, FP]]} />
              )
            ) : useGoogle && googleSessionQuery.data ? (
              <TileLayer
                key="google"
                attribution="&copy; Google"
                url={googleTileUrl(googleSessionQuery.data, mapConfig!.google_api_key as string)}
              />
            ) : (
              <TileLayer
                key="osm"
                attribution="&copy; OpenStreetMap"
                url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
              />
            )}
            {editMode && <ClickToAdd onAdd={addMarker} />}
            {markers.map((m, i) => {
              const cam = cameraById.get(String(m.camera_id));
              return (
                <Marker key={m.id ?? i} position={toPos(m)} icon={camIcon((cam?.status ?? '') === 'online')}>
                  <Popup>
                    <div className="w-44 space-y-1">
                      {cam && (
                        <CameraThumbnail cameraUuid={cam.uuid} status={cam.status} className="aspect-video w-full rounded" />
                      )}
                      <div className="text-sm font-medium">{cam?.name ?? m.label}</div>
                      {editMode ? (
                        <button className="text-xs text-red-500" onClick={() => setMarkers((p) => p.filter((_, j) => j !== i))}>
                          {intl.formatMessage({ id: 'common.delete' })}
                        </button>
                      ) : (
                        cam && (
                          <button className="text-xs text-primary" onClick={() => navigate(`/events?camera=${cam.uuid}`)}>
                            {intl.formatMessage({ id: 'map.view_live' })}
                          </button>
                        )
                      )}
                    </div>
                  </Popup>
                </Marker>
              );
            })}
          </MapContainer>
        )}
      </div>

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent className="max-w-sm">
          <DialogHeader><DialogTitle>{intl.formatMessage({ id: 'map.new' })}</DialogTitle></DialogHeader>
          <div className="space-y-3 py-1">
            <div className="space-y-1.5">
              <Label>{intl.formatMessage({ id: 'map.name' })}</Label>
              <Input value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
            </div>
            <div className="space-y-1.5">
              <Label>{intl.formatMessage({ id: 'map.kind' })}</Label>
              <select className="h-10 w-full rounded border border-input bg-background px-2 text-sm" value={draft.kind}
                onChange={(e) => setDraft({ ...draft, kind: e.target.value })}>
                <option value="geo">{intl.formatMessage({ id: 'map.kind.geo' })}</option>
                <option value="floorplan">{intl.formatMessage({ id: 'map.kind.floorplan' })}</option>
              </select>
            </div>
            {draft.kind === 'floorplan' && (
              <div className="space-y-1.5">
                <Label>{intl.formatMessage({ id: 'map.image_url' })}</Label>
                <Input value={draft.image_url} onChange={(e) => setDraft({ ...draft, image_url: e.target.value })} placeholder="https://…/floor.png" />
              </div>
            )}
          </div>
          <DialogFooter>
            <Button variant="ghost" size="sm" onClick={() => setCreateOpen(false)}>{intl.formatMessage({ id: 'common.cancel' })}</Button>
            <Button size="sm" disabled={!draft.name || createMut.isPending} onClick={() => createMut.mutate()}>{intl.formatMessage({ id: 'common.save' })}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

interface MarkerLike {
  x: number;
  y: number;
}
