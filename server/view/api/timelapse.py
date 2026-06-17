from flask import Blueprint, g, request, send_file

from server.controller.timelapse import TimelapseController
from server.decorator import camera_scope_guard, login_required, permission_required
from server.service.permission import PermissionService
from server.service.token import TokenService
from server.util.pagination import build_page, parse_pagination
from server.view.errors import map_errors
from server.view.response import ResponseBuilder

context = Blueprint('api_timelapse', __name__, url_prefix='/api/v1/timelapse')


@context.route('', methods=('GET',))
@login_required
@permission_required('timelapse', 'read')
@map_errors
def list_jobs():
    camera_uuid = request.args.get('camera_id')
    if camera_uuid:
        err = camera_scope_guard(camera_uuid, 'view')
        if err:
            return err
    elif not PermissionService.is_superuser(g.current_user):
        # an unfiltered listing would expose other cameras' job metadata —
        # restrict the all-cameras view to superusers
        return ResponseBuilder.forbidden('camera_id_required')
    p = parse_pagination(request.args)
    total, items = TimelapseController.list_jobs(
        camera_uuid, request.args.get('status'), p['page'], p['items_per_page'])
    return ResponseBuilder.success(build_page(items, total, p['page'], p['items_per_page']))


@context.route('', methods=('POST',))
@login_required
@permission_required('timelapse', 'create')
@map_errors
def create_job():
    return ResponseBuilder.success(TimelapseController.create(request.get_json(silent=True) or {}, g.current_user))


@context.route('/<int:job_id>', methods=('GET',))
@login_required
@permission_required('timelapse', 'read')
@map_errors
def get_job(job_id):
    return ResponseBuilder.success(TimelapseController.get_job(job_id, g.current_user))


@context.route('/<int:job_id>/cancel', methods=('POST',))
@login_required
@permission_required('timelapse', 'cancel')
@map_errors
def cancel_job(job_id):
    TimelapseController.cancel(job_id, g.current_user)
    return ResponseBuilder.success()


@context.route('/<int:job_id>/download', methods=('GET',))
@map_errors
def download(job_id):
    bearer = request.headers.get('Authorization', '')
    access = bearer[7:].strip() if bearer.startswith('Bearer ') else request.args.get('access_token')
    if not access:
        return ResponseBuilder.no_permission('authentication_required')
    try:
        user, _ = TokenService.verify_access(access)
    except Exception:
        return ResponseBuilder.no_permission('invalid_token')
    job, path = TimelapseController.resolve_download(job_id, user)
    return send_file(path, mimetype='video/mp4', as_attachment=True,
                     download_name='axp_timelapse_%s.mp4' % job.id, conditional=True)
