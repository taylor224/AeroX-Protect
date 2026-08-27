"""Tiny CLI against the launcher control API:

    python -m axp_launcher.ctl status
    python -m axp_launcher.ctl logs <service> [tail]
    python -m axp_launcher.ctl restart <service>
    python -m axp_launcher.ctl update-check
    python -m axp_launcher.ctl update-apply [version]
    python -m axp_launcher.ctl stop          # WinSW stopexecutable target
"""
import json
import sys
import urllib.request

from . import env


def _call(method: str, path: str, body: dict | None = None):
    cfg = env.load_env()
    req = urllib.request.Request(
        'http://127.0.0.1:%d%s' % (env.CONTROL_PORT, path),
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={'Authorization': 'Bearer %s' % cfg.get('AXP_LAUNCHER_TOKEN', ''),
                 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode('utf-8'))


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'status'
    try:
        if cmd == 'status':
            out = _call('GET', '/v1/status')
        elif cmd == 'logs':
            name = sys.argv[2]
            tail = sys.argv[3] if len(sys.argv) > 3 else '200'
            out = _call('GET', '/v1/logs/%s?tail=%s' % (name, tail))
            print('\n'.join(out.get('lines', [])))
            return
        elif cmd == 'restart':
            out = _call('POST', '/v1/restart/%s' % sys.argv[2])
        elif cmd == 'update-check':
            out = _call('GET', '/v1/update/check?force=1')
        elif cmd == 'update-apply':
            out = _call('POST', '/v1/update/apply',
                        {'version': sys.argv[2] if len(sys.argv) > 2 else None})
        elif cmd == 'stop':
            out = _call('POST', '/v1/shutdown')
        else:
            print(__doc__)
            sys.exit(2)
        print(json.dumps(out, indent=2))
    except Exception as e:
        print('error: %s' % e, file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
