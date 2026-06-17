from flask import Blueprint, g, request

from server.controller.object_trigger import ObjectTriggerController
from server.decorator import login_required, permission_required
from server.view.errors import map_errors
from server.view.response import ResponseBuilder

context = Blueprint('api_object_trigger', __name__, url_prefix='/api/v1/object-triggers')


@context.route('', methods=('GET',))
@login_required
@permission_required('triggers', 'read')
@map_errors
def list_triggers():
    return ResponseBuilder.success({'items': ObjectTriggerController.list_triggers(request.args.get('camera_id'))})


@context.route('', methods=('POST',))
@login_required
@permission_required('triggers', 'update')
@map_errors
def create_trigger():
    return ResponseBuilder.success(ObjectTriggerController.create(request.get_json(silent=True) or {}, g.current_user))


@context.route('/test', methods=('POST',))
@login_required
@permission_required('triggers', 'read')
@map_errors
def test_trigger():
    return ResponseBuilder.success(ObjectTriggerController.test(request.get_json(silent=True) or {}))


@context.route('/<int:trigger_id>', methods=('PUT', 'POST'))
@login_required
@permission_required('triggers', 'update')
@map_errors
def update_trigger(trigger_id):
    return ResponseBuilder.success(
        ObjectTriggerController.update(trigger_id, request.get_json(silent=True) or {}, g.current_user))


@context.route('/<int:trigger_id>', methods=('DELETE',))
@login_required
@permission_required('triggers', 'update')
@map_errors
def delete_trigger(trigger_id):
    ObjectTriggerController.delete(trigger_id)
    return ResponseBuilder.success()
