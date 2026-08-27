"""Filesystem helpers that need Windows-aware semantics."""
import os
import time


def atomic_replace(src: str, dst: str, attempts: int = 5, delay: float = 0.05):
    """os.replace with retry. On POSIX rename-over is always atomic; on Windows it
    fails with WinError 5/32 while a reader holds the destination open (e.g. a
    concurrent request streaming the same cached thumbnail/segment). Retries ride
    out those short reader windows; the final attempt propagates the error."""
    for i in range(attempts):
        try:
            os.replace(src, dst)
            return
        except (PermissionError, OSError):
            if i == attempts - 1:
                raise
            time.sleep(delay * (i + 1))
