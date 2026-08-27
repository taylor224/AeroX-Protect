"""Installer post-install step (run by Inno Setup with the bundled runtime python):

    python.exe postinstall.py --home C:\\AeroXProtect --http-port 3000
        --disk-root C:\\AeroXProtect\\storage --admin-id admin --admin-pw ****

Idempotent: re-running (upgrade install) keeps an existing axp.env and datadir.
Does: dirs, secret generation, axp.env, template rendering (__AXP_HOME__),
config ACLs, current-junction creation, firewall rules, WinSW service install.
"""
import argparse
import base64
import os
import secrets
import subprocess
import sys
from pathlib import Path


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument('--home', required=True)
    p.add_argument('--version', required=True)
    p.add_argument('--http-port', default='3000')
    p.add_argument('--disk-root', default='')
    p.add_argument('--admin-id', default='admin')
    p.add_argument('--admin-pw', default='')
    return p.parse_args()


def _rand_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def _fernet_key() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()


def write_env(home: Path, args) -> Path:
    """config\\axp.env — created once; later installs keep existing secrets."""
    env_file = home / 'config' / 'axp.env'
    if env_file.exists():
        print('axp.env exists — keeping current secrets')
        return env_file
    disk_root = args.disk_root or str(home / 'storage')
    lines = [
        '# AeroXProtect native config — generated at install. Guard this file:',
        '# it holds the secrets for the DB, JWT signing and camera credentials.',
        'SECRET_KEY=%s' % _rand_token(48),
        'JWT_SECRET=%s' % _rand_token(48),
        'CREDENTIAL_ENC_KEY=%s' % _fernet_key(),
        'AXP_LAUNCHER_TOKEN=%s' % _rand_token(32),
        'DATABASE_ID=axp',
        'DATABASE_PW=%s' % secrets.token_hex(16),   # alphanumeric — safe in the DSN
        'DATABASE_DB=axp',
        'DB_ROOT_PW=%s' % secrets.token_hex(16),
        'AXP_HTTP_PORT=%s' % args.http_port,
        'AXP_DISK_ROOT=%s' % disk_root,
        'GITHUB_REPO=taylor224/AeroX-Protect',
        'AXP_UPDATE_DB_BACKUP=true',
        'BOOTSTRAP_ADMIN_ID=%s' % args.admin_id,
        'BOOTSTRAP_ADMIN_PW=%s' % args.admin_pw,
        'ENCODER_HWACCEL=none',
    ]
    env_file.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return env_file


def render_templates(home: Path):
    """Fill __AXP_HOME__ into the config templates shipped under launcher\\templates.
    Only writes files that don't exist yet (user edits survive upgrades)."""
    tpl_dir = home / 'launcher' / 'templates'
    home_fwd = str(home).replace('\\', '/')
    targets = {
        'Caddyfile.tmpl': home / 'config' / 'Caddyfile',
        'my.ini.tmpl': home / 'config' / 'my.ini',
        'redis.windows.conf.tmpl': home / 'config' / 'redis.conf',
        'go2rtc.windows.yaml': home / 'config' / 'go2rtc.yaml',
    }
    for src_name, dst in targets.items():
        src = tpl_dir / src_name
        if not src.exists() or dst.exists():
            continue
        text = src.read_text(encoding='utf-8').replace('__AXP_HOME__', home_fwd)
        dst.write_text(text, encoding='utf-8')
        print('rendered %s' % dst)


def make_dirs(home: Path, disk_root: str):
    for d in ('config', 'versions', 'data/mariadb', 'data/redis', 'data/logs',
              'data/staging', 'data/backups', 'data/media/thumbnails'):
        (home / d).mkdir(parents=True, exist_ok=True)
    root = Path(disk_root or (home / 'storage'))
    (root / 'disk1').mkdir(parents=True, exist_ok=True)


def secure_config(home: Path):
    """Lock config\\ down to SYSTEM + Administrators (it holds all secrets)."""
    subprocess.run(['icacls', str(home / 'config'), '/inheritance:r',
                    '/grant:r', 'SYSTEM:(OI)(CI)F', '/grant:r', '*S-1-5-32-544:(OI)(CI)F'],
                   capture_output=True)


def make_junction(home: Path, version: str):
    cur = home / 'current'
    target = home / 'versions' / ('v%s' % version)
    if cur.exists():
        try:
            cur.rmdir()
        except OSError:
            return   # junction already points somewhere — an update owns it now
    subprocess.run(['cmd', '/c', 'mklink', '/J', str(cur), str(target)],
                   capture_output=True, check=True)


def firewall(home: Path, http_port: str):
    rules = [
        ('AeroXProtect Web', http_port, 'TCP'),
        ('AeroXProtect WebRTC TCP', '8555', 'TCP'),
        ('AeroXProtect WebRTC UDP', '8555', 'UDP'),
    ]
    for name, port, proto in rules:
        subprocess.run(['netsh', 'advfirewall', 'firewall', 'delete', 'rule',
                        'name=%s' % name], capture_output=True)
        subprocess.run(['netsh', 'advfirewall', 'firewall', 'add', 'rule',
                        'name=%s' % name, 'dir=in', 'action=allow',
                        'protocol=%s' % proto, 'localport=%s' % port],
                       capture_output=True)


def install_service(home: Path):
    svc = home / 'launcher' / 'axp-service.exe'
    xml = home / 'launcher' / 'axp-service.xml'
    xml.write_text(
        xml.read_text(encoding='utf-8').replace('__AXP_HOME__', str(home)),
        encoding='utf-8')
    q = subprocess.run([str(svc), 'status'], capture_output=True, text=True)
    if 'NonExistent' not in (q.stdout + q.stderr) and q.returncode == 0:
        print('service already installed')
        return
    r = subprocess.run([str(svc), 'install'], capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit('service install failed: %s' % (r.stderr or r.stdout))


def main():
    args = parse_args()
    home = Path(args.home)
    make_dirs(home, args.disk_root)
    write_env(home, args)
    render_templates(home)
    secure_config(home)
    make_junction(home, args.version)
    firewall(home, args.http_port)
    install_service(home)
    print('post-install complete')


if __name__ == '__main__':
    sys.exit(main())
