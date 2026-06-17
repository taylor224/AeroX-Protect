"""Event-policy resolution by specificity (PLAN §4.2, §5.3).

Priority: (camera,type,subtype) > (camera,type) > (camera,*) > (global,type) > (global,*).
A policy with a specific subtype only matches that subtype; subtype=NULL matches all."""
from server.model.event_policy import EventPolicy


def _rank(policy: EventPolicy, camera_id: int, event_type: str, subtype: str | None) -> int:
    rank = 0
    rank += 1000 if policy.camera_id == camera_id else 0          # camera-specific beats global
    if policy.event_type == event_type:
        rank += 100
    elif policy.event_type == '*':
        rank += 10
    if policy.subtype and subtype and policy.subtype == subtype:
        rank += 5
    return rank


def resolve(camera_id: int, event_type: str, subtype: str | None = None,
            at_ts=None) -> EventPolicy | None:
    best, best_rank = None, -1
    for policy in EventPolicy.get_candidates(camera_id, event_type):
        # a subtype-specific policy excludes other subtypes
        if policy.subtype and policy.subtype != (subtype or ''):
            continue
        r = _rank(policy, camera_id, event_type, subtype)
        if r > best_rank:
            best, best_rank = policy, r
    return best
