from server.model.ai_settings import AiSettings
from server.model.camera import Camera
from server.service import ai_config_resolver, ai_scheduler


class AiSettingsController:
    @classmethod
    def get(cls, camera_uuid) -> dict:
        g = AiSettings.ensure_global()
        out = {'global': g.to_dict()}
        if camera_uuid:
            camera = Camera.get_by_uuid(camera_uuid)
            override = AiSettings.get_for_camera(camera.id)
            out['camera_id'] = str(camera.id)
            out['camera_override'] = override.to_dict() if override else None
            out['effective'] = ai_config_resolver.effective_settings(camera.id)
        return out

    @classmethod
    def update_global(cls, data: dict, actor) -> dict:
        row = AiSettings.upsert(None, data, actor.id)
        ai_scheduler.touch()          # GPU toggle / model change → nodes reconfigure
        return row.to_dict()

    @classmethod
    def update_camera(cls, camera_uuid: str, data: dict, actor) -> dict:
        camera = Camera.get_by_uuid(camera_uuid)
        row = AiSettings.upsert(camera.id, data, actor.id)
        ai_scheduler.touch()
        return row.to_dict()
