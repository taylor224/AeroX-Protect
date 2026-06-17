"""Share-link API. `/share-links` is owner-authed (share:create); `/s/<token>` is the
public viewer — authenticated by the share token in the URL only, never a user session.
Segment paths are built from disk_id+rel_path (no user path input → no traversal, §13)."""
import os

from flask import Blueprint, g, request, send_file

from server.controller.share_link import ShareLinkController
from server.decorator import login_required, permission_required
from server.model.disk import Disk
from server.service import storage_manager
from server.view.errors import map_errors
from server.view.response import ResponseBuilder

context = Blueprint('api_share_link', __name__, url_prefix='/api/v1/share-links')
public_context = Blueprint('api_share_public', __name__, url_prefix='/api/v1/s')


# ── owner-authed CRUD ─────────────────────────────────────────────────────────
@context.route('', methods=('POST',))
@login_required
@permission_required('share', 'create')
@map_errors
def create_link():
    return ResponseBuilder.success(ShareLinkController.create(g.current_user, request.get_json(silent=True) or {}))


@context.route('', methods=('GET',))
@login_required
@permission_required('share', 'create')
@map_errors
def list_links():
    return ResponseBuilder.success(ShareLinkController.list_links(g.current_user))


@context.route('/<share_id>', methods=('DELETE',))
@login_required
@permission_required('share', 'create')
@map_errors
def revoke_link(share_id):
    return ResponseBuilder.success(ShareLinkController.revoke(g.current_user, share_id))


# ── public viewer (share token only, no session) ──────────────────────────────
@public_context.route('/<token>', methods=('GET',))
@map_errors
def view_link(token):
    return ResponseBuilder.success(ShareLinkController.public_view(token, None, request.remote_addr))


@public_context.route('/<token>', methods=('POST',))
@map_errors
def unlock_link(token):
    pw = (request.get_json(silent=True) or {}).get('password')
    return ResponseBuilder.success(ShareLinkController.public_view(token, pw, request.remote_addr))


@public_context.route('/<token>/segments/<int:segment_id>/data', methods=('GET',))
@map_errors
def share_segment_data(token, segment_id):
    seg = ShareLinkController.public_segment_path(token, segment_id)
    disk = Disk.get_by_id(seg.disk_id)
    path = storage_manager.abs_path(disk, seg.rel_path) if disk else None
    if not path or not os.path.exists(path):
        return ResponseBuilder.not_found('segment_unavailable')
    mimetype = 'video/mp2t' if seg.container == 'mpegts' else 'video/mp4'
    return send_file(path, mimetype=mimetype, conditional=True, max_age=3600)
