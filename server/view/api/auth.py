from flask import Blueprint, g, request

import config
from server.controller.auth import AuthController
from server.decorator import login_required
from server.exception import (
    AccountLockedException,
    AuthenticationException,
    InvalidParameterException,
    RowNotFoundException,
    TokenReuseException,
)
from server.service.token import TokenService
from server.view.response import ResponseBuilder

context = Blueprint('api_auth', __name__, url_prefix='/api/v1/auth')


def _set_refresh_cookie(response, refresh_token: str):
    response.set_cookie(
        config.REFRESH_COOKIE_NAME, refresh_token,
        max_age=config.JWT_REFRESH_TTL,
        httponly=True,
        secure=not (config.PROJECT_ENV == 'development'),
        samesite='Strict',
        path=config.REFRESH_COOKIE_PATH,
    )
    return response


def _clear_refresh_cookie(response):
    response.delete_cookie(config.REFRESH_COOKIE_NAME, path=config.REFRESH_COOKIE_PATH)
    return response


def _access_payload(bundle: dict) -> dict:
    return {
        'access_token': bundle['access_token'],
        'token_type': 'Bearer',
        'expires_in': bundle['expires_in'],
        'user': bundle['user'],
    }


@context.route('/login', methods=('POST',))
def login():
    data = request.get_json(silent=True) or request.form
    try:
        bundle = AuthController.login(
            data.get('login_id'), data.get('password'),
            request.remote_addr, request.user_agent.string)
    except AccountLockedException:
        return ResponseBuilder.too_many_requests('account_locked')
    except (AuthenticationException, RowNotFoundException):
        return ResponseBuilder.bad_request('invalid_credentials')

    response = ResponseBuilder.success(_access_payload(bundle))
    return _set_refresh_cookie(response, bundle['refresh_token'])


@context.route('/refresh', methods=('POST',))
def refresh():
    token = request.cookies.get(config.REFRESH_COOKIE_NAME)
    if not token:
        body = request.get_json(silent=True) or {}
        token = body.get('refresh_token')
    try:
        bundle = AuthController.refresh(token, request.remote_addr, request.user_agent.string)
    except TokenReuseException:
        response = ResponseBuilder.no_permission('refresh_reuse_detected')
        return _clear_refresh_cookie(response)
    except (AuthenticationException, RowNotFoundException):
        response = ResponseBuilder.no_permission('invalid_refresh')
        return _clear_refresh_cookie(response)

    response = ResponseBuilder.success(_access_payload(bundle))
    return _set_refresh_cookie(response, bundle['refresh_token'])


@context.route('/logout', methods=('POST',))
@login_required
def logout():
    # denylist the presented access token + revoke the refresh family
    access_claims = g.get('token_claims')
    refresh_token = request.cookies.get(config.REFRESH_COOKIE_NAME)
    refresh_jti = None
    if refresh_token:
        decoded = TokenService.decode_unverified_access(refresh_token)
        refresh_jti = decoded.get('jti') if decoded else None

    AuthController.logout(access_claims, refresh_jti, g.current_user,
                          request.remote_addr, request.user_agent.string)
    response = ResponseBuilder.success()
    return _clear_refresh_cookie(response)


@context.route('/me', methods=('GET',))
@login_required
def me():
    return ResponseBuilder.success(AuthController.me(g.current_user))


@context.route('/change_password', methods=('POST',))
@login_required
def change_password():
    data = request.get_json(silent=True) or {}
    try:
        AuthController.change_password(g.current_user, data.get('previous_password'), data.get('password'))
        return ResponseBuilder.success()
    except InvalidParameterException as e:
        return ResponseBuilder.bad_request(e.value)


@context.route('/language', methods=('POST',))
@login_required
def language():
    data = request.get_json(silent=True) or {}
    try:
        lang = AuthController.set_language(g.current_user, data.get('language'))
        return ResponseBuilder.success({'language': lang})
    except InvalidParameterException as e:
        return ResponseBuilder.bad_request(e.value)
