from flask import Blueprint, request

from server.controller.audit_log import AuditLogController
from server.decorator import login_required, roles_required
from server.util.pagination import build_page, parse_pagination
from server.view.errors import map_errors
from server.view.response import ResponseBuilder

context = Blueprint('api_admin_audit_log', __name__, url_prefix='/api/v1/admin/audit_logs')


@context.route('', methods=('GET',))
@login_required
@roles_required('admin')
@map_errors
def list_audit_logs():
    p = parse_pagination(request.args)
    total, items = AuditLogController.get_list(
        p['page'], p['items_per_page'],
        request.args.get('action'), p['q'],
        request.args.get('from'), request.args.get('to'))
    return ResponseBuilder.success(build_page(items, total, p['page'], p['items_per_page']))
