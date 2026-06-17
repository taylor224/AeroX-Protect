"""Write-disk selection + free-space watchdog (PLAN P2 §6.5, §6.8)."""
import hashlib
import os

import config
from server.model import db
from server.model.disk import ROLE_CACHE, ROLE_RECORD, Disk
from server.model.storage_policy import (
    STRATEGY_LEAST_USED,
    STRATEGY_PER_CAMERA,
    STRATEGY_ROUND_ROBIN,
)


def _hash_index(camera_id: int, n: int) -> int:
    return int(hashlib.md5(str(camera_id).encode()).hexdigest(), 16) % n


def abs_path(disk: Disk, rel_path: str) -> str:
    """Server-built absolute path (disk_id + rel_path only — no user input, §13)."""
    return os.path.join(disk.mount_path, rel_path)


def pick_write_disk(camera_id: int, policy) -> Disk | None:
    """Choose a writable disk for live segments. Prefers cache role, falls back to
    record (single-disk setups). Returns None if the pool has no headroom."""
    headroom = config.MIN_WRITE_HEADROOM_BYTES

    cache_pool = [d for d in Disk.get_writable((ROLE_CACHE,)) if d.usable_free_bytes > headroom]
    pool = cache_pool or [d for d in Disk.get_writable((ROLE_RECORD,)) if d.usable_free_bytes > headroom]
    if not pool:
        return None

    pool.sort(key=lambda d: d.id)  # stable ordering
    strategy = getattr(policy, 'balance_strategy', STRATEGY_LEAST_USED) if policy else STRATEGY_LEAST_USED

    if strategy == STRATEGY_PER_CAMERA:
        if policy and policy.pinned_disk_id:
            pinned = next((d for d in pool if d.id == policy.pinned_disk_id), None)
            if pinned:
                return pinned
        chosen = pool[_hash_index(camera_id, len(pool))]
        if policy and not policy.pinned_disk_id:
            policy.pinned_disk_id = chosen.id
            db.session.add(policy)
            db.session.commit()
        return chosen

    if strategy == STRATEGY_ROUND_ROBIN:
        from server.service.token import get_redis
        try:
            n = int(get_redis().incr('%s:rr:write_disk' % config.REDIS_KEY_PREFIX))
        except Exception:
            n = 0
        return pool[n % len(pool)]

    # least_used (weighted by capacity)
    return max(pool, key=lambda d: d.usable_free_bytes * (d.weight or 100))


def disks_needing_rotation(soft_margin: int = 0) -> list[Disk]:
    """record/cache disks whose free space is at/under reserved + margin."""
    out = []
    for disk in Disk.get_writable((ROLE_CACHE, ROLE_RECORD)):
        if (disk.free_bytes or 0) <= (disk.reserved_free_bytes or 0) + soft_margin:
            out.append(disk)
    return out


def pool_summary() -> dict:
    """Role-rollup of the pool for the storage dashboard (PLAN /storage/pool)."""
    disks = Disk.get_all()
    by_role: dict[str, dict] = {}
    warnings: list[str] = []
    for disk in disks:
        role = by_role.setdefault(disk.role, {'count': 0, 'total_bytes': 0, 'free_bytes': 0, 'reserved_bytes': 0})
        role['count'] += 1
        role['total_bytes'] += disk.total_bytes or 0
        role['free_bytes'] += disk.free_bytes or 0
        role['reserved_bytes'] += disk.reserved_free_bytes or 0
        if disk.status != 'online':
            warnings.append('disk_offline:%s' % disk.name)
        elif (disk.free_bytes or 0) <= (disk.reserved_free_bytes or 0):
            warnings.append('disk_full:%s' % disk.name)
    record_total = by_role.get(ROLE_RECORD, {}).get('total_bytes', 0) + by_role.get(ROLE_CACHE, {}).get('total_bytes', 0)
    return {'roles': by_role, 'record_total_bytes': record_total, 'warnings': warnings,
            'disks': [d.to_dict() for d in disks]}
