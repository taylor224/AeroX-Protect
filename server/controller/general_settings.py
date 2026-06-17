"""Global site settings (timezone, …). Currently just the site timezone used to interpret
recording schedules. Other globals (GPU, retention) live in their owning phases (AI settings,
storage/retention policy) and are intentionally not surfaced here.
"""
from server.exception import InvalidParameterException
from server.model.audit_log import AuditLog
from server.model.setting import Setting

DEFAULT_TZ = 'Asia/Seoul'


class GeneralSettingsController:
    @classmethod
    def get(cls) -> dict:
        return {
            'timezone': Setting.get_value('timezone', DEFAULT_TZ),
            # base URL used to build public share links (blank = use the request origin)
            'public_base_url': Setting.get_value('public_base_url', '') or '',
            # site default UI language (new users + login screen); per-user choice overrides it
            'default_language': Setting.get_value('default_language', 'ko') or 'ko',
            # server LAN IP advertised as a WebRTC ICE candidate so low-latency WebRTC live works
            # on the local network (blank = no candidate; clients use the MSE fallback)
            'webrtc_candidate_ip': Setting.get_value('webrtc_candidate_ip', '') or '',
        }

    @classmethod
    def update(cls, data: dict, actor) -> dict:
        if 'default_language' in data:
            lang = (data.get('default_language') or '').strip()
            if lang not in ('ko', 'en'):
                raise InvalidParameterException('default_language must be ko or en')
            Setting.set_value('default_language', lang)
            AuditLog.record('settings_updated', target='default_language', user_id=actor.id,
                            detail={'default_language': lang})
        tz = (data.get('timezone') or '').strip()
        if tz:
            try:
                from zoneinfo import ZoneInfo
                ZoneInfo(tz)                       # validate against the tz database
            except Exception:
                raise InvalidParameterException('invalid timezone')
            Setting.set_value('timezone', tz)
            AuditLog.record('settings_updated', target='timezone', user_id=actor.id, detail={'timezone': tz})
        if 'public_base_url' in data:
            url = (data.get('public_base_url') or '').strip().rstrip('/')
            if url and not url.startswith(('http://', 'https://')):
                raise InvalidParameterException('public_base_url must start with http:// or https://')
            Setting.set_value('public_base_url', url)
            AuditLog.record('settings_updated', target='public_base_url', user_id=actor.id,
                            detail={'public_base_url': url})
        if 'webrtc_candidate_ip' in data:
            ip = (data.get('webrtc_candidate_ip') or '').strip()
            if ip:
                import ipaddress
                try:
                    ipaddress.ip_address(ip)       # accept a literal IPv4/IPv6 only — a candidate
                except ValueError:                 # must be an address, not a hostname
                    raise InvalidParameterException('webrtc_candidate_ip must be a valid IP address')
            Setting.set_value('webrtc_candidate_ip', ip)
            AuditLog.record('settings_updated', target='webrtc_candidate_ip', user_id=actor.id,
                            detail={'webrtc_candidate_ip': ip})
        return cls.get()


class TwilioSettingsController:
    """SMS (Twilio) account config. SMS notifications fire from event triggers / automation;
    this just stores the account credentials. The token is write-only (never read back)."""

    @classmethod
    def get(cls) -> dict:
        from server.service import twilio_config
        return twilio_config.status()

    @classmethod
    def update(cls, data: dict, actor) -> dict:
        from server.service import twilio_config
        try:
            status = twilio_config.set_config(
                account_sid=data.get('account_sid'),
                auth_token=data.get('auth_token'),      # None = leave as-is, '' = clear
                from_number=data.get('from_number'),
                api_base=data.get('api_base'),
            )
        except RuntimeError as e:                        # crypto not configured
            raise InvalidParameterException(str(e))
        AuditLog.record('settings_updated', target='twilio', user_id=actor.id,
                        detail={'configured': status['configured']})  # never log the token
        return status
