from flask import Blueprint, g, request

from server.controller.privacy_mask import PrivacyMaskController
from server.decorator import login_required, permission_required
from server.view.errors import map_errors
from server.view.response import ResponseBuilder

context = Blueprint('api_privacy_mask', __name__, url_prefix='/api/v1')


@context.route('/cameras/<camera_uuid>/privacy-masks', methods=('GET',))
@login_required
@permission_required('live', 'read')   # masks must render for every live viewer, not just managers
@map_errors
def list_masks(camera_uuid):
    return ResponseBuilder.success({'items': PrivacyMaskController.list_for_camera(g.current_user, camera_uuid)})


@context.route('/cameras/<camera_uuid>/privacy-masks', methods=('POST',))
@login_required
@permission_required('masks', 'update')
@map_errors
def create_mask(camera_uuid):
    return ResponseBuilder.success(
        PrivacyMaskController.create(g.current_user, camera_uuid, request.get_json(silent=True) or {}))


@context.route('/privacy-masks/<int:mask_id>', methods=('PUT', 'POST'))
@login_required
@permission_required('masks', 'update')
@map_errors
def update_mask(mask_id):
    return ResponseBuilder.success(
        PrivacyMaskController.update(g.current_user, mask_id, request.get_json(silent=True) or {}))


@context.route('/privacy-masks/<int:mask_id>', methods=('DELETE',))
@login_required
@permission_required('masks', 'update')
@map_errors
def delete_mask(mask_id):
    PrivacyMaskController.delete(g.current_user, mask_id)
    return ResponseBuilder.success()
