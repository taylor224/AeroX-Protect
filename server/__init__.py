import logging
import os
from datetime import date, datetime

import sentry_sdk
from flask import Flask, g, request
from flask.json.provider import DefaultJSONProvider
from flask_cors import CORS
from sentry_sdk.integrations.flask import FlaskIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
from werkzeug.middleware.proxy_fix import ProxyFix

import config
from server.model import BaseDB, db

PROJECT_PATH = os.path.dirname(__file__)

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
app.config['MAX_CONTENT_LENGTH'] = 1 * 1024 * 1024 * 1024
app.config['SECRET_KEY'] = config.SECRET_KEY
app.config['SQLALCHEMY_DATABASE_URI'] = config.DATABASE_URI

IS_DEV = config.PROJECT_ENV == 'development'
if IS_DEV:
    app.config['DEBUG'] = True
    logging.basicConfig(level=logging.DEBUG)
else:
    logging.basicConfig(level=logging.INFO)

sentry_sdk.init(
    dsn=config.SENTRY_DSN,
    integrations=[FlaskIntegration(), SqlalchemyIntegration()],
    traces_sample_rate=1.0,
    send_default_pii=False,
)

# A wildcard origin combined with credentials makes flask_cors reflect ANY Origin back
# with Access-Control-Allow-Credentials:true — a credentialed-CORS bypass. Only enable
# credentialed CORS for an explicit origin allowlist; otherwise serve credential-less CORS.
_cors_origins = [o.strip() for o in config.CORS_ALLOWED_ORIGINS.split(',') if o.strip()]
if _cors_origins == ['*']:
    CORS(app, resources={r"/api/*": {"origins": '*'}}, supports_credentials=False)
else:
    CORS(app, resources={r"/api/*": {"origins": _cors_origins}}, supports_credentials=True)

db.db_init(config.DATABASE_URI, BaseDB)


class AxpJSONProvider(DefaultJSONProvider):
    """Stray datetime/date -> ISO. Models already serialize to epoch ms in to_dict()."""

    def default(self, o):
        if isinstance(o, (datetime, date)):
            return o.isoformat()
        return super().default(o)


app.json = AxpJSONProvider(app)

# Paths that must never trigger DB access-logging.
_ACCESS_LOG_SKIP_PREFIXES = ('/api/v1/healthz', '/api/v1/auth/refresh', '/static')


@app.before_request
def load_current_user():
    """Resolve JWT (if present) into g.current_user; never blocks the request.
    Decorators (login_required / permission_required) enforce access."""
    g.current_user = None
    g.token_claims = None

    if request.method == 'OPTIONS':
        return

    auth_header = request.headers.get('Authorization', '')
    token = None
    if auth_header.startswith('Bearer '):
        token = auth_header[7:].strip()
    elif request.method == 'GET':
        # <img>/<video> tags can't set an Authorization header, so media tiles
        # (thumbnail/snapshot) pass the access token as a query param. Accept it for
        # GET only — never for mutations — so those decorator-guarded routes authenticate.
        token = request.args.get('access_token')
    if token:
        # Lazy import to avoid an import cycle at module load.
        from server.service.token import TokenService
        user, claims = TokenService.resolve_access_token(token)
        g.current_user = user
        g.token_claims = claims

    _record_access_log()


def _record_access_log():
    """Best-effort access log for mutating API calls (writes only — keeps it light)."""
    if request.method in ('GET', 'HEAD', 'OPTIONS'):
        return
    path = request.path
    if not path.startswith('/api/') or any(path.startswith(p) for p in _ACCESS_LOG_SKIP_PREFIXES):
        return
    try:
        from server.model.audit_log import AuditLog
        AuditLog.record(
            action='access',
            target=path,
            user_id=g.current_user.id if g.current_user else None,
            method=request.method,
            path=path,
            ip=request.remote_addr,
            user_agent=request.user_agent.string,
        )
    except Exception:  # never let logging break a request
        db.session.rollback()


@app.teardown_request
def teardown(exc=None):
    if db.session:
        db.session.remove()


import server.view  # noqa: E402,F401  (registers blueprints)
