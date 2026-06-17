from flask import Blueprint

import config
from server.decorator import login_required, roles_required
from server.model.camera_subscription import CameraSubscription
from server.view.errors import map_errors
from server.view.response import ResponseBuilder

context = Blueprint('api_subscription', __name__, url_prefix='/api/v1/subscriptions')


@context.route('', methods=('GET',))
@login_required
@roles_required('admin')
@map_errors
def list_subscriptions():
    return ResponseBuilder.success({'items': [s.to_dict() for s in CameraSubscription.get_all()]})


@context.route('/<int:camera_id>/resubscribe', methods=('POST',))
@login_required
@roles_required('admin')
@map_errors
def resubscribe(camera_id):
    # signal the supervisor to (re)spawn this camera's subscription
    try:
        from server.service.token import get_redis
        get_redis().delete('%s:sub:%s:lock' % (config.REDIS_KEY_PREFIX, camera_id))
        get_redis().delete('%s:sub:%s:stop' % (config.REDIS_KEY_PREFIX, camera_id))
    except Exception:
        pass
    return ResponseBuilder.success({'camera_id': str(camera_id), 'status': 'resubscribe_requested'})
