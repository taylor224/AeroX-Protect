from server.exception import InvalidParameterException, RowNotFoundException
from server.model.webhook_endpoint import WebhookEndpoint


class WebhookController:
    @classmethod
    def list_webhooks(cls, purpose=None) -> list[dict]:
        return [w.to_dict() for w in WebhookEndpoint.list_for(purpose)]

    @classmethod
    def create(cls, data: dict, actor) -> dict:
        if not data.get('name') or not data.get('url'):
            raise InvalidParameterException('name and url required')
        return WebhookEndpoint.create(data, actor.id).to_dict()

    @classmethod
    def update(cls, uuid: str, data: dict, actor) -> dict:
        return cls._require(uuid).modify(data, actor.id).to_dict()

    @classmethod
    def delete(cls, uuid: str):
        cls._require(uuid).soft_delete()

    @classmethod
    def test(cls, uuid: str, data: dict) -> dict:
        from server.driver import webhook as webhook_drv
        ep = cls._require(uuid)
        sample = data.get('sample_event') or {'type': 'test', 'camera_id': None, 'ts': None, 'delivery': 'test'}
        return webhook_drv.deliver(ep, sample)

    @staticmethod
    def _require(uuid) -> WebhookEndpoint:
        w = WebhookEndpoint.get_by_uuid(uuid)
        if not w:
            raise RowNotFoundException()
        return w
