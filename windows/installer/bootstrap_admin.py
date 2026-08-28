"""Installer final step: create the first admin account.

Runs AFTER the service starts, elevated, with the wizard's admin id/password
passed as process arguments only — the password is deliberately NEVER written
to disk (axp.env or anywhere else). It waits for the stack's first boot
(MariaDB datadir init + schema/seed) via the backend healthz, then runs
`server.command seed-admin` with BOOTSTRAP_ADMIN_* injected into that child's
environment. seed-admin no-ops if any user already exists (upgrade installs).
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

BACKEND_HEALTHZ = 'http://127.0.0.1:10000/api/v1/healthz'
DB_PORT = 3307


def load_env(path: Path) -> dict[str, str]:
    cfg: dict[str, str] = {}
    for raw in path.read_text(encoding='utf-8').splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, _, v = line.partition('=')
        cfg[k.strip()] = v.strip().strip('"')
    return cfg


def wait_backend(timeout_s: int = 300) -> bool:
    """First boot initializes MariaDB + runs db-upgrade/seed before the backend
    comes up — healthz db:true means the schema (roles) is ready for seed-admin."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(BACKEND_HEALTHZ, timeout=3) as r:
                data = json.loads(r.read().decode('utf-8')).get('data') or {}
                if data.get('db'):
                    return True
        except Exception:
            pass
        time.sleep(2)
    return False


def decode_hex_utf16(s: str) -> str:
    """Inno Setup passes wizard strings as IntToHex(Ord(ch), 4) per UTF-16 code
    unit — quoting-proof for passwords containing '"', spaces, Korean, anything.
    (Plain argv quoting mangled special-character passwords: the install-time
    admin account ended up with a different password than the user typed.)"""
    units = bytes(b for i in range(0, len(s), 4)
                  for b in int(s[i:i + 4], 16).to_bytes(2, 'big'))
    return units.decode('utf-16-be')


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument('--home', required=True)
    p.add_argument('--admin-id', default='admin')
    p.add_argument('--admin-pw', default=None)
    p.add_argument('--admin-id-hex', default=None)
    p.add_argument('--admin-pw-hex', default=None)
    args = p.parse_args()
    if args.admin_id_hex:
        args.admin_id = decode_hex_utf16(args.admin_id_hex)
    if args.admin_pw_hex:
        args.admin_pw = decode_hex_utf16(args.admin_pw_hex)
    if not args.admin_pw:
        p.error('--admin-pw or --admin-pw-hex required')

    home = Path(args.home)
    cfg = load_env(home / 'config' / 'axp.env')
    if not wait_backend():
        print('backend did not become healthy in time — create the admin later with '
              'seed-admin', file=sys.stderr)
        return 1

    env = dict(os.environ)
    env.update({
        'TZ': 'UTC',
        'PYTHONPATH': '%s;%s' % (home / 'current' / 'site-packages', home / 'current' / 'app'),
        'DATABASE_URL': '127.0.0.1:%d' % DB_PORT,
        'DATABASE_ID': cfg.get('DATABASE_ID', 'axp'),
        'DATABASE_PW': cfg.get('DATABASE_PW', ''),
        'DATABASE_DB': cfg.get('DATABASE_DB', 'axp'),
        # memory-only handoff — never persisted
        'BOOTSTRAP_ADMIN_ID': args.admin_id,
        'BOOTSTRAP_ADMIN_PW': args.admin_pw,
    })
    r = subprocess.run(
        [str(home / 'runtime' / 'python' / 'python.exe'), '-m', 'server.command', 'seed-admin'],
        cwd=str(home / 'current' / 'app'), env=env,
        capture_output=True, text=True, timeout=120)
    print(r.stdout or r.stderr)
    return r.returncode


if __name__ == '__main__':
    sys.exit(main())
