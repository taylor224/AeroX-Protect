from datetime import datetime

from flask import jsonify

from server.model import KST


class ResponseBuilder:
    """Standard API envelope (ams pattern). `time` is KST ISO (display only)."""

    @staticmethod
    def success(data=None):
        return jsonify(
            status='success',
            data=data,
            time=datetime.now(KST).isoformat(),
        )

    @staticmethod
    def bad_request(message=None):
        r = jsonify(status='bad_request', message=message, time=datetime.now(KST).isoformat())
        r.status_code = 400
        return r

    @staticmethod
    def no_permission(message=None):
        """401 — not authenticated / invalid token."""
        r = jsonify(status='no_permission', message=message, time=datetime.now(KST).isoformat())
        r.status_code = 401
        return r

    @staticmethod
    def forbidden(message=None):
        """403 — authenticated but lacks permission."""
        r = jsonify(status='forbidden', message=message, time=datetime.now(KST).isoformat())
        r.status_code = 403
        return r

    @staticmethod
    def not_found(message=None):
        r = jsonify(status='not_found', message=message, time=datetime.now(KST).isoformat())
        r.status_code = 404
        return r

    @staticmethod
    def conflict(message=None):
        r = jsonify(status='conflict', message=message, time=datetime.now(KST).isoformat())
        r.status_code = 409
        return r

    @staticmethod
    def too_many_requests(message=None):
        r = jsonify(status='too_many_requests', message=message, time=datetime.now(KST).isoformat())
        r.status_code = 429
        return r

    @staticmethod
    def internal_server_error(message=None):
        r = jsonify(status='internal_server_error', message=message, time=datetime.now(KST).isoformat())
        r.status_code = 500
        return r
