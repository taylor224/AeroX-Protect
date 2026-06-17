from server.exception import InvalidParameterException, RowNotFoundException
from server.model.ai_node import KIND_REMOTE, STATUS_DRAINING, AiNode
from server.service import ai_scheduler
from server.service.token import TokenService
from server.util.tool import safe_int


class AiNodeController:
    @classmethod
    def list_nodes(cls) -> list[dict]:
        return [n.to_dict() for n in AiNode.list_all()]

    @classmethod
    def create(cls, data: dict, actor) -> dict:
        """Pre-register a remote node and mint a one-time join token (PLAN §7.2)."""
        if not data.get('name'):
            raise InvalidParameterException('name required')
        node = AiNode.create(name=data['name'], kind=KIND_REMOTE, actor_id=actor.id)
        join_token = TokenService.issue_join_token(node.id)
        return {'node': node.to_dict(), 'join_token': join_token}

    @classmethod
    def issue_token(cls, node_id: int, data: dict, actor) -> dict:
        """(Re)issue a scoped node token; revoke the previous jti (rotation)."""
        node = AiNode.get_by_id(node_id)
        if not node:
            raise RowNotFoundException()
        if node.token_jti:
            TokenService.revoke(node.token_jti, 60)
        ttl = safe_int(data.get('ttl_days'), None)
        tok = TokenService.issue_node_token(node.uuid, ttl_days=ttl)
        node.update(token_jti=tok['jti'])
        return {'node_token': tok['token']}

    @classmethod
    def update(cls, node_id: int, data: dict, actor) -> dict:
        node = AiNode.get_by_id(node_id)
        if not node:
            raise RowNotFoundException()
        fields = {}
        if 'name' in data:
            fields['name'] = data['name']
        if 'enabled' in data:
            fields['enabled'] = bool(data['enabled'])
            if not fields['enabled']:
                fields['status'] = STATUS_DRAINING
        node.update(**fields)
        if 'enabled' in fields and not fields['enabled']:
            ai_scheduler.reassign(node.id)
        return node.to_dict()

    @classmethod
    def drain(cls, node_id: int):
        node = AiNode.get_by_id(node_id)
        if not node:
            raise RowNotFoundException()
        node.update(status=STATUS_DRAINING)
        ai_scheduler.reassign(node.id)

    @classmethod
    def delete(cls, node_id: int):
        node = AiNode.get_by_id(node_id)
        if not node:
            raise RowNotFoundException()
        if node.token_jti:
            TokenService.revoke(node.token_jti, 60)
        node.soft_delete()
        ai_scheduler.reassign(node.id)
