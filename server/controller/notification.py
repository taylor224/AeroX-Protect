from server.exception import InvalidParameterException


class PushController:
    """Web-push subscription management. The in-app notification center and channel
    subscriptions were retired with the rule engine — flows' push nodes are the only
    notification sender, targeting the browser subscriptions registered here."""

    @classmethod
    def vapid_key(cls) -> dict:
        import config
        return {'public_key': config.VAPID_PUBLIC_KEY}

    @classmethod
    def subscribe(cls, user, data: dict) -> dict:
        endpoint = data.get('endpoint')
        keys = data.get('keys') or {}
        if not endpoint or not keys.get('p256dh') or not keys.get('auth'):
            raise InvalidParameterException('endpoint and keys.p256dh/auth required')
        from server.model.push_subscription import PushSubscription
        row = PushSubscription.upsert(user.id, endpoint, keys['p256dh'], keys['auth'], data.get('ua'))
        return {'id': str(row.id)}

    @classmethod
    def unsubscribe(cls, user, endpoint: str):
        from server.model.push_subscription import PushSubscription
        PushSubscription.disable_by_endpoint(user.id, endpoint)

    @classmethod
    def test(cls, user) -> dict:
        from server.driver import push as push_drv
        from server.model.push_subscription import PushSubscription
        subs = PushSubscription.active_for_user(user.id)
        sent = sum(1 for s in subs if push_drv.send(s, {'title': 'AeroX Protect', 'body': '테스트 알림',
                                                        'deeplink': '/'}).get('status') == 'success')
        return {'subscriptions': len(subs), 'sent': sent}
