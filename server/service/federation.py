"""Federation sync + aggregation (PLAN P8). `sync_member` pulls a member's camera list into
the local cache and updates its status; `aggregate_cameras`/`aggregate_events` present a
unified hub view. Event aggregation fans out live (best-effort — a down member is skipped,
not fatal). The member API client is mocked in tests.
"""
import logging

from server.driver.federation import FederationClient, FederationError
from server.model.federation_camera import FederationCamera
from server.model.federation_member import (
    STATUS_ERROR,
    STATUS_OFFLINE,
    STATUS_ONLINE,
    FederationMember,
)

logger = logging.getLogger(__name__)


def _client(member: FederationMember) -> FederationClient:
    return FederationClient(member.base_url, member.get_token())


def sync_member(member_id: int) -> dict:
    """Pull the member's cameras into the cache + refresh its status. Returns a small report."""
    member = FederationMember.get_by_id(member_id)
    if not member:
        return {'ok': False, 'error': 'not_found'}
    if not member.enabled:
        return {'ok': False, 'error': 'disabled'}

    try:
        state = _client(member).state()
        if not isinstance(state, dict) or not isinstance(state.get('cameras'), list):
            # a 200 without a cameras list (version skew / proxy stub) must not
            # be treated as "member has zero cameras" — that wipes the cache
            member.mark_sync(STATUS_ERROR, error='malformed_state')
            return {'ok': False, 'error': 'malformed_state'}
        count = FederationCamera.replace_for_member(member.id, state['cameras'])
        member.mark_sync(STATUS_ONLINE, camera_count=count)
        return {'ok': True, 'cameras': count}
    except FederationError as e:
        status = STATUS_OFFLINE if 'unreachable' in str(e) else STATUS_ERROR
        member.mark_sync(status, error=str(e))
        return {'ok': False, 'error': str(e)}
    except Exception as e:                                   # never let one member break a sweep
        logger.exception('federation sync failed member=%s', member_id)
        member.mark_sync(STATUS_ERROR, error=str(e))
        return {'ok': False, 'error': str(e)}


def sync_all() -> dict:
    members = FederationMember.list_enabled()
    results = {str(m.id): sync_member(m.id) for m in members}
    ok = sum(1 for r in results.values() if r.get('ok'))
    return {'members': len(members), 'synced': ok, 'results': results}


def aggregate_cameras() -> list[dict]:
    """All cached remote cameras across enabled members, tagged with the member name."""
    members = {m.id: m for m in FederationMember.list_enabled()}
    rows = FederationCamera.for_members(list(members))
    out = []
    for r in rows:
        m = members.get(r.member_id)
        out.append({**r.to_dict(), 'member_name': m.name if m else None})
    return out


def aggregate_events(params: dict | None = None, per_member: int = 50) -> list[dict]:
    """Live fan-out to each enabled member's /ext/events, merged + sorted by ts desc.
    Best-effort: a failing member is skipped (logged), not fatal."""
    params = dict(params or {})
    params.setdefault('items_per_page', per_member)
    merged = []
    for m in FederationMember.list_enabled():
        try:
            for ev in _client(m).list_events(params):
                merged.append({**ev, 'member_id': str(m.id), 'member_name': m.name})
        except FederationError as e:
            logger.info('federation events skip member=%s: %s', m.id, e)
        except Exception:
            logger.exception('federation events error member=%s', m.id)
    def _ts(e) -> int:
        v = e.get('start_ts') or e.get('ts') or 0
        try:
            return int(v)
        except (ValueError, TypeError):      # tolerate a member returning a string ts
            return 0
    merged.sort(key=_ts, reverse=True)
    return merged
