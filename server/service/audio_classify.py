"""Pluggable audio classifier (PLAN P6 A4).

A real model (PANNs / YAMNet) is the target, but torch/torchaudio are not in the base
image (they live in the detector). So the classifier is pluggable — exactly like the A1
embedder:

- `panns` — lazy-loaded if `panns_inference`+torch import (AudioSet tags → our label set).
            Activates with ZERO code change once the dep ships in the detector image.
- `stub`  — dependency-free fallback that runs everywhere NOW: cheap time-domain features
            (RMS energy + zero-crossing rate + peak) → a coarse label + score. Not a real
            acoustic model, but enough to ship + unit-test the whole pipeline end to end.

`classify(samples, sample_rate)` takes mono PCM floats in [-1, 1] and returns a ranked list
of `{'label': str, 'score': int 0–100}`. `active_backend()` reports which is live.
"""
import math

LABELS = ['glass_break', 'scream', 'alarm', 'gunshot', 'dog_bark', 'speech', 'loud_noise', 'ambient']

_panns = None  # None=untried, False=unavailable, object=loaded


def active_backend() -> str:
    return 'panns' if _try_panns() else 'stub'


def classify(samples, sample_rate: int = 16000) -> list[dict]:
    """Classify one window of mono audio. Returns ranked [{label, score}] (score 0–100)."""
    if not samples:
        return [{'label': 'ambient', 'score': 0}]
    ctx = _try_panns()
    if ctx is not None:
        return _classify_panns(ctx, samples, sample_rate)  # pragma: no cover
    return _classify_stub(samples, sample_rate)


# ── time-domain features (pure Python, no numpy) ─────────────────────────────
def _features(samples) -> tuple[float, float, float]:
    n = len(samples)
    sq = 0.0
    peak = 0.0
    crossings = 0
    prev = samples[0]
    for s in samples:
        sq += s * s
        a = s if s >= 0 else -s
        if a > peak:
            peak = a
        if (s >= 0) != (prev >= 0):
            crossings += 1
        prev = s
    rms = math.sqrt(sq / n)
    zcr = crossings / n                      # 0..1 — proxy for spectral brightness
    return rms, peak, zcr


def _classify_stub(samples, sample_rate: int) -> list[dict]:
    rms, peak, zcr = _features(samples)
    # loudness → score (rms in [0,1] for normalized audio; ~0.5 is already very loud)
    score = max(0, min(100, int(rms * 220)))
    if peak >= 0.92 and zcr >= 0.22:
        label = 'glass_break'                # loud + bright/high-freq transient
    elif peak >= 0.92 and zcr < 0.08:
        label = 'gunshot'                    # loud + impulsive, low crossings
    elif rms >= 0.30 and zcr < 0.12:
        label = 'alarm'                      # sustained tonal energy
    elif rms >= 0.30 and zcr >= 0.22:
        label = 'scream'                     # sustained + bright
    elif rms >= 0.12:
        label = 'speech' if zcr >= 0.08 else 'loud_noise'
    else:
        label = 'ambient'
    return [{'label': label, 'score': score}]


# ── PANNs (real model; only where the dep is installed) ──────────────────────
def _try_panns():
    global _panns
    if _panns is False:
        return None
    if _panns is None:
        try:  # pragma: no cover - exercised only where panns_inference+torch are installed
            import numpy  # type: ignore  # noqa: F401
            from panns_inference import AudioTagging  # type: ignore

            _panns = {'tagger': AudioTagging(checkpoint_path=None, device='cpu')}
        except Exception:
            _panns = False
            return None
    return _panns


def _classify_panns(ctx, samples, sample_rate):  # pragma: no cover
    import numpy as np

    audio = np.array(samples, dtype=np.float32)[None, :]
    clipwise, _ = ctx['tagger'].inference(audio)
    # AudioSet → our coarse labels (crude mapping; refine with the real tag index)
    from panns_inference.config import labels as as_labels  # type: ignore
    top = int(clipwise[0].argmax())
    raw = as_labels[top].lower()
    score = int(float(clipwise[0][top]) * 100)
    mapping = (('glass', 'glass_break'), ('scream', 'scream'), ('shout', 'scream'),
               ('alarm', 'alarm'), ('siren', 'alarm'), ('gunshot', 'gunshot'), ('gun', 'gunshot'),
               ('bark', 'dog_bark'), ('dog', 'dog_bark'), ('speech', 'speech'))
    label = next((our for key, our in mapping if key in raw), 'loud_noise' if score >= 30 else 'ambient')
    return [{'label': label, 'score': max(0, min(100, score))}]
