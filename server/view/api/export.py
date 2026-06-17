from flask import Blueprint, g, request, send_file

from server.controller.export import ExportController
from server.decorator import login_required, permission_required
from server.service.token import TokenService
from server.util.pagination import build_page, parse_pagination
from server.view.errors import map_errors
from server.view.response import ResponseBuilder

context = Blueprint('api_export', __name__, url_prefix='/api/v1/export')


@context.route('/jobs', methods=('POST',))
@login_required
@permission_required('clips', 'export')
@map_errors
def create_job():
    return ResponseBuilder.success(ExportController.create_job(request.get_json(silent=True) or {}, g.current_user))


@context.route('/jobs', methods=('GET',))
@login_required
@permission_required('clips', 'export')
@map_errors
def list_jobs():
    p = parse_pagination(request.args)
    total, items = ExportController.list_jobs(g.current_user, p['page'], p['items_per_page'])
    return ResponseBuilder.success(build_page(items, total, p['page'], p['items_per_page']))


@context.route('/jobs/<int:job_id>', methods=('GET',))
@login_required
@permission_required('clips', 'export')
@map_errors
def get_job(job_id):
    return ResponseBuilder.success(ExportController.get_job(job_id, g.current_user))


@context.route('/jobs/<int:job_id>', methods=('DELETE',))
@login_required
@permission_required('clips', 'export')
@map_errors
def cancel_job(job_id):
    ExportController.cancel_job(job_id, g.current_user)
    return ResponseBuilder.success()


@context.route('/download/<token>', methods=('GET',))
@map_errors
def download(token):
    # browser navigation can't set headers → accept header OR ?access_token
    bearer = request.headers.get('Authorization', '')
    access = bearer[7:].strip() if bearer.startswith('Bearer ') else request.args.get('access_token')
    if not access:
        return ResponseBuilder.no_permission('authentication_required')
    try:
        user, _ = TokenService.verify_access(access)
    except Exception:
        return ResponseBuilder.no_permission('invalid_token')

    job, path = ExportController.resolve_download(token, user)
    download_name = 'axp_clip_%s.%s' % (job.id, job.container)
    return send_file(path, mimetype='video/mp4', as_attachment=True,
                     download_name=download_name, conditional=True)
