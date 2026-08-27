"""Production WSGI entrypoint for native (non-Docker) installs: `python -m server.wsgi`.

Docker keeps uWSGI (see server/Dockerfile); waitress is the Windows-capable
equivalent. The tuning mirrors the uWSGI/nginx streaming contract:
- channel_timeout=3600: a live fMP4 stream (server/view/api/live.py GET /live/mp4/)
  is an endless chunked response — the default 120s would cut it off.
- send_bytes=1: flush every app-yielded chunk immediately (the live generator
  yields 8192-byte chunks; waitress's default 18000-byte output buffer would add
  multi-second latency and stall the player).
- trusted_proxy: the local reverse proxy (Caddy) is the only legitimate source of
  X-Forwarded-* (ProxyFix in server/__init__.py trusts exactly one hop).
"""
import os


def serve():
    from waitress import serve as waitress_serve

    from server import app

    waitress_serve(
        app,
        host=os.getenv('AXP_BIND_HOST', '127.0.0.1'),
        port=int(os.getenv('AXP_BIND_PORT', '10000')),
        threads=int(os.getenv('AXP_WAITRESS_THREADS', '32')),
        channel_timeout=3600,
        connection_limit=int(os.getenv('AXP_WAITRESS_CONNECTIONS', '200')),
        send_bytes=1,
        max_request_body_size=1024 * 1024 * 1024,
        expose_tracebacks=False,
        clear_untrusted_proxy_headers=True,
        trusted_proxy=os.getenv('AXP_TRUSTED_PROXY', '127.0.0.1'),
        trusted_proxy_headers={'x-forwarded-for', 'x-forwarded-proto', 'x-forwarded-host'},
    )


if __name__ == '__main__':
    serve()
