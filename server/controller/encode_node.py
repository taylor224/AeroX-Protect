from server.exception import InvalidParameterException, RowNotFoundException
from server.model.encode_assignment import EncodeAssignment
from server.model.encoding_node import KIND_REMOTE, STATUS_DRAINING, EncodingNode
from server.service import encode_scheduler
from server.service.token import TokenService
from server.util.tool import safe_int


class EncodeNodeController:
    @classmethod
    def list_nodes(cls) -> list[dict]:
        return [n.to_dict() for n in EncodingNode.list_all()]

    @classmethod
    def create(cls, data: dict, actor) -> dict:
        """Pre-register a remote encoder node and mint a one-time join token."""
        if not data.get('name'):
            raise InvalidParameterException('name required')
        node = EncodingNode.create(name=data['name'], kind=KIND_REMOTE, actor_id=actor.id)
        join_token = TokenService.issue_join_token(node.id)
        return {'node': node.to_dict(), 'join_token': join_token}

    @classmethod
    def issue_token(cls, node_id: int, data: dict, actor) -> dict:
        """(Re)issue a scoped node token; revoke the previous jti (rotation)."""
        node = EncodingNode.get_by_id(node_id)
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
        node = EncodingNode.get_by_id(node_id)
        if not node:
            raise RowNotFoundException()
        fields = {}
        if 'name' in data:
            fields['name'] = data['name']
        if 'endpoint' in data:
            fields['endpoint'] = data['endpoint'] or None
        if 'max_sessions' in data:
            fields['max_sessions'] = max(0, safe_int(data.get('max_sessions'), 0) or 0)
        if 'enabled' in data:
            fields['enabled'] = bool(data['enabled'])
            if not fields['enabled']:
                fields['status'] = STATUS_DRAINING
        node.update(**fields)
        if 'enabled' in fields and not fields['enabled']:
            encode_scheduler.reassign(node.id)
        return node.to_dict()

    @classmethod
    def drain(cls, node_id: int):
        node = EncodingNode.get_by_id(node_id)
        if not node:
            raise RowNotFoundException()
        node.update(status=STATUS_DRAINING)
        encode_scheduler.reassign(node.id)

    @classmethod
    def delete(cls, node_id: int):
        node = EncodingNode.get_by_id(node_id)
        if not node:
            raise RowNotFoundException()
        if node.token_jti:
            TokenService.revoke(node.token_jti, 60)
        node.soft_delete()
        encode_scheduler.reassign(node.id)

    @classmethod
    def list_assignments(cls) -> dict:
        return {'items': [a.to_dict() for a in EncodeAssignment.all_rows()]}

    @classmethod
    def rebalance(cls) -> dict:
        return encode_scheduler.rebalance()
