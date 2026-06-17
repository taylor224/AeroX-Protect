from server.exception import InvalidParameterException, NoPermissionException, RowNotFoundException
from server.model.notification import Notification
from server.model.notification_subscription import CHANNELS, NotificationSubscription
from server.util.tool import safe_int


class NotificationController:
    @classmethod
    def list_notifications(cls, user, args) -> dict:
        unread_only = str(args.get('unread', '')).lower() == 'true'
        total, unread, rows = Notification.list_for_user(
            user.id, unread_only=unread_only,
            page=max(1, safe_int(args.get('page'), 1)),
            items_per_page=min(100, max(1, safe_int(args.get('items_per_page'), 30))))
        return {'count': total, 'unread': unread, 'items': [n.to_dict() for n in rows]}

    @classmethod
    def read(cls, user, notif_id: int) -> dict:
        if not Notification.mark_read(notif_id, user.id):
            raise RowNotFoundException()
        return {}

    @classmethod
    def read_all(cls, user) -> dict:
        return {'updated': Notification.mark_all_read(user.id)}

    # ── subscriptions ──────────────────────────────────────────────────────────
    @classmethod
    def list_subscriptions(cls, user) -> list[dict]:
        return [s.to_dict() for s in NotificationSubscription.list_for_user(user.id)]

    @classmethod
    def create_subscription(cls, user, data: dict) -> dict:
        if data.get('channel') not in CHANNELS:
            raise InvalidParameterException('channel must be one of %s' % (CHANNELS,))
        return NotificationSubscription.create(user.id, data).to_dict()

    @classmethod
    def update_subscription(cls, user, sub_id: int, data: dict) -> dict:
        return cls._own(user, sub_id).modify(data).to_dict()

    @classmethod
    def delete_subscription(cls, user, sub_id: int):
        cls._own(user, sub_id).soft_delete()

    @staticmethod
    def _own(user, sub_id) -> NotificationSubscription:
        s = NotificationSubscription.get_by_id(sub_id)
        if not s:
            raise RowNotFoundException()
        if str(s.user_id) != str(user.id):
            raise NoPermissionException('not_owner')
        return s


class PushController:
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
