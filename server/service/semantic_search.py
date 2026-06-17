"""Semantic search index + query (PLAN P6 A1). Indexes events into the `embeddings` table
and answers natural-language queries by cosine similarity (brute force, bounded). Backend
(clip/hash) is chosen by `semantic_embed` and recorded per row so query/pool stay matched.
"""
import os
from datetime import datetime

from server.model import db, to_epoch_ms
from server.model.camera import Camera
from server.model.embedding import Embedding
from server.model.event import Event
from server.service import semantic_embed

_INDEX_CAP = 2000
_SEARCH_LIMIT = 24


def _snapshot_bytes(ev) -> bytes | None:
    """Read an event's snapshot for CLIP image embedding; None if unavailable (→ CLIP text)."""
    path = getattr(ev, 'snapshot_path', None)
    if not path:
        return None
    try:
        if os.path.exists(path):
            with open(path, 'rb') as f:
                return f.read()
    except Exception:
        pass
    return None


def _event_text(ev, camera_name: str | None) -> str:
    parts = [ev.type or '']
    for attr in ('subtype', 'label'):
        v = getattr(ev, attr, None)
        if v:
            parts.append(str(v))
    if camera_name:
        parts.append(camera_name)
    return ' '.join(p for p in parts if p)


def index_events(camera_ids=None, start=None, end=None, limit: int = _INDEX_CAP) -> dict:
    backend = semantic_embed.active_backend()
    q = db.session.query(Event).filter(Event.deleted_at.is_(None))
    if camera_ids:
        q = q.filter(Event.camera_id.in_(camera_ids))
    if start is not None and end is not None:
        q = q.filter(Event.start_ts >= start, Event.start_ts <= end)
    rows = q.order_by(Event.start_ts.desc()).limit(limit).all()

    names: dict[int, str] = {}
    count = 0
    for ev in rows:
        if ev.camera_id not in names:
            try:                                          # tolerate events whose camera was deleted
                names[ev.camera_id] = Camera.get_by_id(ev.camera_id).name
            except Exception:
                names[ev.camera_id] = ''
        text = _event_text(ev, names[ev.camera_id])
        img = _snapshot_bytes(ev) if backend == 'clip' else None   # real visual embedding when CLIP is on
        vec = semantic_embed.embed_item(text, image_bytes=img)
        Embedding.upsert(source_type='event', source_ref=str(ev.id), camera_id=ev.camera_id,
                         ts=ev.start_ts, text=text, backend=backend, vector=vec)
        count += 1
    return {'indexed': count, 'backend': backend}


def search(query: str, camera_ids=None, start: datetime | None = None,
           end: datetime | None = None, limit: int = _SEARCH_LIMIT) -> dict:
    backend = semantic_embed.active_backend()
    if not (query or '').strip():
        return {'backend': backend, 'count': 0, 'items': []}
    qvec = semantic_embed.embed_query(query)
    pool = Embedding.search_pool(camera_ids, start, end, backend)
    scored = sorted(
        ((semantic_embed.cosine(qvec, e.vector), e) for e in pool),
        key=lambda x: x[0], reverse=True)
    items = [{
        'source_type': e.source_type, 'source_ref': e.source_ref,
        'camera_id': str(e.camera_id), 'ts': to_epoch_ms(e.ts),
        'text': e.text, 'score': round(float(score), 4),
    } for score, e in scored[:limit] if score > 0]
    return {'backend': backend, 'count': len(items), 'items': items}
