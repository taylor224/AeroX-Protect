import uuid as uuid_lib

from flask import g

from server.exception import InvalidParameterException
from server.model.camera import Camera
from server.model.schedule import MODES, Schedule
from server.service.permission import PermissionService


def _validate_rules(rules: list) -> list:
    if not isinstance(rules, list):
        raise InvalidParameterException('rules must be a list')
    clean = []
    for r in rules:
        try:
            dow = int(r['day_of_week'])
            start = int(r['start_min'])
            end = int(r['end_min'])
        except (KeyError, TypeError, ValueError):
            raise InvalidParameterException('each rule needs integer day_of_week/start_min/end_min')
        if not (0 <= dow <= 6):
            raise InvalidParameterException('day_of_week must be 0..6')
        if not (0 <= start <= 1440 and 0 <= end <= 1440 and start != end):
            raise InvalidParameterException('require start_min/end_min in 0..1440 and start != end')
        if r.get('mode') not in MODES:
            raise InvalidParameterException('mode must be one of %s' % (MODES,))
        if start < end:
            clean.append(r)
        else:
            # midnight-crossing window (e.g. Mon 22:00–06:00) — the resolver only matches
            # same-day [start, end) intervals, so split into tonight + tomorrow-morning rules
            clean.append({**r, 'start_min': start, 'end_min': 1440})
            clean.append({**r, 'day_of_week': (dow + 1) % 7, 'start_min': 0, 'end_min': end})
    return clean


class ScheduleController:
    @classmethod
    def get_schedule(cls, camera_uuid: str) -> dict:
        camera = Camera.get_by_uuid(camera_uuid)
        rules = [s.to_dict() for s in Schedule.get_for_camera(camera.id)]
        return {'rules': rules}

    @classmethod
    def replace_schedule(cls, camera_uuid: str, rules: list, actor) -> dict:
        camera = Camera.get_by_uuid(camera_uuid)
        clean = _validate_rules(rules)
        created = Schedule.replace_for_camera(camera.id, clean, actor.id)
        return {'rules': [s.to_dict() for s in created]}

    @classmethod
    def apply_group(cls, rules: list, camera_uuids: list, actor) -> dict:
        clean = _validate_rules(rules)
        group = str(uuid_lib.uuid4()).replace('-', '')
        for r in clean:
            r['group_uuid'] = group
        applied = 0
        for cu in camera_uuids or []:
            try:
                camera = Camera.get_by_uuid(cu)
            except Exception:
                continue
            if not PermissionService.has_camera_scope(g.current_user, cu, 'view'):
                continue                         # silently skip cameras out of the actor's scope
            Schedule.replace_for_camera(camera.id, clean, actor.id)
            applied += 1
        return {'group_uuid': group, 'applied': applied}
