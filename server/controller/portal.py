"""Remote-portal config + ICE servers (PLAN P9). Remote viewing works by default over the
TURN-free MSE/WebSocket path; ICE servers degrade to plain STUN until an admin configures a
TURN relay (for WebRTC through hard NATs). Config CRUD is gated by `portal:manage` permission
(route decorator) — no global feature flag.
"""
from server.exception import InvalidParameterException
from server.model.turn_config import TurnConfig
from server.service import turn

PROTOCOLS = ('udp', 'tcp')


class PortalController:
    @classmethod
    def ice_servers(cls, user) -> dict:
        # always STUN; TURN creds added when an admin has configured + enabled the relay
        return turn.ice_servers(user)

    @classmethod
    def get_config(cls) -> dict:
        return TurnConfig.ensure().to_dict()

    @classmethod
    def update_config(cls, data: dict, actor) -> dict:
        if data.get('turn_protocol') and data['turn_protocol'] not in PROTOCOLS:
            raise InvalidParameterException('turn_protocol must be udp or tcp')
        if 'stun_urls' in data and not isinstance(data['stun_urls'], list):
            raise InvalidParameterException('stun_urls must be a list')
        if data.get('ttl_seconds') is not None and int(data['ttl_seconds']) < 60:
            raise InvalidParameterException('ttl_seconds must be ≥ 60')
        return TurnConfig.update(data, actor_id=actor.id).to_dict()
