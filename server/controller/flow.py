from server.exception import InvalidParameterException, RowNotFoundException
from server.model.flow import Flow
from server.model.flow_run import FlowRun
from server.service import flow_engine, trigger_router
from server.util.tool import safe_int


def _bool(v):
    return {'true': True, 'false': False}.get(str(v).lower()) if v is not None else None


class FlowController:
    @classmethod
    def list_flows(cls, args) -> dict:
        total, rows = Flow.list_flows(
            enabled=_bool(args.get('enabled')),
            page=max(1, safe_int(args.get('page'), 1)),
            items_per_page=min(200, max(1, safe_int(args.get('items_per_page'), 50))))
        return {'count': total, 'items': [f.to_dict() for f in rows]}

    @classmethod
    def get(cls, flow_uuid: str) -> dict:
        return cls._require(flow_uuid).to_dict()

    @classmethod
    def create(cls, data: dict, actor) -> dict:
        cls._validate(data)
        return Flow.create(data, actor.id).to_dict()

    @classmethod
    def update(cls, flow_uuid: str, data: dict, actor) -> dict:
        flow = cls._require(flow_uuid)
        if 'graph' in data:
            cls._validate({'name': flow.name, **data})
        return flow.modify(data, actor.id).to_dict()

    @classmethod
    def delete(cls, flow_uuid: str):
        cls._require(flow_uuid).soft_delete()

    @classmethod
    def enable(cls, flow_uuid: str, enabled: bool, actor) -> dict:
        return cls._require(flow_uuid).modify({'enabled': bool(enabled)}, actor.id).to_dict()

    @classmethod
    def run(cls, flow_uuid: str, data: dict) -> dict:
        """Manual/test run: starts from every trigger node with a synthetic manual trigger."""
        flow = cls._require(flow_uuid)
        if not flow.trigger_nodes():
            raise InvalidParameterException('flow has no trigger node')
        trig = trigger_router.from_manual(
            camera_id=safe_int(data.get('camera_id'), None) if data.get('camera_id') else None,
            context=data.get('context'))
        return flow_engine.run_flow(flow, trig).to_dict()

    @classmethod
    def fire_incoming(cls, token: str, body: dict | None, query: dict | None) -> dict:
        """Inbound-webhook trigger: the URL's opaque token IS the credential. Starts only
        from trigger nodes that opted into incoming_webhook; minimal response (no
        flow internals leaked to an unauthenticated caller)."""
        flow = Flow.get_by_incoming_token(token)
        if not flow or not flow.enabled:
            raise RowNotFoundException()
        starts = flow_engine.incoming_start_nodes(flow)
        if not starts:
            raise RowNotFoundException()
        trig = trigger_router.from_incoming(flow, body=body, query=query)
        run = flow_engine.run_flow(flow, trig, starts)
        return {'status': run.status}

    @classmethod
    def runs(cls, flow_uuid: str, args) -> dict:
        flow = cls._require(flow_uuid)
        total, rows = FlowRun.list_runs(
            flow_id=flow.id, status=args.get('status'),
            page=max(1, safe_int(args.get('page'), 1)),
            items_per_page=min(200, max(1, safe_int(args.get('items_per_page'), 50))))
        return {'count': total, 'items': [r.to_dict(with_detail=False) for r in rows]}

    @classmethod
    def run_detail(cls, flow_uuid: str, run_id) -> dict:
        flow = cls._require(flow_uuid)
        run = FlowRun.get_by_id(safe_int(run_id, 0))
        if not run or run.flow_id != flow.id:
            raise RowNotFoundException()
        return run.to_dict()

    @staticmethod
    def _require(flow_uuid) -> Flow:
        flow = Flow.get_by_uuid(flow_uuid)
        if not flow:
            raise RowNotFoundException()
        return flow

    @staticmethod
    def _validate(data):
        if not data.get('name'):
            raise InvalidParameterException('name required')
        flow_engine.validate_graph(data.get('graph') if data.get('graph') is not None
                                   else {'nodes': [], 'edges': []})
