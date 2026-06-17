"""Face matching (PLAN P7 A8). Brute-force cosine of an observed embedding against every
enabled identity's reference embeddings (MySQL has no native vector index — plan §152 picks
brute-force for the MVP; a FAISS/sqlite-vss sidecar is the scale path). Only vectors sharing
the observation's `backend`+`dim` are comparable. Returns the best (identity, score 0–100).
"""
from server.model.face_identity import FaceIdentity
from server.service.semantic_embed import cosine

MATCH_THRESHOLD = 0.55          # cosine ≥ this → a match (tune per embedder)


def match(vector: list[float], backend: str):
    """Best (FaceIdentity, score_pct) over enabled identities, or (None, 0) if none clear
    the threshold. `score_pct` is cosine×100 clamped to 0–100."""
    if not vector:
        return None, 0
    dim = len(vector)
    best_identity, best_score = None, 0.0
    for ident in FaceIdentity.list_enabled_with_embeddings():
        if ident.backend != backend or ident.dim != dim:
            continue
        for ref in (ident.embeddings or []):
            if len(ref) != dim:
                continue
            score = cosine(vector, ref)
            if score > best_score:
                best_identity, best_score = ident, score
    if best_identity is None or best_score < MATCH_THRESHOLD:
        return None, 0
    return best_identity, max(0, min(100, int(best_score * 100)))
