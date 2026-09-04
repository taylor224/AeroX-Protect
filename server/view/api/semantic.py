from flask import Blueprint, g, request

from server.controller.semantic_search import SemanticSearchController
from server.decorator import login_required, permission_required
from server.view.errors import map_errors
from server.view.response import ResponseBuilder

context = Blueprint('api_semantic', __name__, url_prefix='/api/v1/search')


@context.route('/semantic', methods=('GET',))
@login_required
@permission_required('ai', 'semantic_search')
@map_errors
def semantic_search():
    return ResponseBuilder.success(SemanticSearchController.search(g.current_user, request.args))


@context.route('/semantic/reindex', methods=('POST',))
@login_required
@permission_required('ai', 'semantic_search')
@map_errors
def semantic_reindex():
    return ResponseBuilder.success(
        SemanticSearchController.reindex(g.current_user, request.get_json(silent=True) or {}))


@context.route('/semantic/model', methods=('GET',))
@login_required
@permission_required('ai', 'semantic_search')
@map_errors
def semantic_model_status():
    return ResponseBuilder.success(SemanticSearchController.model_status(g.current_user))


@context.route('/semantic/model/install', methods=('POST',))
@login_required
@permission_required('settings', 'update')
@map_errors
def semantic_model_install():
    from server.service import ai_model_setup
    if not ai_model_setup.supported():
        r = ResponseBuilder.internal_server_error('platform_unsupported')
        r.status_code = 501
        return r
    data = SemanticSearchController.model_install(g.current_user, request.get_json(silent=True) or {})
    if not data['started']:
        return ResponseBuilder.conflict('install_already_running')
    return ResponseBuilder.success(data)


@context.route('/semantic/model', methods=('DELETE',))
@login_required
@permission_required('settings', 'update')
@map_errors
def semantic_model_remove():
    from server.service import ai_model_setup
    if not ai_model_setup.supported():
        r = ResponseBuilder.internal_server_error('platform_unsupported')
        r.status_code = 501
        return r
    try:
        return ResponseBuilder.success(SemanticSearchController.model_remove(g.current_user))
    except RuntimeError as e:
        if str(e) == 'install_running':
            return ResponseBuilder.conflict('install_running')
        raise
