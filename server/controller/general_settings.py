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
            # idle-stop for live H.264 transcodes: stop after this many seconds without a
            # viewer (0 = keep always warm, the pre-idle-stop behavior)
            'live_transcode_idle_s': int(Setting.get_value('live_transcode_idle_s', 300) or 0),
            # native-install auto-update channel: stable = releases only, beta adds
            # -beta/-rc prereleases, alpha adds everything
            'update_channel': Setting.get_value('update_channel', 'stable') or 'stable',
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
        if 'update_channel' in data:
            channel = (data.get('update_channel') or '').strip().lower()
            if channel not in ('stable', 'beta', 'alpha'):
                raise InvalidParameterException('update_channel must be stable, beta or alpha')
            Setting.set_value('update_channel', channel)
            AuditLog.record('settings_updated', target='update_channel', user_id=actor.id,
                            detail={'update_channel': channel})
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
        if 'live_transcode_idle_s' in data:
            try:
                idle = int(data.get('live_transcode_idle_s'))
            except (TypeError, ValueError):
                raise InvalidParameterException('live_transcode_idle_s must be an integer (seconds)')
            if idle < 0 or idle > 86400:
                raise InvalidParameterException('live_transcode_idle_s must be 0..86400')
            Setting.set_value('live_transcode_idle_s', idle)
            AuditLog.record('settings_updated', target='live_transcode_idle_s', user_id=actor.id,
                            detail={'live_transcode_idle_s': idle})
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
