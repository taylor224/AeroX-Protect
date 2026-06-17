from flask import Blueprint
from sqlalchemy import text

import config
from server.model import db
from server.service.token import get_redis
from server.view.response import ResponseBuilder

context = Blueprint('healthz', __name__, url_prefix='/api/v1/healthz')


@context.route('', methods=('GET',))
def healthz():
    db_ok = False
    try:
        db.session.execute(text('SELECT 1'))
        db_ok = True
    except Exception:
        db.session.rollback()

    redis_ok = False
    try:
        redis_ok = bool(get_redis().ping())
    except Exception:
        redis_ok = False

    return ResponseBuilder.success({
        'db': db_ok,
        'redis': redis_ok,
        'version': config.VERSION,
    })
