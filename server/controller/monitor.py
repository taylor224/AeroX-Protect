from server.exception import InvalidParameterException, RowNotFoundException
from server.model.camera import Camera
from server.model.dashboard import Dashboard
from server.model.monitor import STATUS_REVOKED, Monitor
from server.service import pairing_code


def _dash_uuid(monitor) -> str | None:
    d = Dashboard.get_by_id(monitor.dashboard_id)
    return d.uuid if d else None


class MonitorController:
    @classmethod
    def list_monitors(cls) -> list[dict]:
        out = []
        for m in Monitor.list_all():
            d = m.to_dict()
            d['dashboard_uuid'] = _dash_uuid(m)
            out.append(d)
        return out

    @classmethod
    def create(cls, data: dict, actor) -> dict:
        if not data.get('name') or not data.get('dashboard_uuid'):
            raise InvalidParameterException('name and dashboard_uuid required')
        dash = Dashboard.get_by_uuid(data['dashboard_uuid'])
        m = Monitor.create(data['name'], dash.id, actor_id=actor.id,
                           settings=data.get('settings'), device_label=data.get('device_label'))
        return {**m.to_dict(), 'dashboard_uuid': dash.uuid}

    @classmethod
    def update(cls, uuid: str, data: dict, actor) -> dict:
        m = cls._require(uuid)
        fields = {}
        for f in ('name', 'settings', 'rotation', 'device_label'):
            if f in data:
                fields[f] = data[f]
        if data.get('dashboard_uuid'):
            dash = Dashboard.get_by_uuid(data['dashboard_uuid'])
            if dash.id != m.dashboard_id:
                fields['dashboard_id'] = dash.id
                m.update(**fields)
                m.bump_token_version()               # dashboard change invalidates tokens
                return {**m.to_dict(), 'dashboard_uuid': dash.uuid}
        if fields:
            m.update(**fields)
        return {**m.to_dict(), 'dashboard_uuid': _dash_uuid(m)}

    @classmethod
    def delete(cls, uuid: str):
        cls._require(uuid).soft_delete()

    @classmethod
    def pair_code(cls, uuid: str, ip, actor) -> dict:
        m = cls._require(uuid)
        result = pairing_code.issue(m, ip=ip, actor_id=actor.id)
        from server.model import to_epoch_ms
        return {'code': result['code'], 'expires_in': result['expires_in'],
                'expires_at': to_epoch_ms(result['expires_at'])}

    @classmethod
    def revoke(cls, uuid: str) -> dict:
        m = cls._require(uuid)
        m.update(status=STATUS_REVOKED)
        m.bump_token_version()
        return m.to_dict()

    @staticmethod
    def _require(uuid) -> Monitor:
        m = Monitor.get_by_uuid(uuid)
        if not m:
            raise RowNotFoundException()
        return m


class PairingController:
    @classmethod
    def claim(cls, code: str, ip, ua) -> dict:
        monitor, pair = pairing_code.claim(code, ip=ip, ua=ua)
        return {
            'monitor': {'uuid': monitor.uuid, 'name': monitor.name, 'dashboard_uuid': _dash_uuid(monitor)},
            'access_token': pair['access_token'], 'refresh_token': pair['refresh_token'],
            'token_type': 'Bearer', 'expires_in': pair['expires_in'],
        }

    @classmethod
    def me(cls, monitor) -> dict:
        dash = Dashboard.get_by_id(monitor.dashboard_id)
        cameras = []
        if dash:
            for cell in (dash.layout or {}).get('cells', []):     # dashboard layout = {grid, cells[], ratio_mode}
                cam_uuid = cell.get('camera_uuid')
                if not cam_uuid:
                    continue
                try:
                    cam = Camera.get_by_uuid(cam_uuid)
                except RowNotFoundException:
                    continue
                streams = [{'role': s.role, 'go2rtc_name': s.go2rtc_name}
                           for s in cam.streams if not s.deleted_at]
                cameras.append({'uuid': cam.uuid, 'name': cam.name, 'streams': streams})
        return {
            'monitor': {'uuid': monitor.uuid, 'name': monitor.name, 'settings': monitor.settings},
            'dashboard': {'uuid': dash.uuid, 'layout': dash.layout} if dash else None,
            'cameras': cameras,
        }

    @classmethod
    def heartbeat(cls, monitor) -> dict:
        from server.model import to_epoch_ms, utcnow
        monitor.update(last_seen_at=utcnow())
        return {'server_time': to_epoch_ms(utcnow()),
                'dashboard_version': to_epoch_ms(monitor.updated_at)}
