from flask import Blueprint, g, request

from server.controller.bookmark import BookmarkController
from server.decorator import login_required, permission_required
from server.view.errors import map_errors
from server.view.response import ResponseBuilder

context = Blueprint('api_bookmark', __name__, url_prefix='/api/v1/bookmarks')


@context.route('', methods=('GET',))
@login_required
@permission_required('bookmarks', 'read')
@map_errors
def list_bookmarks():
    return ResponseBuilder.success(BookmarkController.list_bookmarks(g.current_user, request.args))


@context.route('', methods=('POST',))
@login_required
@permission_required('bookmarks', 'update')
@map_errors
def create_bookmark():
    return ResponseBuilder.success(
        BookmarkController.create(g.current_user, request.get_json(silent=True) or {}))


@context.route('/<bookmark_id>', methods=('PUT', 'POST'))
@login_required
@permission_required('bookmarks', 'update')
@map_errors
def update_bookmark(bookmark_id):
    return ResponseBuilder.success(
        BookmarkController.update(g.current_user, bookmark_id, request.get_json(silent=True) or {}))


@context.route('/<bookmark_id>', methods=('DELETE',))
@login_required
@permission_required('bookmarks', 'update')
@map_errors
def delete_bookmark(bookmark_id):
    BookmarkController.delete(g.current_user, bookmark_id)
    return ResponseBuilder.success()
