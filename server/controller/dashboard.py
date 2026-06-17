from server.exception import InvalidParameterException, NoPermissionException, RowNotFoundException
from server.model.camera import Camera
from server.model.dashboard import RATIO_MODES, Dashboard
from server.model.dashboard_acl import ACCESS_EDIT, ACCESS_VIEW, DashboardAcl
from server.service.permission import PermissionService


def _validate_page(page: dict) -> None:
    """Validate one grid page: bounds, unique cell ids, known cameras."""
    grid = page.get('grid') or {}
    cols = int(grid.get('cols', 12))
    rows = int(grid.get('rows', 8))
    cells = page.get('cells', [])
    if not isinstance(cells, list):
        raise InvalidParameterException('layout.cells must be a list')

    seen_ids = set()
    for cell in cells:
        if not isinstance(cell, dict):
            raise InvalidParameterException('each cell must be an object')
        cid = cell.get('i')
        if cid in seen_ids:
            raise InvalidParameterException('duplicate cell id: %s' % cid)
        seen_ids.add(cid)
        x, y, w, h = cell.get('x', 0), cell.get('y', 0), cell.get('w', 1), cell.get('h', 1)
        if not all(isinstance(v, int) for v in (x, y, w, h)):
            raise InvalidParameterException('cell x/y/w/h must be integers')
        if x < 0 or y < 0 or w < 1 or h < 1 or x + w > cols or y + h > rows:
            raise InvalidParameterException('cell out of grid bounds: %s' % cid)
        rm = cell.get('ratio_mode')
        if rm is not None and rm not in RATIO_MODES:
            raise InvalidParameterException('invalid ratio_mode: %s' % rm)
        cam_uuid = cell.get('camera_uuid')
        if cam_uuid:
            try:
                Camera.get_by_uuid(cam_uuid)
            except RowNotFoundException:
                raise InvalidParameterException('unknown camera in cell: %s' % cam_uuid)


def validate_layout(layout: dict) -> dict:
    """Validate the dashboard layout JSON (PLAN P1 §4.7). Supports both the legacy single-page
    shape ({grid, cells}) and the multi-page shape ({pages:[{name,grid,cells}], sequence})."""
    if not isinstance(layout, dict):
        raise InvalidParameterException('layout must be an object')
    pages = layout.get('pages')
    if pages is not None:
        if not isinstance(pages, list) or not pages:
            raise InvalidParameterException('layout.pages must be a non-empty list')
        for page in pages:
            if not isinstance(page, dict):
                raise InvalidParameterException('each page must be an object')
            _validate_page(page)
        seq = layout.get('sequence')
        if seq is not None:
            if not isinstance(seq, dict):
                raise InvalidParameterException('layout.sequence must be an object')
            if seq.get('dwell_s') is not None and int(seq['dwell_s']) < 2:
                raise InvalidParameterException('sequence.dwell_s must be >= 2')
    else:
        _validate_page(layout)
    return layout


class DashboardController:
    @staticmethod
    def _access_level(user, dashboard: Dashboard) -> str | None:
        if PermissionService.is_superuser(user) or dashboard.owner_id == user.id:
            return ACCESS_EDIT
        return DashboardAcl.get_access(dashboard.id, user.id)

    @classmethod
    def _require(cls, user, dashboard, need=ACCESS_VIEW) -> str:
        level = cls._access_level(user, dashboard)
        if level is None:
            raise NoPermissionException('dashboard_access_denied')
        if need == ACCESS_EDIT and level != ACCESS_EDIT:
            raise NoPermissionException('dashboard_edit_denied')
        return level

    @classmethod
    def _require_owner(cls, user, dashboard):
        if not (PermissionService.is_superuser(user) or dashboard.owner_id == user.id):
            raise NoPermissionException('dashboard_owner_required')

    @classmethod
    def get_list(cls, user) -> list[dict]:
        is_admin = PermissionService.is_superuser(user)
        rows = Dashboard.get_accessible(user.id, is_admin)
        out = []
        for d in rows:
            item = d.to_dict(with_layout=False)
            item['access'] = cls._access_level(user, d)
            out.append(item)
        return out

    @classmethod
    def get(cls, user, dashboard_uuid: str) -> dict:
        dashboard = Dashboard.get_by_uuid(dashboard_uuid)
        level = cls._require(user, dashboard, ACCESS_VIEW)
        acl = [a.to_dict() for a in DashboardAcl.list_for_dashboard(dashboard.id)]
        data = dashboard.to_dict(with_layout=True, acl=acl)
        data['access'] = level
        return data

    @classmethod
    def create(cls, user, data: dict) -> dict:
        name = (data.get('name') or '').strip()
        if not name:
            raise InvalidParameterException('name required')
        layout = validate_layout(data.get('layout') or {'version': 1, 'grid': {'cols': 12, 'rows': 8}, 'cells': []})
        ratio = data.get('default_ratio_mode') or 'fit'
        if ratio not in RATIO_MODES:
            raise InvalidParameterException('invalid default_ratio_mode')
        dashboard = Dashboard.create(
            name=name, layout=layout, owner_id=user.id, description=data.get('description'),
            default_ratio_mode=ratio, is_shared=bool(data.get('is_shared')), created_by_id=user.id)
        return dashboard.to_dict(with_layout=True)

    @classmethod
    def update(cls, user, dashboard_uuid: str, data: dict) -> dict:
        dashboard = Dashboard.get_by_uuid(dashboard_uuid)
        cls._require(user, dashboard, ACCESS_EDIT)
        layout = None
        if data.get('layout') is not None:
            layout = validate_layout(data['layout'])
        ratio = data.get('default_ratio_mode')
        if ratio is not None and ratio not in RATIO_MODES:
            raise InvalidParameterException('invalid default_ratio_mode')
        dashboard.modify(name=data.get('name'), description=data.get('description'), layout=layout,
                         default_ratio_mode=ratio, is_shared=data.get('is_shared'), updated_by_id=user.id)
        return dashboard.to_dict(with_layout=True)

    @classmethod
    def delete(cls, user, dashboard_uuid: str):
        dashboard = Dashboard.get_by_uuid(dashboard_uuid)
        cls._require_owner(user, dashboard)
        DashboardAcl.delete_for_dashboard(dashboard.id)
        dashboard.soft_delete(deleted_by_id=user.id)

    @classmethod
    def set_acl(cls, user, dashboard_uuid: str, data: dict) -> dict:
        dashboard = Dashboard.get_by_uuid(dashboard_uuid)
        cls._require_owner(user, dashboard)
        target_user_id = data.get('user_id')
        access = data.get('access') or ACCESS_VIEW
        if not target_user_id:
            raise InvalidParameterException('user_id required')
        if access not in (ACCESS_VIEW, ACCESS_EDIT):
            raise InvalidParameterException('access must be view or edit')
        DashboardAcl.upsert(dashboard.id, int(target_user_id), access)
        if not dashboard.is_shared:
            dashboard.modify(is_shared=True, updated_by_id=user.id)
        return {'user_id': str(target_user_id), 'access': access}

    @classmethod
    def remove_acl(cls, user, dashboard_uuid: str, target_user_id):
        dashboard = Dashboard.get_by_uuid(dashboard_uuid)
        cls._require_owner(user, dashboard)
        DashboardAcl.remove(dashboard.id, int(target_user_id))
