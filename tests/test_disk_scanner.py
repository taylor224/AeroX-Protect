import config
from server.model import db
from server.model.disk import Disk
from server.service import disk_scanner


def test_write_verify(tmp_path):
    assert disk_scanner.write_verify(str(tmp_path)) is True
    assert disk_scanner.write_verify('/nonexistent/axp/zzz') is False


def test_discover_candidates(app_db, tmp_path, monkeypatch):
    root = tmp_path / 'axp'
    (root / 'disk1').mkdir(parents=True)
    (root / 'disk2').mkdir()
    monkeypatch.setattr(config, 'DISK_ROOT', str(root))

    paths = {c['mount_path'] for c in disk_scanner.discover_candidates()}
    assert str(root / 'disk1') in paths and str(root / 'disk2') in paths

    # register disk1 → it drops out of candidates
    d = Disk()
    d.name = 'd1'
    d.mount_path = str(root / 'disk1')
    d.role = 'record'
    db.session.add(d)
    db.session.commit()

    paths = {c['mount_path'] for c in disk_scanner.discover_candidates()}
    assert str(root / 'disk1') not in paths
    assert str(root / 'disk2') in paths
