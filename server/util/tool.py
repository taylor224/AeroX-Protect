def safe_int(value, default=0):
    """Safe int conversion. Empty / None / non-numeric -> default."""
    if value is None or value == '':
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        try:
            return int(float(value))  # '1.0' style
        except (ValueError, TypeError):
            return default


def safe_float(value, default=0.0):
    """Safe float conversion. Empty / None / non-numeric -> default."""
    if value is None or value == '':
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default
