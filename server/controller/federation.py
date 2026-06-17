"""Federation members + aggregated views (PLAN P8). Member CRUD needs `federation:manage`;
the aggregated camera/event views need `federation:read`. Flag-gated by `federation`.
Member api_tokens are write-only (Fernet at rest, never returned).
"""
from server.exception import InvalidParameterException, NoPermissionException, RowNotFoundException
from server.model.federation_camera import FederationCamera
from server.model.federation_member import FederationMember
from server.service import federation, feature_flag


def _guard():
    if not feature_flag.is_enabled('federation'):
        raise NoPermissionException('feature_disabled')


class FederationController:
    @classmethod
    def list_members(cls) -> list[dict]:
        _guard()
        return [m.to_dict() for m in FederationMember.list_all()]

    @classmethod
    def create_member(cls, data: dict, actor) -> dict:
        _guard()
        name = (data.get('name') or '').strip()
        base_url = (data.get('base_url') or '').strip()
        token = (data.get('token') or '').strip()
        if not name or not base_url:
            raise InvalidParameterException('name and base_url required')
        if not base_url.startswith(('http://', 'https://')):
            raise InvalidParameterException('base_url must be http(s)')
        if not token:
            raise InvalidParameterException('api token required')
        m = FederationMember.create(name=name, base_url=base_url, token=token, actor_id=actor.id)
        return m.to_dict()

    @classmethod
    def update_member(cls, member_id, data: dict, actor) -> dict:
        _guard()
        m = FederationMember.get_by_id(member_id)
        if not m:
            raise RowNotFoundException()
        return m.modify(data, actor_id=actor.id).to_dict()

    @classmethod
    def delete_member(cls, member_id, actor):
        _guard()
        m = FederationMember.get_by_id(member_id)
        if not m:
            raise RowNotFoundException()
        FederationCamera.delete_for_member(m.id)
        m.soft_delete(actor_id=actor.id)

    @classmethod
    def sync_member(cls, member_id) -> dict:
        _guard()
        m = FederationMember.get_by_id(member_id)
        if not m:
            raise RowNotFoundException()
        result = federation.sync_member(m.id)
        return {**FederationMember.get_by_id(member_id).to_dict(), 'sync': result}

    @classmethod
    def aggregate_cameras(cls) -> dict:
        _guard()
        return {'cameras': federation.aggregate_cameras()}

    @classmethod
    def aggregate_events(cls, args) -> dict:
        _guard()
        params = {}
        if args.get('type'):
            params['type'] = args.get('type')
        if args.get('items_per_page'):
            params['items_per_page'] = args.get('items_per_page')
        return {'events': federation.aggregate_events(params)}
