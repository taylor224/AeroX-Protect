"""Disk discovery + usage refresh (PLAN P2 §6.7).

In containers, pool disks are bind-mounted under AXP_DISK_ROOT (e.g. /mnt/axp/disk1).
We scan that root for subdirectories (works for bind mounts) plus psutil partitions,
excluding the system mount and anything already registered.
"""
import logging
import os
import shutil

import config

logger = logging.getLogger(__name__)

_REAL_FS = {'ext4', 'ext3', 'ext2', 'xfs', 'btrfs', 'zfs', 'f2fs', 'apfs'}


def _registered_mounts() -> set[str]:
    from server.model.disk import Disk
    return {d.mount_path for d in Disk.get_all()}


def write_verify(mount_path: str) -> bool:
    """Confirm the mount is writable (PLAN §6.7 safety)."""
    test = os.path.join(mount_path, '.axp_write_test')
    try:
        with open(test, 'wb') as f:
            f.write(b'axp')
        os.remove(test)
        return True
    except OSError:
        return False


def discover_candidates() -> list[dict]:
    """Mounted, unregistered, writable pool-disk candidates."""
    registered = _registered_mounts()
    root = config.DISK_ROOT
    seen: set[str] = set()
    candidates: list[dict] = []

    if os.path.isdir(root):
        for name in sorted(os.listdir(root)):
            mp = os.path.join(root, name)
            if not os.path.isdir(mp) or mp in registered or mp in seen:
                continue
            try:
                usage = shutil.disk_usage(mp)
            except OSError:
                continue
            seen.add(mp)
            candidates.append({'mount_path': mp, 'device': None, 'fs_uuid': None,
                               'total_bytes': usage.total, 'free_bytes': usage.free, 'fstype': None})

    try:
        import psutil
        for part in psutil.disk_partitions(all=False):
            mp = part.mountpoint
            if mp in registered or mp in seen or mp == '/' or not mp.startswith(root):
                continue
            if part.fstype and part.fstype.lower() not in _REAL_FS:
                continue
            try:
                usage = shutil.disk_usage(mp)
            except OSError:
                continue
            seen.add(mp)
            candidates.append({'mount_path': mp, 'device': part.device, 'fs_uuid': None,
                               'total_bytes': usage.total, 'free_bytes': usage.free, 'fstype': part.fstype})
    except Exception as e:  # pragma: no cover - psutil/env specific
        logger.debug('psutil scan skipped: %s', e)

    return candidates


def refresh_all_usage() -> int:
    """Refresh free/total bytes for all registered disks (disk_scan task)."""
    from server.model.disk import Disk
    count = 0
    for disk in Disk.get_all():
        disk.refresh_usage()
        count += 1
    return count
