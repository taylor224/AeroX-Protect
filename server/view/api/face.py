from flask import Blueprint, g, request

from server.controller.face import FaceController
from server.decorator import login_required, permission_required
from server.view.errors import map_errors
from server.view.response import ResponseBuilder

context = Blueprint('api_face', __name__, url_prefix='/api/v1')


@context.route('/face/identities', methods=('GET',))
@login_required
@permission_required('face', 'read')
@map_errors
def list_identities():
    return ResponseBuilder.success({'items': FaceController.list_identities(g.current_user)})


@context.route('/face/identities', methods=('POST',))
@login_required
@permission_required('face', 'manage')
@map_errors
def create_identity():
    return ResponseBuilder.success(FaceController.create_identity(g.current_user, request.get_json(silent=True) or {}))


@context.route('/face/identities/<int:identity_id>', methods=('PUT', 'POST'))
@login_required
@permission_required('face', 'manage')
@map_errors
def update_identity(identity_id):
    return ResponseBuilder.success(
        FaceController.update_identity(g.current_user, identity_id, request.get_json(silent=True) or {}))


@context.route('/face/identities/<int:identity_id>', methods=('DELETE',))
@login_required
@permission_required('face', 'manage')
@map_errors
def delete_identity(identity_id):
    FaceController.delete_identity(g.current_user, identity_id)
    return ResponseBuilder.success()


@context.route('/face/identities/<int:identity_id>/enroll', methods=('POST',))
@login_required
@permission_required('face', 'manage')
@map_errors
def enroll(identity_id):
    return ResponseBuilder.success(
        FaceController.enroll(g.current_user, identity_id, request.get_json(silent=True) or {}))


@context.route('/cameras/<camera_uuid>/faces', methods=('GET',))
@login_required
@permission_required('face', 'read')
@map_errors
def list_for_camera(camera_uuid):
    return ResponseBuilder.success({'items': FaceController.list_for_camera(g.current_user, camera_uuid, request.args)})


@context.route('/faces/search', methods=('GET',))
@login_required
@permission_required('face', 'read')
@map_errors
def search():
    return ResponseBuilder.success(FaceController.search(g.current_user, request.args))
