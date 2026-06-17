"""Face identities + observations (PLAN P7 A8). Identity CRUD + enroll-from-observation
(promote an observed face to a reference embedding). Observations are camera-scoped; search
spans the caller's allowed cameras. Privacy: identities carry consent + right-to-erasure
(soft delete wipes embeddings). Flag-gated by `face`.
"""
from server.exception import InvalidParameterException, NoPermissionException, RowNotFoundException
from server.model.camera import Camera
from server.model.face_identity import FaceIdentity
from server.model.face_observation import FaceObservation
from server.service import feature_flag
from server.service.permission import PermissionService
from server.util.tool import safe_int


def _guard():
    if not feature_flag.is_enabled('face'):
        raise NoPermissionException('feature_disabled')


def _scoped_camera(user, camera_uuid: str) -> Camera:
    camera = Camera.get_by_uuid(camera_uuid)
    if not PermissionService.has_camera_scope(user, camera.uuid, 'view'):
        raise NoPermissionException('camera_scope_denied')
    return camera


def _allowed_camera_ids(user) -> set[int] | None:
    if PermissionService.is_superuser(user):
        return None
    scope = PermissionService._merged_scope(user, 'camera_scope')
    star = scope.get('*')
    if star and ('view' in star or '*' in star):
        return None
    allowed: set[int] = set()
    for uuid, actions in scope.items():
        if uuid == '*':
            continue
        if 'view' in actions or '*' in actions:
            cam = Camera.get_by_uuid(uuid)
            if cam:
                allowed.add(cam.id)
    return allowed


class FaceController:
    # ── identities ────────────────────────────────────────────────────────────
    @classmethod
    def list_identities(cls, user) -> list[dict]:
        _guard()
        return [i.to_dict() for i in FaceIdentity.list_all()]

    @classmethod
    def create_identity(cls, user, data: dict) -> dict:
        _guard()
        name = (data.get('name') or '').strip()
        if not name:
            raise InvalidParameterException('name required')
        ident = FaceIdentity.create(name=name[:120], note=data.get('note'),
                                    consent=bool(data.get('consent')),
                                    retention_days=data.get('retention_days'), actor_id=user.id)
        return ident.to_dict()

    @classmethod
    def update_identity(cls, user, identity_id, data: dict) -> dict:
        _guard()
        ident = FaceIdentity.get_by_id(identity_id)
        if not ident:
            raise RowNotFoundException()
        return ident.modify(data, actor_id=user.id).to_dict()

    @classmethod
    def delete_identity(cls, user, identity_id):
        _guard()
        ident = FaceIdentity.get_by_id(identity_id)
        if not ident:
            raise RowNotFoundException()
        ident.soft_delete(actor_id=user.id)        # also erases stored embeddings

    @classmethod
    def enroll(cls, user, identity_id, data: dict) -> dict:
        """Add a reference embedding from an existing observation, or a raw vector."""
        _guard()
        ident = FaceIdentity.get_by_id(identity_id)
        if not ident:
            raise RowNotFoundException()
        if not ident.consent:
            raise InvalidParameterException('consent required before enrollment')

        obs_id = data.get('observation_id')
        if obs_id is not None:
            obs = FaceObservation.get_by_id(safe_int(obs_id))
            if not obs:
                raise RowNotFoundException()
            vector, backend, dim = obs.embedding, obs.backend, obs.dim
        else:
            vector = data.get('embedding')
            backend = data.get('backend')
            if not isinstance(vector, (list, tuple)) or not vector or not backend:
                raise InvalidParameterException('observation_id or (embedding + backend) required')
            dim = len(vector)
        try:
            ident.add_embedding([float(x) for x in vector], backend, dim)
        except ValueError as e:
            raise InvalidParameterException(str(e))
        return ident.to_dict()

    # ── observations ──────────────────────────────────────────────────────────
    @classmethod
    def list_for_camera(cls, user, camera_uuid: str, args) -> list[dict]:
        _guard()
        camera = _scoped_camera(user, camera_uuid)
        limit = min(safe_int(args.get('limit'), 50) or 50, 200)
        return [o.to_dict() for o in FaceObservation.recent_for_camera(camera.id, limit)]

    @classmethod
    def search(cls, user, args) -> dict:
        _guard()
        allowed = _allowed_camera_ids(user)
        if allowed is not None and not allowed:
            return {'items': []}
        obs = FaceObservation.search(
            camera_ids=(list(allowed) if allowed is not None else None),
            identity_id=(safe_int(args.get('identity_id')) if args.get('identity_id') else None),
            known_only=(args.get('known_only') in ('1', 'true', 'True')),
            limit=min(safe_int(args.get('limit'), 100) or 100, 500))
        return {'items': [o.to_dict() for o in obs]}
