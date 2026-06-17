"""Maps + markers CRUD (PLAN P6 L6). Flag-gated (`maps`). Maps are an admin-configured
layout; live access from a marker is separately camera-scoped at the live endpoint.
"""
from server.exception import InvalidParameterException, NoPermissionException, RowNotFoundException
from server.model.map_config import MapConfig
from server.model.site_map import KINDS, MapMarker, SiteMap
from server.service import feature_flag


def _guard():
    if not feature_flag.is_enabled('maps'):
        raise NoPermissionException('feature_disabled')


def _require(map_id) -> SiteMap:
    m = SiteMap.get_by_id(map_id)
    if not m:
        raise RowNotFoundException()
    return m


class MapController:
    @classmethod
    def list_maps(cls) -> list[dict]:
        _guard()
        return [m.to_dict() for m in SiteMap.list_all()]

    @classmethod
    def get_map(cls, map_id) -> dict:
        _guard()
        return _require(map_id).to_dict(with_markers=True)

    @classmethod
    def create_map(cls, data: dict, actor) -> dict:
        _guard()
        if not data.get('name') or (data.get('kind') and data['kind'] not in KINDS):
            raise InvalidParameterException('name and valid kind (geo/floorplan) required')
        return SiteMap.create(data, actor.id).to_dict()

    @classmethod
    def update_map(cls, map_id, data: dict, actor) -> dict:
        _guard()
        return _require(map_id).modify(data, actor.id).to_dict()

    @classmethod
    def delete_map(cls, map_id):
        _guard()
        _require(map_id).soft_delete()

    @classmethod
    def replace_markers(cls, map_id, markers: list) -> dict:
        _guard()
        m = _require(map_id)
        if not isinstance(markers, list):
            raise InvalidParameterException('markers must be a list')
        for mk in markers:
            if 'camera_id' not in mk or 'x' not in mk or 'y' not in mk:
                raise InvalidParameterException('each marker needs camera_id, x, y')
        MapMarker.replace_for_map(m.id, markers)
        return m.to_dict(with_markers=True)

    # ── provider config (OSM / Google) ─────────────────────────────────────────
    @classmethod
    def get_config(cls) -> dict:
        """Map base-layer config for any maps:read user — includes the Google client key
        (referrer-restricted, the browser SDK needs it)."""
        _guard()
        return MapConfig.ensure().to_dict(with_key=True)

    @classmethod
    def update_config(cls, data: dict, actor) -> dict:
        _guard()
        return MapConfig.update(data, actor.id).to_dict(with_key=True)
