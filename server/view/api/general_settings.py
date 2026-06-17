from flask import Blueprint, g, request

from server.controller.general_settings import GeneralSettingsController, TwilioSettingsController
from server.decorator import login_required, permission_required
from server.view.errors import map_errors
from server.view.response import ResponseBuilder

context = Blueprint('api_general_settings', __name__, url_prefix='/api/v1/settings')


@context.route('/general', methods=('GET',))
@login_required
@permission_required('settings', 'read')
@map_errors
def get_general():
    return ResponseBuilder.success(GeneralSettingsController.get())


@context.route('/general', methods=('PUT', 'POST'))
@login_required
@permission_required('settings', 'update')
@map_errors
def update_general():
    return ResponseBuilder.success(
        GeneralSettingsController.update(request.get_json(silent=True) or {}, g.current_user))


@context.route('/twilio', methods=('GET',))
@login_required
@permission_required('settings', 'read')
@map_errors
def get_twilio():
    return ResponseBuilder.success(TwilioSettingsController.get())


@context.route('/twilio', methods=('PUT', 'POST'))
@login_required
@permission_required('settings', 'update')
@map_errors
def update_twilio():
    return ResponseBuilder.success(
        TwilioSettingsController.update(request.get_json(silent=True) or {}, g.current_user))
