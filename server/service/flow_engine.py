"""Flow execution engine — runs the visual automation graphs (server/model/flow.py).

Graph shape (stored verbatim from the editor):
  nodes: [{id, type, position, data}]        type ∈ flow.NODE_TYPES
  edges: [{id, source, sourceHandle, target}]

Branching: a trigger node exits on 'out'; a condition node exits on 'true'/'false';
every other node exits on 'ok' (success) or 'err' (failure). An edge with no
sourceHandle rides the node's default branch (out/true/ok). One handle may fan out
to any number of targets; each node runs at most once per run (cycle-safe).

Node params may reference run variables with {{path}} templates —
{{trigger.camera_id}}, {{trigger.camera_name}}, {{trigger.context.body.x}},
{{nodes.<node_id>.http_status}} … A template that is the whole string keeps the
raw value's type; embedded templates stringify.
"""
import json
import logging
import re
import time
from collections import deque

import config
from server.model.flow import (
    ACTION_NODE_TYPES,
    MAX_EDGES,
    MAX_NODES,
    NODE_CONDITION,
    NODE_DELAY,
    NODE_HANDLES,
    NODE_TRIGGER,
    NODE_TYPES,
)

logger = logging.getLogger(__name__)

MAX_STEPS = 100          # per-run node-execution cap (cycle/explosion guard)
MAX_DELAY_S = 60         # per-node delay cap — runs synchronously inside the worker task
MAX_TOTAL_DELAY_S = 120  # per-run sleep budget (chained delay nodes can't stall a worker)

_TPL = re.compile(r'{{\s*([A-Za-z0-9_.\-]+)\s*}}')

# trigger sources the generic bus can match (schedule fires from tick_schedules,
# incoming_webhook from its token URL, manual from the run API)
_BUS_SOURCES = ('event', 'object', 'system_event')


class _SystemActor:
    """Actor stand-in for engine-initiated controller calls (audit user_id = None)."""
    id = None


# ── dispatch entry points ─────────────────────────────────────────────────────
def on_trigger(trig) -> list:
    """Run every enabled flow with a trigger node matching this trigger. Called from the
    trigger bus (outbox events/objects, system events)."""
    from server.model.flow import Flow
    from server.model.flow_run import STATUS_SKIPPED, FlowRun
    runs = []
    for flow in Flow.active():
        starts = [n for n in flow.trigger_nodes() if _node_matches(n, trig)]
        if not starts:
            continue
        if _within_cooldown(flow):
            runs.append(FlowRun.create(
                flow_id=flow.id, trigger_type=trig.trigger_type, event_id=trig.event_id,
                camera_id=trig.camera_id, status=STATUS_SKIPPED, skip_reason='cooldown'))
            continue
        _mark_cooldown(flow)
        runs.append(run_flow(flow, trig, starts))
    return runs


def tick_schedules(now) -> int:
    """Beat every minute (schedule_trigger.tick): fire flows whose schedule trigger
    source's cron (KST) matches the current minute."""
    from server.model.flow import Flow
    from server.service import trigger_router
    from server.util.cron import cron_match
    fired = 0
    for flow in Flow.active():
        for node in flow.trigger_nodes():
            crons = [s.get('cron') for s in _sources(node)
                     if s.get('trigger_type') == 'schedule' and s.get('cron')]
            if any(cron_match(c, now) for c in crons):
                run_flow(flow, trigger_router.from_schedule(), [node])
                fired += 1
    return fired


def run_flow(flow, trig, start_nodes=None):
    """Walk the graph from the given trigger node(s) and log a FlowRun with the
    per-node trail. Never raises — node failures route to their 'err' branch."""
    from server.model import db, to_epoch_ms, utcnow
    from server.model.flow_run import STATUS_RUNNING, FlowRun

    graph = flow.graph or {}
    nodes = {n['id']: n for n in graph.get('nodes', []) if n.get('id')}
    out = _out_edges(graph.get('edges', []))
    starts = start_nodes if start_nodes is not None else flow.trigger_nodes()

    run = FlowRun.create(
        flow_id=flow.id, trigger_type=trig.trigger_type, event_id=trig.event_id,
        camera_id=trig.camera_id, status=STATUS_RUNNING, started_ts=utcnow(),
        trigger_snapshot=trig.serialize())
    flow.last_run_ts = utcnow()
    db.session.add(flow)
    db.session.commit()

    ctx = {'trigger': _trigger_vars(trig), 'nodes': {}}
    budget = {'delay_s': float(MAX_TOTAL_DELAY_S)}
    results, executed, queue = [], set(), deque()
    for tn in starts:
        if tn.get('id') in executed:
            continue
        executed.add(tn['id'])
        results.append({'node_id': tn['id'], 'type': NODE_TRIGGER, 'status': 'success',
                        'input': None, 'output': ctx['trigger'], 'error': None,
                        'started_ts': to_epoch_ms(utcnow()), 'duration_ms': 0})
        queue.extend(_targets(out, tn['id'], 'out', default='out'))

    steps = 0
    while queue and steps < MAX_STEPS:
        nid = queue.popleft()
        if nid in executed or nid not in nodes:
            continue
        executed.add(nid)
        steps += 1
        node = nodes[nid]
        started, t0 = utcnow(), time.monotonic()
        try:
            status, rendered, output, error, branches = _execute(node, trig, ctx, budget)
        except Exception as exc:                     # noqa: BLE001 — route to err branch
            logger.exception('flow node failed (flow %s node %s)', flow.id, nid)
            status, rendered, output, error, branches = 'failed', None, None, str(exc)[:200], ('err',)
        ctx['nodes'][nid] = output if isinstance(output, dict) else {'value': output}
        results.append({'node_id': nid, 'type': node.get('type'), 'status': status,
                        'input': rendered, 'output': output, 'error': error,
                        'started_ts': to_epoch_ms(started),
                        'duration_ms': int((time.monotonic() - t0) * 1000)})
        default = 'true' if node.get('type') == NODE_CONDITION else 'ok'
        for h in branches:
            queue.extend(_targets(out, nid, h, default=default))

    finished = utcnow()
    run.update(node_results=results, status=_summarize(results), finished_ts=finished,
               duration_ms=int((finished - run.started_ts).total_seconds() * 1000)
               if run.started_ts else None)
    return run


# ── node execution ────────────────────────────────────────────────────────────
def _execute(node, trig, ctx, budget) -> tuple[str, dict | None, dict | None, str | None, tuple]:
    """→ (status, rendered_input, output, error, branch_handles)"""
    ntype = node.get('type')
    params = render(dict(node.get('data') or {}), ctx)
    params.pop('label', None)

    if ntype == NODE_CONDITION:
        hit = _eval_condition(params, trig)
        return 'success', params, {'result': hit}, None, ('true' if hit else 'false',)

    if ntype == NODE_DELAY:
        secs = max(0.0, min(_num(params.get('seconds')), MAX_DELAY_S, budget['delay_s']))
        budget['delay_s'] -= secs
        time.sleep(secs)
        return 'success', params, {'slept_s': secs}, None, ('ok',)

    if ntype == 'record':
        res = _record(params, trig)
    elif ntype in ACTION_NODE_TYPES:
        from server.service import action_runner
        res = action_runner.run({'type': ntype, 'params': params,
                                 'target_id': params.get('target_id')}, trig)
    else:
        res = {'status': 'failed', 'error': 'unknown_node_type'}

    status = res.get('status') or 'failed'
    return (status, params, res, res.get('error'),
            ('ok',) if status == 'success' else ('err',))


def _eval_condition(cond: dict, trig) -> bool:
    """clauses: [{field, op, value}] on trigger fields (clause whitelist), or
    {left, op, value} where left is an already-rendered {{template}} value."""
    from server.service import clause
    clauses = cond.get('clauses') or []
    if not clauses:
        return True

    def one(cl):
        if 'left' in cl and cl.get('field') in (None, '', 'custom'):
            op = clause.OPS.get(cl.get('op'))
            if op is None:
                return False
            try:
                return bool(op(cl.get('left'), cl.get('value')))
            except (TypeError, ValueError):
                return False
        return clause.match_clause(cl, trig)

    hits = (one(cl) for cl in clauses)
    return any(hits) if cond.get('mode') == 'any' else all(hits)


def _record(params: dict, trig) -> dict:
    """Fixed-duration manual recording on the target (or trigger) camera."""
    from server.controller.recording import RecordingController
    from server.exception import InvalidParameterException
    from server.model.camera import Camera
    cam_id = params.get('camera_id') or trig.camera_id
    if not cam_id:
        return {'status': 'failed', 'error': 'no_camera'}
    cam = Camera.get_by_id(int(cam_id))
    if not cam:
        return {'status': 'failed', 'error': 'no_camera'}
    duration = int(params.get('duration_s') or 60)
    try:
        res = RecordingController.manual_start(cam, 'flow', _SystemActor(), duration_s=duration)
    except InvalidParameterException as exc:
        return {'status': 'failed', 'error': str(exc)[:200]}
    return {'status': 'success', **res}


# ── trigger-node matching ─────────────────────────────────────────────────────
def _node_matches(node: dict, trig) -> bool:
    return any(s.get('trigger_type') == trig.trigger_type and _source_matches(s, trig)
               for s in _sources(node))


def _source_matches(s: dict, trig) -> bool:
    tt = s.get('trigger_type')
    if tt not in _BUS_SOURCES:
        return False                     # schedule/incoming/manual fire via their own paths
    if s.get('camera_ids') and trig.camera_id not in _int_list(s['camera_ids']):
        return False
    if tt in ('event', 'system_event'):
        if s.get('event_types') and trig.type not in s['event_types']:
            return False
    elif tt == 'object':
        if s.get('classes') and not (set(trig.classes or []) & set(s['classes'])):
            return False
        if s.get('min_confidence') and (trig.score or 0) < s['min_confidence']:
            return False
    return True


def _sources(node: dict) -> list[dict]:
    return [s for s in (node.get('data') or {}).get('sources') or [] if isinstance(s, dict)]


def incoming_start_nodes(flow) -> list[dict]:
    return [n for n in flow.trigger_nodes()
            if any(s.get('trigger_type') == 'incoming_webhook' for s in _sources(n))]


# ── graph validation (save-time) ──────────────────────────────────────────────
def validate_graph(graph):
    """Raise InvalidParameterException unless the graph is a runnable node/edge set."""
    from server.exception import InvalidParameterException
    from server.service import clause as clause_mod

    def bad(msg):
        raise InvalidParameterException('graph: %s' % msg)

    if not isinstance(graph, dict):
        bad('must be an object with nodes/edges')
    nodes, edges = graph.get('nodes'), graph.get('edges')
    if not isinstance(nodes, list) or not isinstance(edges, list):
        bad('nodes and edges must be lists')
    if len(nodes) > MAX_NODES or len(edges) > MAX_EDGES:
        bad('too large (max %d nodes / %d edges)' % (MAX_NODES, MAX_EDGES))

    ids = set()
    for n in nodes:
        if not isinstance(n, dict) or not n.get('id') or not isinstance(n.get('id'), str):
            bad('every node needs a string id')
        if n['id'] in ids:
            bad('duplicate node id %s' % n['id'])
        ids.add(n['id'])
        if n.get('type') not in NODE_TYPES:
            bad('unknown node type %r' % n.get('type'))
        if n.get('data') is not None and not isinstance(n['data'], dict):
            bad('node data must be an object')
        if n.get('type') == NODE_CONDITION:
            for cl in (n.get('data') or {}).get('clauses') or []:
                if not isinstance(cl, dict) or cl.get('op') not in clause_mod.OPS:
                    bad('condition clause op must be one of %s' % sorted(clause_mod.OPS))

    if not any(n.get('type') == NODE_TRIGGER for n in nodes):
        bad('needs at least one trigger node')

    by_id = {n['id']: n for n in nodes}
    for e in edges:
        if not isinstance(e, dict) or e.get('source') not in ids or e.get('target') not in ids:
            bad('edge references a missing node')
        if by_id[e['target']].get('type') == NODE_TRIGGER:
            bad('a trigger node cannot be an edge target')
        h = e.get('sourceHandle')
        allowed = NODE_HANDLES.get(by_id[e['source']].get('type'), ('ok', 'err'))
        if h is not None and h not in allowed:
            bad('handle %r not valid for a %s node' % (h, by_id[e['source']].get('type')))


# ── template rendering ────────────────────────────────────────────────────────
def render(value, ctx):
    if isinstance(value, str):
        m = _TPL.fullmatch(value.strip())
        if m:
            return _lookup(m.group(1), ctx)          # whole-string template keeps the type
        return _TPL.sub(lambda mm: _fmt(_lookup(mm.group(1), ctx)), value)
    if isinstance(value, dict):
        return {k: render(v, ctx) for k, v in value.items()}
    if isinstance(value, list):
        return [render(v, ctx) for v in value]
    return value


def _lookup(path: str, ctx):
    cur = ctx
    for part in path.split('.'):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _fmt(v) -> str:
    if v is None:
        return ''
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return str(v)


def _trigger_vars(trig) -> dict:
    from server.service import action_runner
    out = action_runner.event_payload(trig)
    out['zone'] = trig.zone
    out['snapshot_path'] = trig.snapshot_path
    out['camera_name'] = None
    if trig.camera_id:
        try:
            from server.model.camera import Camera
            cam = Camera.get_by_id(int(trig.camera_id))
            out['camera_name'] = cam.name if cam else None
        except Exception:                            # noqa: BLE001 — vars are best-effort
            pass
    return out


# ── plumbing ──────────────────────────────────────────────────────────────────
def _out_edges(edges) -> dict:
    out = {}
    for e in edges or []:
        src, tgt = e.get('source'), e.get('target')
        if src and tgt:
            out.setdefault((src, e.get('sourceHandle') or None), []).append(tgt)
    return out


def _targets(out: dict, nid: str, handle: str, *, default: str) -> list:
    hit = list(out.get((nid, handle), []))
    if handle == default:                            # handle-less edges ride the default branch
        hit += out.get((nid, None), [])
    return hit


def _summarize(results: list) -> str:
    from server.model.flow_run import STATUS_FAILED, STATUS_PARTIAL, STATUS_SUCCESS
    st = [r.get('status') for r in results if r.get('type') != NODE_TRIGGER]
    if not st or all(s == 'success' for s in st):
        return STATUS_SUCCESS
    if any(s == 'success' for s in st):
        return STATUS_PARTIAL
    return STATUS_FAILED


def _redis():
    from server.service.token import get_redis
    return get_redis()


def _within_cooldown(flow) -> bool:
    if not (flow.cooldown_s or 0):
        return False
    try:
        return _redis().exists('%s:flow:cd:%s' % (config.REDIS_KEY_PREFIX, flow.id)) == 1
    except Exception:                                # noqa: BLE001 — redis down ≠ stop flows
        return False


def _mark_cooldown(flow):
    if not (flow.cooldown_s or 0):
        return
    try:
        _redis().setex('%s:flow:cd:%s' % (config.REDIS_KEY_PREFIX, flow.id), flow.cooldown_s, '1')
    except Exception:                                # noqa: BLE001
        pass


def _num(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _int_list(xs) -> list[int]:
    out = []
    for x in xs or []:
        try:
            out.append(int(x))
        except (TypeError, ValueError):
            pass
    return out
