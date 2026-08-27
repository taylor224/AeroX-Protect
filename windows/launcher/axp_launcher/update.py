"""Self-update state machine: GitHub Releases → download → verify → junction swap.

Phases (mirrored by the SPA's SystemUpdateCard):
  idle → checking → precheck → downloading → verifying → extracting → backup_db
       → stopping_app → migrating → swapping → starting → health → done
                                        ↘ rollback → restoring → failed

Infra (mariadb/redis/go2rtc/caddy) and this launcher stay up throughout, so the
SPA keeps loading and /updater/* progress polling keeps answering while the
backend restarts. Rollback re-points the junction at the previous version and,
if the migration touched the DB, restores the pre-update dump.
"""
import hashlib
import json
import logging
import re
import shutil
import ssl
import subprocess
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

from . import LAUNCHER_VERSION, env, health, mariadb_init

logger = logging.getLogger(__name__)

APP_ASSET_RE = re.compile(r'^aeroxprotect-windows-x64-app-v(?P<v>[\d.]+)\.zip$')
MANIFEST_ASSET_RE = re.compile(r'^manifest-v[\d.]+\.json$')
CHECK_CACHE_TTL_S = 3600
FORCED_CHECK_TTL_S = 300
HEALTH_GATE_S = 120
KEEP_VERSIONS = 2


def _vtuple(v: str) -> tuple:
    return tuple(int(p) for p in re.findall(r'\d+', v or '0')[:4]) or (0,)


class Updater:
    def __init__(self, cfg: dict[str, str], supervisor):
        self.cfg = cfg
        self.sup = supervisor
        self.lock = threading.Lock()
        self.state = {'phase': 'idle', 'percent': 0, 'message': None, 'error': None,
                      'from': None, 'to': None}
        self._check_cache: dict | None = None
        self._check_at = 0.0
        self.repo = cfg.get('GITHUB_REPO', 'taylor224/AeroX-Protect')

    # ── status ───────────────────────────────────────────────────────────────
    def status(self) -> dict:
        return dict(self.state)

    def _set(self, phase: str, percent: int, message: str | None = None,
             error: str | None = None):
        self.state.update(phase=phase, percent=percent, message=message, error=error)
        logger.info('update: %s (%d%%) %s', phase, percent, message or '')

    # ── check ────────────────────────────────────────────────────────────────
    def _github_json(self, url: str) -> dict:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'AeroXProtect/%s' % env.current_version(),
            'Accept': 'application/vnd.github+json',
        })
        token = self.cfg.get('AXP_GITHUB_TOKEN')
        if token:
            req.add_header('Authorization', 'Bearer %s' % token)
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
            return json.loads(r.read().decode('utf-8'))

    def check(self, force: bool = False) -> dict:
        now = time.time()
        ttl = FORCED_CHECK_TTL_S if force else CHECK_CACHE_TTL_S
        if self._check_cache is not None and now - self._check_at < ttl:
            return self._check_cache
        rel = self._github_json(
            'https://api.github.com/repos/%s/releases/latest' % self.repo)
        latest = (rel.get('tag_name') or '').lstrip('v')
        assets = {a['name']: a for a in rel.get('assets', [])}
        manifest = self._load_manifest(assets)
        current = env.current_version()
        needs_installer = bool(
            manifest and _vtuple(manifest.get('min_launcher_version', '0'))
            > _vtuple(LAUNCHER_VERSION))
        installer = next((a for n, a in assets.items() if n.endswith('.exe')), None)
        result = {
            'latest_version': latest or None,
            'update_available': bool(latest) and _vtuple(latest) > _vtuple(current),
            'needs_installer': needs_installer,
            'notes_url': rel.get('html_url'),
            'installer_url': installer['browser_download_url'] if installer else None,
            'checked_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        }
        self._check_cache, self._check_at = result, now
        return result

    def _load_manifest(self, assets: dict) -> dict | None:
        name = next((n for n in assets if MANIFEST_ASSET_RE.match(n)), None)
        if name is None:
            return None
        try:
            return self._github_json(assets[name]['browser_download_url'])
        except Exception:
            logger.warning('manifest fetch failed for %s', name)
            return None

    # ── apply ────────────────────────────────────────────────────────────────
    def apply(self, version: str | None) -> bool:
        """Kick the update in a background thread. False if one is already running."""
        if not self.lock.acquire(blocking=False):
            return False
        t = threading.Thread(target=self._run, args=(version,), name='updater', daemon=True)
        t.start()
        return True

    def _run(self, version: str | None):
        db_changed = False
        dump_path: Path | None = None
        prev_version = env.current_version()
        try:
            self._set('checking', 2)
            rel = self._github_json(
                'https://api.github.com/repos/%s/releases/%s' % (
                    self.repo, 'tags/v%s' % version if version else 'latest'))
            target = (rel.get('tag_name') or '').lstrip('v')
            assets = {a['name']: a for a in rel.get('assets', [])}
            manifest = self._load_manifest(assets) or {}
            self.state.update({'from': prev_version, 'to': target})

            self._set('precheck', 5)
            if _vtuple(manifest.get('min_launcher_version', '0')) > _vtuple(LAUNCHER_VERSION):
                raise RuntimeError('needs_installer')
            if _vtuple(prev_version) < _vtuple(manifest.get('min_from_version', '0')):
                raise RuntimeError('min_from_version %s not met'
                                   % manifest.get('min_from_version'))
            app_asset = assets.get('aeroxprotect-windows-x64-app-v%s.zip' % target)
            if app_asset is None:
                raise RuntimeError('release has no app asset')
            free = shutil.disk_usage(env.AXP_HOME).free
            if free < app_asset.get('size', 0) * 3:
                raise RuntimeError('not enough free disk space')

            env.STAGING.mkdir(parents=True, exist_ok=True)
            zip_path = env.STAGING / ('v%s.zip' % target)
            self._download(app_asset['browser_download_url'], zip_path,
                           app_asset.get('size', 0))

            self._set('verifying', 45)
            want = (manifest.get('app') or {}).get('sha256')
            if want and self._sha256(zip_path) != want.lower():
                raise RuntimeError('sha256 mismatch')

            self._set('extracting', 50)
            vdir = env.version_dir(target)
            tmp = Path(str(vdir) + '.tmp')
            if tmp.exists():
                shutil.rmtree(tmp)
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(tmp)
            if vdir.exists():
                shutil.rmtree(vdir)
            tmp.rename(vdir)
            zip_path.unlink(missing_ok=True)

            self._set('backup_db', 72)
            if self.cfg.get('AXP_UPDATE_DB_BACKUP', 'true').lower() != 'false':
                env.BACKUPS.mkdir(parents=True, exist_ok=True)
                dump_path = env.BACKUPS / ('pre-v%s.sql' % target)
                if not mariadb_init.dump(self.cfg, dump_path):
                    logger.warning('pre-update dump failed — continuing without it')
                    dump_path = None
                self._prune_backups()

            self._set('stopping_app', 75)
            self.sup.stop_all(app_only=True)

            self._set('migrating', 80)
            db_changed = True   # DDL may be partially applied from here on
            self._run_app_cmd(vdir, ['-m', 'server.command', 'db-upgrade'])

            self._set('swapping', 85)
            self._swap_junction(vdir)

            self._run_app_cmd(vdir, ['-m', 'server.command', 'seed'])

            self._set('starting', 90)
            self.sup.start_app_tier()

            self._set('health', 95)
            deadline = time.monotonic() + HEALTH_GATE_S
            healthy = False
            while time.monotonic() < deadline:
                h = health.healthz(env.BACKEND_PORT) or {}
                if h.get('db') and h.get('redis') and h.get('version') == target:
                    healthy = True
                    break
                time.sleep(2)
            if not healthy:
                raise RuntimeError('health gate failed (backend not healthy on v%s)' % target)

            self._write_installed(target, prev_version)
            self._prune_versions(keep={target, prev_version})
            self._set('done', 100, message='updated to v%s' % target)
            self._check_cache = None
        except Exception as e:
            logger.exception('update failed')
            self._rollback(prev_version, dump_path if db_changed else None, str(e))
        finally:
            self.lock.release()

    # ── helpers ──────────────────────────────────────────────────────────────
    def _download(self, url: str, dest: Path, total: int):
        req = urllib.request.Request(url, headers={'User-Agent': 'AeroXProtect'})
        ctx = ssl.create_default_context()
        done = 0
        with urllib.request.urlopen(req, timeout=60, context=ctx) as r, open(dest, 'wb') as f:
            while True:
                chunk = r.read(1024 * 256)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                pct = 5 + int(done / total * 35) if total else 20
                self._set('downloading', min(pct, 40),
                          message='%d / %d MB' % (done // 1048576, (total or 0) // 1048576))

    @staticmethod
    def _sha256(path: Path) -> str:
        h = hashlib.sha256()
        with open(path, 'rb') as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b''):
                h.update(chunk)
        return h.hexdigest()

    def _run_app_cmd(self, version_root: Path, args: list[str]):
        r = subprocess.run(
            [str(env.PYTHON), '-u', *args],
            cwd=str(version_root / 'app'),
            env=env.app_env(self.cfg, version_root=version_root),
            capture_output=True, text=True, timeout=1800)
        if r.returncode != 0:
            raise RuntimeError('%s failed: %s' % (' '.join(args), (r.stderr or r.stdout)[-2000:]))

    def _swap_junction(self, vdir: Path):
        cur = env.CURRENT
        if cur.exists() or cur.is_symlink():
            # removes the junction/link itself, never the target tree
            try:
                cur.rmdir()
            except OSError:
                cur.unlink()
        r = subprocess.run(['cmd', '/c', 'mklink', '/J', str(cur), str(vdir)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError('junction swap failed: %s' % (r.stderr or r.stdout))

    def _rollback(self, prev_version: str, dump_path: Path | None, error: str):
        self._set('rollback', 96, error=error)
        try:
            self.sup.stop_all(app_only=True)
            prev_dir = env.version_dir(prev_version)
            if prev_dir.exists():
                self._swap_junction(prev_dir)
            if dump_path is not None and dump_path.exists():
                self._set('restoring', 97, error=error)
                if not mariadb_init.restore(self.cfg, dump_path):
                    logger.error('DB restore failed — manual intervention needed')
            self.sup.start_app_tier()
        except Exception:
            logger.exception('rollback itself failed')
        self._set('failed', 100, error=error,
                  message='rolled back to v%s' % prev_version)

    def _write_installed(self, current: str, previous: str):
        env.INSTALLED_FILE.write_text(json.dumps({
            'current': current, 'previous': previous,
            'updated_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        }, indent=2), encoding='utf-8')

    def _prune_versions(self, keep: set[str]):
        try:
            for d in env.VERSIONS.iterdir():
                if d.is_dir() and d.name.lstrip('v') not in keep:
                    shutil.rmtree(d, ignore_errors=True)
        except OSError:
            pass

    def _prune_backups(self, keep: int = 3):
        try:
            dumps = sorted(env.BACKUPS.glob('pre-v*.sql'),
                           key=lambda p: p.stat().st_mtime, reverse=True)
            for old in dumps[keep:]:
                old.unlink(missing_ok=True)
        except OSError:
            pass
