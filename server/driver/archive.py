"""Archive upload drivers (PLAN P6 M2). One `upload(target, src_abs, remote_name)` per
destination type. Credentials come from the target's Fernet-encrypted secrets (never logged).
S3 = boto3; SMB = smbprotocol(smbclient); local = filesystem copy.
"""
import logging
import os
import shutil

logger = logging.getLogger(__name__)


def upload(target, src_abs: str, remote_name: str) -> int:
    if target.type == 's3':
        return _s3_upload(target, src_abs, remote_name)
    if target.type == 'smb':
        return _smb_upload(target, src_abs, remote_name)
    if target.type == 'local':
        return _local_upload(target, src_abs, remote_name)
    raise ValueError('unknown archive target type: %s' % target.type)


def _local_upload(target, src_abs: str, remote_name: str) -> int:
    base = (target.config or {}).get('path') or '/tmp/axp-archive'
    dest = os.path.join(base, remote_name)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.copy2(src_abs, dest)
    return os.path.getsize(dest)


def _s3_upload(target, src_abs: str, remote_name: str) -> int:
    import boto3
    cfg = target.config or {}
    sec = target.get_secrets()
    client = boto3.client(
        's3',
        region_name=cfg.get('region') or None,
        endpoint_url=cfg.get('endpoint') or None,
        aws_access_key_id=sec.get('access_key') or None,
        aws_secret_access_key=sec.get('secret_key') or None,
    )
    key = '%s%s' % (cfg.get('prefix', ''), remote_name)
    client.upload_file(src_abs, cfg['bucket'], key)
    return os.path.getsize(src_abs)


def _smb_upload(target, src_abs: str, remote_name: str) -> int:
    import smbclient
    cfg = target.config or {}
    sec = target.get_secrets()
    if sec.get('username'):
        smbclient.ClientConfig(username=sec.get('username'), password=sec.get('password'))
    rel = ((cfg.get('path', '') or '').rstrip('/') + '/' + remote_name).lstrip('/').replace('/', '\\')
    unc = '\\\\%s\\%s\\%s' % (cfg['host'], cfg['share'], rel)
    parent = unc.rsplit('\\', 1)[0]
    try:
        smbclient.makedirs(parent, exist_ok=True)
    except Exception:
        pass
    with smbclient.open_file(unc, mode='wb') as dst, open(src_abs, 'rb') as fsrc:
        shutil.copyfileobj(fsrc, dst)
    return os.path.getsize(src_abs)
