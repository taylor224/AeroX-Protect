"""Face embedding pipeline (PLAN P7 A8) — detector-node side.

Runs on person crops the detector produced: detect face → align → embed. The embedder is
pluggable like the A4 audio classifier / A1 text embedder — a real face model (InsightFace)
when present, else None (there is no meaningful "stub" face embedding). `build_report` is
pure + unit-tested; embedding + frame I/O are runtime-only. Reports (embedding + quality)
are batched by the node to `POST /ai/ingest/faces`, where the server matches them against
the known-identity registry.
"""
import logging

logger = logging.getLogger(__name__)

MIN_QUALITY = 40

_embedder = None  # None=untried, False=unavailable, object=loaded


def active_backend() -> str:
    return 'insightface' if _try_embedder() else 'none'


def embed_face(crop_bgr):
    """Face crop → (embedding list[float], quality 0–100) or None. No model → None."""
    ctx = _try_embedder()
    if ctx is None:
        return None
    return _embed_model(ctx, crop_bgr)  # pragma: no cover


def build_report(camera_id: int, embedding, backend: str, quality: int | None = None,
                 region=None, ts_ms: int | None = None) -> dict | None:
    """Assemble one ingest report from an embedding. None if empty or below quality floor."""
    if not embedding:
        return None
    if quality is not None and int(quality) < MIN_QUALITY:
        return None
    row = {'camera_id': camera_id, 'embedding': [float(x) for x in embedding], 'backend': backend}
    if quality is not None:
        row['quality'] = max(0, min(100, int(quality)))
    if region is not None:
        row['region'] = region
    if ts_ms is not None:
        row['ts'] = ts_ms
    return row


# ── real embedder (only where a face dep is installed) ───────────────────────
def _try_embedder():
    global _embedder
    if _embedder is False:
        return None
    if _embedder is None:
        try:  # pragma: no cover - exercised only where insightface is installed
            from insightface.app import FaceAnalysis  # type: ignore

            app = FaceAnalysis(name='buffalo_l')
            app.prepare(ctx_id=-1)            # CPU
            _embedder = {'app': app}
        except Exception:
            _embedder = False
            return None
    return _embedder


def _embed_model(ctx, crop_bgr):  # pragma: no cover
    faces = ctx['app'].get(crop_bgr)
    if not faces:
        return None
    f = max(faces, key=lambda x: getattr(x, 'det_score', 0))
    return list(map(float, f.normed_embedding)), int(getattr(f, 'det_score', 0.8) * 100)
