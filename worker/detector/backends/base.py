"""Inference backend abstraction (PLAN P4 §5.4). One `Detector` interface, pluggable
CUDA/CPU/fake implementations selected by `make_detector`. Heavy deps (torch/ultralytics)
are imported lazily inside the concrete backends so this module imports anywhere."""
from dataclasses import dataclass
from typing import Protocol


@dataclass
class Detection:
    bbox_xyxy: tuple          # (x1, y1, x2, y2) in pixels (pipeline-internal)
    confidence: float         # 0–1
    class_id: int
    label: str


class Detector(Protocol):
    name: str

    def warmup(self) -> None: ...
    def infer(self, frame, *, imgsz: int, conf: float, classes: list[int] | None) -> list[Detection]: ...
    def benchmark(self, sample) -> dict: ...
    @property
    def healthy(self) -> bool: ...
    @property
    def device(self) -> str: ...
    def close(self) -> None: ...
