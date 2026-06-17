"""Domain exceptions. Views map these to ResponseBuilder statuses:

    RowNotFoundException      -> not_found        (404)
    InvalidParameterException -> bad_request      (400)
    ConflictException         -> conflict         (409)
    AuthenticationException   -> no_permission    (401)
    TokenReuseException       -> no_permission    (401)
    NoPermissionException     -> forbidden        (403)
    AccountLockedException    -> too_many_requests(429)
"""


class RowNotFoundException(Exception):
    pass


class InvalidParameterException(Exception):
    def __init__(self, value=None):
        self.value = str(value) if value else None

    def __str__(self):
        return repr(self.value)


class ConflictException(Exception):
    def __init__(self, value=None):
        self.value = str(value) if value else None

    def __str__(self):
        return repr(self.value)


class AuthenticationException(Exception):
    """Bad credentials / invalid or expired token."""
    def __init__(self, value=None):
        self.value = str(value) if value else None

    def __str__(self):
        return repr(self.value)


class TokenReuseException(Exception):
    """A rotated (already-used) refresh token was replayed — token theft."""
    def __init__(self, value=None):
        self.value = str(value) if value else None

    def __str__(self):
        return repr(self.value)


class NoPermissionException(Exception):
    """Authenticated but lacks the required permission."""
    def __init__(self, value=None):
        self.value = str(value) if value else None

    def __str__(self):
        return repr(self.value)


class AccountLockedException(Exception):
    """Too many failed logins — account temporarily locked."""
    def __init__(self, value=None):
        self.value = str(value) if value else None

    def __str__(self):
        return repr(self.value)
