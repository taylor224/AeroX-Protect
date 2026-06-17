"""P6 M4 — derived disk health surfacing."""
from server.model.disk import STATUS_OFFLINE, STATUS_ONLINE, STATUS_READONLY, Disk


def _disk(status, total, free):
    d = Disk()
    d.status = status
    d.total_bytes = total
    d.free_bytes = free
    return d


def test_disk_health_levels():
    assert _disk(STATUS_ONLINE, 100, 50).to_dict()['health'] == 'ok'        # 50%
    assert _disk(STATUS_ONLINE, 100, 12).to_dict()['health'] == 'warning'   # 88%
    assert _disk(STATUS_ONLINE, 100, 3).to_dict()['health'] == 'critical'   # 97%
    assert _disk(STATUS_OFFLINE, 100, 50).to_dict()['health'] == 'critical'  # offline
    assert _disk(STATUS_READONLY, 100, 50).to_dict()['health'] == 'warning'
