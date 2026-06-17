from server.model import db
from server.model.disk import ROLE_CACHE, ROLE_RECORD, Disk
from server.service import storage_manager

GB = 1024 ** 3


def _disk(name, role=ROLE_RECORD, free_gb=100, reserved_gb=0, weight=100, status='online', enabled=True) -> Disk:
    d = Disk()
    d.name = name
    d.mount_path = '/tmp/axp_test/' + name
    d.role = role
    d.enabled = enabled
    d.status = status
    d.total_bytes = 200 * GB
    d.free_bytes = free_gb * GB
    d.reserved_free_bytes = reserved_gb * GB
    d.weight = weight
    db.session.add(d)
    db.session.commit()
    return d


def test_least_used_picks_most_free(app_db):
    _disk('a', free_gb=50)
    big = _disk('b', free_gb=150)
    from server.model.storage_policy import StoragePolicy
    pol = StoragePolicy()
    pol.balance_strategy = 'least_used'
    assert storage_manager.pick_write_disk(123, pol).id == big.id


def test_cache_role_preferred_over_record(app_db):
    _disk('rec', role=ROLE_RECORD, free_gb=150)
    cache = _disk('cache', role=ROLE_CACHE, free_gb=50)
    assert storage_manager.pick_write_disk(1, None).id == cache.id  # cache first even if smaller


def test_no_headroom_returns_none(app_db):
    _disk('tiny', free_gb=1, reserved_gb=1)   # usable ~0 < 2GB headroom
    assert storage_manager.pick_write_disk(1, None) is None


def test_per_camera_pins_disk(app_db):
    from server.model.storage_policy import StoragePolicy
    d1 = _disk('a', free_gb=100)
    d2 = _disk('b', free_gb=100)
    pol = StoragePolicy()
    pol.camera_id = 7
    pol.balance_strategy = 'per_camera'
    db.session.add(pol)
    db.session.commit()
    first = storage_manager.pick_write_disk(7, pol)
    assert first.id in (d1.id, d2.id)
    assert pol.pinned_disk_id == first.id            # pinned persisted
    assert storage_manager.pick_write_disk(7, pol).id == first.id  # stable


def test_offline_disk_excluded(app_db):
    _disk('off', status='offline', free_gb=100)
    assert storage_manager.pick_write_disk(1, None) is None
