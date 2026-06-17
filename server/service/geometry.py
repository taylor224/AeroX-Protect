"""Polygon math for detection-zone attribution (PLAN P4 §6.5). Pure functions on
normalized 0–1 coordinates — shared by detection_ingest (server-side zone_id attribution)
and mirrored in the worker's zones.py."""


def bottom_center(bbox: list[float]) -> tuple[float, float]:
    """[x1,y1,x2,y2] → ground-contact point (mid-x, bottom-y). Standard for ROI membership."""
    x1, y1, x2, y2 = bbox
    return (x1 + x2) / 2.0, max(y1, y2)


def point_in_polygon(x: float, y: float, polygon: list[list[float]]) -> bool:
    """Ray-casting point-in-polygon. polygon = [[x,y],...] (≥3 points)."""
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


def polygon_area(polygon: list[list[float]]) -> float:
    """Shoelace area (normalized units) — tie-break for zone attribution (smallest wins)."""
    if not polygon or len(polygon) < 3:
        return 0.0
    s = 0.0
    n = len(polygon)
    for i in range(n):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0
