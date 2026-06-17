from flask import Blueprint, g, request

from server.controller.storage import StorageController
from server.decorator import login_required, permission_required
from server.model.camera import Camera
from server.view.errors import map_errors
from server.view.response import ResponseBuilder

context = Blueprint('api_storage', __name__, url_prefix='/api/v1/storage')


def _camera_id(camera_uuid: str) -> int:
    return Camera.get_by_uuid(camera_uuid).id


# ── disks ─────────────────────────────────────────────────────────────────────
@context.route('/disks', methods=('GET',))
@login_required
@permission_required('storage', 'read')
@map_errors
def list_disks():
    return ResponseBuilder.success({'disks': StorageController.list_disks()})


@context.route('/disks', methods=('POST',))
@login_required
@permission_required('storage', 'manage')
@map_errors
def create_disk():
    return ResponseBuilder.success(StorageController.create_disk(request.get_json(silent=True) or {}, g.current_user))


@context.route('/disks/<int:disk_id>', methods=('PUT', 'POST'))
@login_required
@permission_required('storage', 'manage')
@map_errors
def update_disk(disk_id):
    return ResponseBuilder.success(
        StorageController.update_disk(disk_id, request.get_json(silent=True) or {}, g.current_user))


@context.route('/disks/<int:disk_id>', methods=('DELETE',))
@login_required
@permission_required('storage', 'manage')
@map_errors
def delete_disk(disk_id):
    mode = (request.get_json(silent=True) or {}).get('mode', 'unregister')
    return ResponseBuilder.success(StorageController.delete_disk(disk_id, mode, g.current_user))


@context.route('/discover', methods=('GET',))
@login_required
@permission_required('storage', 'manage')
@map_errors
def discover():
    return ResponseBuilder.success({'candidates': StorageController.discover()})


@context.route('/pool', methods=('GET',))
@login_required
@permission_required('storage', 'read')
@map_errors
def pool():
    return ResponseBuilder.success(StorageController.pool())


# ── policies ──────────────────────────────────────────────────────────────────
@context.route('/policies', methods=('GET',))
@login_required
@permission_required('storage', 'read')
@map_errors
def get_policies():
    return ResponseBuilder.success(StorageController.get_policies())


@context.route('/policies/<camera_uuid>', methods=('GET',))
@login_required
@permission_required('storage', 'read')
@map_errors
def get_policy(camera_uuid):
    return ResponseBuilder.success(StorageController.get_policy(_camera_id(camera_uuid)))


@context.route('/policies', methods=('PUT', 'POST'))
@login_required
@permission_required('retention', 'manage')
@map_errors
def update_global_policy():
    return ResponseBuilder.success(
        StorageController.update_policy(None, request.get_json(silent=True) or {}, g.current_user))


@context.route('/policies/<camera_uuid>', methods=('PUT', 'POST'))
@login_required
@permission_required('retention', 'manage')
@map_errors
def update_policy(camera_uuid):
    return ResponseBuilder.success(
        StorageController.update_policy(_camera_id(camera_uuid), request.get_json(silent=True) or {}, g.current_user))
