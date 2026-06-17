from flask import Blueprint, g, request

from server.controller.archive import ArchiveController
from server.decorator import login_required, permission_required
from server.view.errors import map_errors
from server.view.response import ResponseBuilder

context = Blueprint('api_archive', __name__, url_prefix='/api/v1')


@context.route('/archive-targets', methods=('GET',))
@login_required
@permission_required('archive', 'read')
@map_errors
def list_targets():
    return ResponseBuilder.success({'items': ArchiveController.list_targets()})


@context.route('/archive-targets', methods=('POST',))
@login_required
@permission_required('archive', 'run')
@map_errors
def create_target():
    return ResponseBuilder.success(ArchiveController.create_target(request.get_json(silent=True) or {}, g.current_user))


@context.route('/archive-targets/<int:target_id>', methods=('PUT', 'POST'))
@login_required
@permission_required('archive', 'run')
@map_errors
def update_target(target_id):
    return ResponseBuilder.success(
        ArchiveController.update_target(target_id, request.get_json(silent=True) or {}, g.current_user))


@context.route('/archive-targets/<int:target_id>', methods=('DELETE',))
@login_required
@permission_required('archive', 'run')
@map_errors
def delete_target(target_id):
    ArchiveController.delete_target(target_id)
    return ResponseBuilder.success()


@context.route('/archive-jobs', methods=('GET',))
@login_required
@permission_required('archive', 'read')
@map_errors
def list_jobs():
    return ResponseBuilder.success({'items': ArchiveController.list_jobs()})


@context.route('/archive-jobs', methods=('POST',))
@login_required
@permission_required('archive', 'run')
@map_errors
def create_job():
    return ResponseBuilder.success(ArchiveController.create_job(request.get_json(silent=True) or {}, g.current_user))
