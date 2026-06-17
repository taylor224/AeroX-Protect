"""Pluggable embedder for semantic search (PLAN P6 A1).

CLIP (image↔text joint space) is the target backend, but torch/open_clip are NOT in the
base image (they live in the separate detector). So the embedder is pluggable:

- `clip`  — lazy-loaded if open_clip+torch are importable (item = image embedding, query =
            text embedding in the same space). Activates with ZERO code change once the
            dep is present.
- `hash`  — dependency-free fallback that runs everywhere NOW: a deterministic char-trigram
            hashing vector over the item's TEXT (labels/type) and the query text. This is
            text-semantic-lite (not pixel-level), enough to ship + test the full pipeline.

Both produce L2-normalized vectors of the same `DIM`, so cosine similarity is comparable
within a backend. `active_backend()` reports which is live.
"""
import hashlib
import math
import re

DIM = 256

_clip = None  # None=untried, False=unavailable, dict=loaded


def _tokens(text: str) -> list[str]:
    return re.findall(r'[a-z0-9가-힣]+', (text or '').lower())


def _hash_vector(text: str) -> list[float]:
    vec = [0.0] * DIM
    for tok in _tokens(text):
        grams = [tok] + [tok[i:i + 3] for i in range(len(tok) - 2)]  # whole word + trigrams
        for g in grams:
            h = int(hashlib.md5(g.encode()).hexdigest(), 16)
            vec[h % DIM] += 1.0 if (h >> 8) & 1 else -1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _try_clip():
    """Return a loaded CLIP context dict, or None if unavailable. Lazy + cached."""
    global _clip
    if _clip is False:
        return None
    if _clip is None:
        try:  # pragma: no cover - exercised only where torch is installed
            import open_clip  # type: ignore
            import torch  # type: ignore

            model, _, preprocess = open_clip.create_model_and_transforms(
                'ViT-B-32', pretrained='laion2b_s34b_b79k')
            tokenizer = open_clip.get_tokenizer('ViT-B-32')
            model.eval()
            _clip = {'model': model, 'preprocess': preprocess, 'tokenizer': tokenizer, 'torch': torch}
        except Exception:
            _clip = False
            return None
    return _clip


def active_backend() -> str:
    return 'clip' if _try_clip() else 'hash'


def embed_query(text: str) -> list[float]:
    ctx = _try_clip()
    if ctx:  # pragma: no cover
        torch = ctx['torch']
        with torch.no_grad():
            feat = ctx['model'].encode_text(ctx['tokenizer']([text]))
            feat = feat / feat.norm(dim=-1, keepdim=True)
        return feat[0].tolist()
    return _hash_vector(text)


def embed_item(text: str, image_bytes: bytes | None = None) -> list[float]:
    """Embed an index item. With CLIP + an image → image embedding (joint space with the
    text query — true visual search). With CLIP but no image → CLIP text embedding (same
    512-dim space as the query, so cosine is valid). Without CLIP → hash text vector.
    Critically, item and query MUST land in the same space/dim per backend."""
    ctx = _try_clip()
    if ctx and image_bytes:  # pragma: no cover
        try:
            import io

            from PIL import Image  # type: ignore
            torch = ctx['torch']
            img = ctx['preprocess'](Image.open(io.BytesIO(image_bytes)).convert('RGB')).unsqueeze(0)
            with torch.no_grad():
                feat = ctx['model'].encode_image(img)
                feat = feat / feat.norm(dim=-1, keepdim=True)
            return feat[0].tolist()
        except Exception:
            pass  # bad image → fall through to text
    if ctx:  # pragma: no cover - CLIP text embedding (matches embed_query's space)
        return embed_query(text)
    return _hash_vector(text)


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    return sum(x * y for x, y in zip(a, b))  # both are L2-normalized → dot == cosine
