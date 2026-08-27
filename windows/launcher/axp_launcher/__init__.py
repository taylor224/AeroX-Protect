"""AeroXProtect native Windows launcher.

Runs as a Windows service (via WinSW) and supervises the whole stack: MariaDB,
Redis, go2rtc, Caddy, the Flask backend (waitress), Celery workers, the recorder,
the encoder node and (optionally) the AI detector. Also owns the self-update
state machine driven from the web UI.

STDLIB ONLY — this package must keep running while the application's
versions\\<v>\\site-packages tree is being swapped out from under it, and a broken
app update must never be able to brick the service that repairs it.
"""
LAUNCHER_VERSION = '1.0.0'
