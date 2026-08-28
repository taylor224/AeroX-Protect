"""System controller — native-install update/service management via the launcher.

The launcher (Windows service supervising all processes) owns downloads, version
swaps and restarts; the backend is only a thin authenticated proxy to its loopback
control API (config.LAUNCHER_URL + bearer config.LAUNCHER_TOKEN). Under Docker
LAUNCHER_URL is unset and the /system API answers 501 (feature card hides).
"""
import logging

import requests

import config
from server.model.audit_log import AuditLog
from server.service import update_ticket

logger = logging.getLogger(__name__)

_TIMEOUT = 15


class LauncherUnreachable(RuntimeError):
    pass


class SystemController:

    @staticmethod
    def available() -> bool:
        return bool(config.LAUNCHER_URL and config.LAUNCHER_TOKEN)

    @staticmethod
    def _request(method: str, path: str, **kwargs):
        url = config.LAUNCHER_URL.rstrip('/') + path
        headers = {'Authorization': 'Bearer %s' % config.LAUNCHER_TOKEN}
        try:
            r = requests.request(method, url, headers=headers, timeout=_TIMEOUT, **kwargs)
        except requests.RequestException as e:
            raise LauncherUnreachable(str(e)) from e
        if r.status_code >= 400:
            raise LauncherUnreachable('launcher answered %d' % r.status_code)
        return r.json()

    @staticmethod
    def _channel() -> str:
        from server.model.setting import Setting
        channel = (Setting.get_value('update_channel', 'stable') or 'stable').lower()
        return channel if channel in ('stable', 'beta', 'alpha') else 'stable'

    @classmethod
    def check_update(cls, force: bool = False) -> dict:
        channel = cls._channel()
        data = cls._request('GET', '/v1/update/check?channel=%s%s'
                            % (channel, '&force=1' if force else ''))
        data['current_version'] = config.VERSION
        data['channel'] = channel
        return data

    @classmethod
    def apply_update(cls, actor, version: str | None) -> dict:
        channel = cls._channel()
        AuditLog.record('system_update_started', target=version or 'latest',
                        user_id=actor.id if actor else None,
                        detail={'from': config.VERSION, 'to': version, 'channel': channel})
        ticket = update_ticket.issue()
        cls._request('POST', '/v1/update/apply', json={'version': version, 'channel': channel})
        return {
            'ticket': ticket['ticket'],
            'expires_in': ticket['expires_in'],
            # Same-origin path the SPA polls with bare fetch — the reverse proxy
            # routes /updater/* to the launcher, which stays up while the backend
            # restarts mid-update.
            'poll_url': '/updater/v1/update/status',
        }

    @classmethod
    def update_status(cls) -> dict:
        return cls._request('GET', '/v1/update/status')

    @classmethod
    def services(cls) -> dict:
        data = cls._request('GET', '/v1/status')
        data['current_version'] = config.VERSION
        return data
