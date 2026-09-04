"""Web-admin CLIP installer for semantic search (PLAN P6 A1 follow-up).

pip-installs torch + open-clip-torch into the persistent extras dir
(config.AI_EXTRAS_DIR — on Windows `AXP_HOME\\extras\\site-packages-ai`, provided by
the launcher, outside the version tree so app auto-updates keep it), then warms the
model (downloads the ViT-B-32 weights) and hot-activates the CLIP backend in this
process via semantic_embed.reset() — no service restart needed. After any later
restart the launcher's PYTHONPATH already includes the extras dir, so CLIP stays on.

One job at a time, state in module memory: the status endpoint reports
`installed` from the filesystem, so a backend restart mid-poll degrades to
"installed but idle" rather than losing the outcome.
"""
import logging
import os
import shutil
import subprocess
import sys
import threading
from collections import deque
from pathlib import Path

import config
from server.service import semantic_embed

logger = logging.getLogger(__name__)

_PACKAGES = ('torch', 'open-clip-torch')
# extra-index (not index-url): open-clip-torch only exists on PyPI, while torch's
# +cpu/+cuXXX local-version wheels on the pytorch index outrank the plain PyPI
# version — so one resolve picks the right torch variant AND finds open-clip.
_TORCH_INDEX = {
    'cpu': 'https://download.pytorch.org/whl/cpu',
    'cuda': 'https://download.pytorch.org/whl/cu126',
}
VARIANTS = tuple(_TORCH_INDEX)

_LOG_TAIL = 40
_lock = threading.Lock()
_state: dict = {'phase': 'idle', 'variant': None, 'error': None, 'log': deque(maxlen=_LOG_TAIL)}


def supported() -> bool:
    return bool(config.AI_EXTRAS_DIR)


def installed() -> bool:
    if not supported():
        return False
    root = Path(config.AI_EXTRAS_DIR)
    return (root / 'open_clip').is_dir() and (root / 'torch').is_dir()


def installed_variant() -> str | None:
    """Variant marker written after a successful install (None = unknown/legacy)."""
    if not installed():
        return None
    try:
        v = (Path(config.AI_EXTRAS_DIR) / '.variant').read_text(encoding='utf-8').strip()
        return v if v in _TORCH_INDEX else None
    except OSError:
        return None


def remove() -> dict:
    """Delete the CLIP install (packages + weight cache) and pin the backend to hash.

    On Windows a previously-used model means torch DLLs are file-locked by this
    process — then we leave a marker and config.py finishes the cleanup on the next
    service start, before anything from the extras dir gets imported.
    """
    if not supported():
        raise RuntimeError('platform_unsupported')
    with _lock:
        if _state['phase'] in ('installing', 'warming'):
            raise RuntimeError('install_running')
        _state.update(phase='idle', variant=None, error=None)
        _state['log'].clear()
    semantic_embed.deactivate()

    extras = Path(config.AI_EXTRAS_DIR)
    cache = extras.parent / 'hf-cache'
    shutil.rmtree(extras, ignore_errors=True)
    shutil.rmtree(cache, ignore_errors=True)
    if extras.exists() or cache.exists():
        try:
            (extras.parent / '.remove-pending').write_text('1', encoding='utf-8')
        except OSError:
            pass
        return {'removed': False, 'restart_required': True}
    return {'removed': True, 'restart_required': False}


def status() -> dict:
    with _lock:
        return {
            'supported': supported(),
            'installed': installed(),
            'installed_variant': installed_variant(),
            'phase': _state['phase'],
            'variant': _state['variant'],
            'error': _state['error'],
            'log': list(_state['log']),
        }


def start(variant: str) -> bool:
    """Kick off the install thread. False = one is already running."""
    if variant not in _TORCH_INDEX:
        raise ValueError('variant must be one of %s' % (VARIANTS,))
    if not supported():
        raise RuntimeError('platform_unsupported')
    with _lock:
        if _state['phase'] in ('installing', 'warming'):
            return False
        _state.update(phase='installing', variant=variant, error=None)
        _state['log'].clear()
    threading.Thread(target=_run, args=(variant,), name='clip-install', daemon=True).start()
    return True


def _log(line: str) -> None:
    line = line.rstrip()
    if not line:
        return
    with _lock:
        _state['log'].append(line)


def _fail(message: str) -> None:
    logger.error('CLIP install failed: %s', message)
    with _lock:
        _state.update(phase='error', error=message)


def _run(variant: str) -> None:
    extras = Path(config.AI_EXTRAS_DIR)
    # fresh dir per install: switching CPU↔CUDA must not leave the other variant's
    # torch libs behind (pip --target can't uninstall). hf-cache stays — the
    # ViT-B-32 weights are variant-independent. Locked DLLs (model used since
    # boot) surface as pip file errors below → the UI says restart first.
    shutil.rmtree(extras, ignore_errors=True)
    if extras.exists():
        return _fail('extras dir is in use — restart services, then reinstall')
    try:
        extras.mkdir(parents=True, exist_ok=True)
        pending = extras.parent / '.remove-pending'
        if pending.exists():
            pending.unlink()
    except OSError as e:
        return _fail('extras dir not writable: %s' % e)

    cmd = [sys.executable, '-m', 'pip', 'install', '--upgrade',
           '--target', str(extras), '--extra-index-url', _TORCH_INDEX[variant],
           *_PACKAGES]
    _log('$ %s' % ' '.join(cmd))
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, errors='replace')
        for line in proc.stdout:  # type: ignore[union-attr]
            _log(line)
        code = proc.wait()
    except OSError as e:
        return _fail('pip launch failed: %s' % e)
    if code != 0:
        return _fail('pip exited %d' % code)

    with _lock:
        _state['phase'] = 'warming'
    _log('downloading model weights + loading CLIP ...')
    if str(extras) not in sys.path:
        sys.path.insert(0, str(extras))
    # first model load pulls ~600MB of weights; keep them next to the extras dir so
    # they survive updates too (the launcher sets HF_HOME to the same place)
    os.environ.setdefault('HF_HOME', str(extras.parent / 'hf-cache'))
    semantic_embed.reset()
    try:
        backend = semantic_embed.active_backend()
    except Exception as e:  # torch import segfault-adjacent failures land here
        return _fail('model load failed: %s' % e)
    if backend != 'clip':
        return _fail('deps installed but CLIP did not activate (check log)')
    try:
        (extras / '.variant').write_text(variant, encoding='utf-8')
    except OSError:
        pass
    _log('CLIP backend active')
    with _lock:
        _state['phase'] = 'done'
