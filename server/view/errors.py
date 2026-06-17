"""@map_errors — translate domain exceptions to ResponseBuilder responses.

    RowNotFoundException      -> 404 not_found
    InvalidParameterException -> 400 bad_request
    ConflictException         -> 409 conflict
    NoPermissionException     -> 403 forbidden
    AuthenticationException   -> 401 no_permission
    AccountLockedException    -> 429 too_many_requests
"""
import functools

from server.exception import (
    AccountLockedException,
    AuthenticationException,
    ConflictException,
    InvalidParameterException,
    NoPermissionException,
    RowNotFoundException,
)
from server.view.response import ResponseBuilder


def map_errors(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except RowNotFoundException:
            return ResponseBuilder.not_found('not_found')
        except InvalidParameterException as e:
            return ResponseBuilder.bad_request(e.value)
        except ConflictException as e:
            return ResponseBuilder.conflict(e.value)
        except NoPermissionException as e:
            return ResponseBuilder.forbidden(e.value)
        except AccountLockedException:
            return ResponseBuilder.too_many_requests('account_locked')
        except AuthenticationException as e:
            return ResponseBuilder.no_permission(e.value)
    return wrapper
