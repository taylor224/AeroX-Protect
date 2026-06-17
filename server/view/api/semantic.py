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
