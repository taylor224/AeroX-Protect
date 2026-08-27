"""Loopback control API (127.0.0.1:10099) — consumed by the backend's /api/v1/system
proxy (Bearer token) and, for update progress only, directly by the browser through
the reverse proxy's /updater/* route (HMAC ticket, because the backend is down
mid-update).

The ticket mirrors server/service/update_ticket.py exactly:
  secret = sha256(SECRET_KEY + ':sys-update')
  ticket = "<exp>.<b64url(HMAC-SHA256(secret, "update\\n<exp>"))>"
"""
import base64
import hashlib
import hmac
import json
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from . import env

logger = logging.getLogger(__name__)


def _verify_ticket(secret_key: str, ticket: str) -> bool:
    if not ticket or '.' not in ticket:
        return False
    exp_s, sig = ticket.split('.', 1)
    try:
        exp = int(exp_s)
    except ValueError:
        return False
    if exp < int(time.time()):
        return False
    secret = hashlib.sha256((secret_key + ':sys-update').encode()).digest()
    mac = hmac.new(secret, ('update\n%d' % exp).encode(), hashlib.sha256).digest()
    want = base64.urlsafe_b64encode(mac).decode().rstrip('=')
    return hmac.compare_digest(sig, want)


class ControlServer:
    def __init__(self, cfg: dict[str, str], supervisor, updater):
        self.cfg = cfg
        self.sup = supervisor
        self.updater = updater
        self.shutdown_event = threading.Event()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            server_version = 'axp-launcher'

            def log_message(self, fmt, *args):
                logger.debug('control: ' + fmt, *args)

            # ── auth ────────────────────────────────────────────────────────
            def _bearer_ok(self) -> bool:
                auth = self.headers.get('Authorization', '')
                token = outer.cfg.get('AXP_LAUNCHER_TOKEN', '')
                return bool(token) and hmac.compare_digest(auth, 'Bearer %s' % token)

            def _ticket_ok(self, query: dict) -> bool:
                ticket = (query.get('ticket') or [''])[0]
                return _verify_ticket(outer.cfg.get('SECRET_KEY', ''), ticket)

            def _json(self, code: int, payload: dict):
                body = json.dumps(payload).encode('utf-8')
                self.send_response(code)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                self.wfile.write(body)

            # ── routes ──────────────────────────────────────────────────────
            def do_GET(self):
                parts = urlsplit(self.path)
                query = parse_qs(parts.query)
                path = parts.path.rstrip('/')

                if path == '/v1/update/status':
                    # ticket OR bearer — this is the browser's mid-update poll
                    if not (self._bearer_ok() or self._ticket_ok(query)):
                        return self._json(403, {'error': 'forbidden'})
                    return self._json(200, outer.updater.status())

                if not self._bearer_ok():
                    return self._json(403, {'error': 'forbidden'})

                if path == '/v1/status':
                    return self._json(200, outer.sup.status())
                if path == '/v1/update/check':
                    try:
                        force = (query.get('force') or ['0'])[0] in ('1', 'true')
                        return self._json(200, outer.updater.check(force=force))
                    except Exception as e:
                        logger.exception('update check failed')
                        return self._json(502, {'error': str(e)})
                if path.startswith('/v1/logs/'):
                    name = path.rsplit('/', 1)[1]
                    tail = int((query.get('tail') or ['200'])[0])
                    lines = outer.sup.logs(name, tail)
                    if lines is None:
                        return self._json(404, {'error': 'unknown service'})
                    return self._json(200, {'name': name, 'lines': lines})
                return self._json(404, {'error': 'not found'})

            def do_POST(self):
                parts = urlsplit(self.path)
                path = parts.path.rstrip('/')
                if not self._bearer_ok():
                    return self._json(403, {'error': 'forbidden'})
                length = int(self.headers.get('Content-Length') or 0)
                try:
                    body = json.loads(self.rfile.read(length) or b'{}') if length else {}
                except ValueError:
                    body = {}

                if path == '/v1/update/apply':
                    started = outer.updater.apply(body.get('version'))
                    if not started:
                        return self._json(409, {'error': 'update already running'})
                    return self._json(200, {'started': True})
                if path.startswith('/v1/restart/'):
                    name = path.rsplit('/', 1)[1]
                    ok = outer.sup.restart_service(name)
                    return self._json(200 if ok else 500, {'restarted': ok, 'name': name})
                if path == '/v1/shutdown':
                    outer.shutdown_event.set()
                    return self._json(200, {'stopping': True})
                return self._json(404, {'error': 'not found'})

        self._server = ThreadingHTTPServer(('127.0.0.1', env.CONTROL_PORT), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        name='control-api', daemon=True)

    def start(self):
        self._thread.start()
        logger.info('control API on 127.0.0.1:%d', env.CONTROL_PORT)

    def stop(self):
        self._server.shutdown()
