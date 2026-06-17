"""Zone include/ignore filtering on the worker (PLAN P4 §6.5). Zones arrive in the
CameraJobSpec as normalized 0–1 polygons; detection bbox is pixels → normalize bottom-center
to test membership. include (∪) gates, ignore (∖) drops. Mirrors server geometry.py."""


def point_in_polygon(x: float, y: float, polygon) -> bool:
    if not polygon or len(polygon) < 3:
        return False
    inside = False
    n = len(polygon)
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i][0], polygon[i][1]
        xj, yj = polygon[j][0], polygon[j][1]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi):
            inside = not inside
        j = i
    return inside


def bottom_center(bbox) -> tuple[float, float]:
    x1, y1, x2, y2 = bbox
    return (x1 + x2) / 2.0, max(y1, y2)


class ZoneFilter:
    def __init__(self, zones: dict | None):
        zones = zones or {}
        self.include = zones.get('include') or []
        self.ignore = zones.get('ignore') or []

    def keep(self, det, frame_w: int, frame_h: int) -> bool:
        bx, by = bottom_center(det.bbox_xyxy)
        nx, ny = bx / max(1, frame_w), by / max(1, frame_h)
        if self.include and not any(point_in_polygon(nx, ny, p) for p in self.include):
            return False
        if any(point_in_polygon(nx, ny, p) for p in self.ignore):
            return False
        return True

    def filter(self, detections, frame_w: int, frame_h: int) -> list:
        return [d for d in detections if self.keep(d, frame_w, frame_h)]
