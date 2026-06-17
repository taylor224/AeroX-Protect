"""COCO class-id ↔ normalized label mapping (PLAN P4 §6.4). Search/triggers use the
normalized `label` so they stay stable across model swaps. Non-COCO models register
their own map; the worker reports both class_id and label, the server trusts label but
canonicalizes via this map when class_id is known."""

COCO_LABELS = {
    0: 'person', 1: 'bicycle', 2: 'car', 3: 'motorcycle', 4: 'airplane', 5: 'bus',
    6: 'train', 7: 'truck', 8: 'boat', 14: 'bird', 15: 'cat', 16: 'dog', 17: 'horse',
    18: 'sheep', 19: 'cow', 20: 'elephant', 21: 'bear', 22: 'zebra', 23: 'giraffe',
}
# A5 smoke/fire — non-COCO classes (need a dedicated detector model). Reserved high ids so
# they never collide with COCO; a smoke/fire model reports these labels and they normalize.
CUSTOM_LABELS = {1000: 'smoke', 1001: 'fire'}
SMOKE_LABELS = frozenset(CUSTOM_LABELS.values())

_ALL_LABELS = {**COCO_LABELS, **CUSTOM_LABELS}
LABEL_TO_ID = {v: k for k, v in _ALL_LABELS.items()}

# NVR security default whitelist (kept in sync with AiSettings.DEFAULT_LABELS)
DEFAULT_LABELS = ['person', 'car', 'truck', 'bus', 'motorcycle', 'bicycle', 'dog', 'cat', 'bird']


def normalize(class_id: int | None, label: str | None) -> tuple[int, str] | None:
    """Return (class_id, canonical_label) or None if neither resolves to a known class."""
    if class_id is not None and class_id in _ALL_LABELS:
        return class_id, _ALL_LABELS[class_id]
    if label:
        lab = label.strip().lower()
        if lab in LABEL_TO_ID:
            return LABEL_TO_ID[lab], lab
        if class_id is not None:
            return class_id, lab     # non-COCO model: trust reported label + class_id
    return None


def class_ids_for(labels: list[str] | None) -> list[int] | None:
    """Labels → COCO class ids for inference-time `classes=` filtering (None = all)."""
    if not labels:
        return None
    ids = [LABEL_TO_ID[l] for l in labels if l in LABEL_TO_ID]
    return ids or None
