"""License-plate OCR pipeline (PLAN P7 A7) — detector-node side.

Runs on vehicle crops the detector already produced: detect plate → (deskew) → OCR. The
OCR engine is pluggable like the A4 audio classifier and A1 embedder — a real plate-OCR
model when present, else a no-op (there is NO responsible "stub OCR": a guessed plate is
worse than none for a watchlist). `build_report` is pure + unit-tested; the OCR + frame I/O
are runtime-only. Reports are batched by the node to `POST /ai/ingest/plates`.
"""
import logging

logger = logging.getLogger(__name__)

MIN_CONFIDENCE = 50

_ocr = None  # None=untried, False=unavailable, object=loaded


def active_backend() -> str:
    return 'model' if _try_ocr() else 'none'


def read_plate(crop_bgr):
    """OCR a vehicle/plate crop → (text, confidence 0–100) or None. No model → None."""
    ctx = _try_ocr()
    if ctx is None:
        return None
    return _read_model(ctx, crop_bgr)  # pragma: no cover


def build_report(camera_id: int, plate_text: str, confidence: int, region=None,
                 ts_ms: int | None = None, vehicle_label: str | None = None) -> dict | None:
    """Assemble one ingest report row from an OCR result. None if below the confidence floor
    or empty (so the node never posts junk)."""
    text = (plate_text or '').strip()
    if not text or int(confidence) < MIN_CONFIDENCE:
        return None
    row = {'camera_id': camera_id, 'plate_text': text[:24], 'confidence': max(0, min(100, int(confidence)))}
    if region is not None:
        row['region'] = region
    if ts_ms is not None:
        row['ts'] = ts_ms
    if vehicle_label:
        row['vehicle_label'] = vehicle_label
    return row


# ── real OCR (only where a plate-OCR dep is installed) ───────────────────────
def _try_ocr():
    global _ocr
    if _ocr is False:
        return None
    if _ocr is None:
        try:  # pragma: no cover - exercised only where an OCR model is installed
            from fast_plate_ocr import ONNXPlateRecognizer  # type: ignore

            _ocr = {'reader': ONNXPlateRecognizer('global-plates-mobile-vit-v2-model')}
        except Exception:
            _ocr = False
            return None
    return _ocr


def _read_model(ctx, crop_bgr):  # pragma: no cover
    try:
        texts = ctx['reader'].run(crop_bgr)
        if not texts:
            return None
        return str(texts[0]).upper(), 90
    except Exception:
        logger.exception('plate OCR failed')
        return None
