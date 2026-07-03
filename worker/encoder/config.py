"""Encoder worker env. No camera config here — the server's EncodeJobSpec drives
everything (pull/publish URLs + validated encode profile)."""
import os

SERVER_API_URL = os.getenv('SERVER_API_URL', 'http://axp-backend:10000/api/v1')
NODE_NAME = os.getenv('NODE_NAME', 'encoder')
JOIN_TOKEN = os.getenv('JOIN_TOKEN')                 # remote node bootstrap (one-time)
NODE_TOKEN = os.getenv('NODE_TOKEN')                 # pre-shared scoped token (skips join)
HEARTBEAT_INTERVAL_S = int(os.getenv('HEARTBEAT_INTERVAL_S', '5'))
ENCODER_BIND = os.getenv('ENCODER_BIND', '0.0.0.0:8098')
HWACCEL = (os.getenv('HWACCEL', 'none') or 'none').lower()   # none/nvenc/qsv/vaapi/videotoolbox
MAX_SESSIONS = int(os.getenv('MAX_SESSIONS', '4'))           # concurrent live encodes
# URL the backend can reach this node on (playback POST /transcode). Falls back to the
# join source IP server-side when unset.
ADVERTISE_URL = os.getenv('ADVERTISE_URL')
# Shared secret for POST /transcode. Unset = LAN-trust (private/loopback callers only).
ENCODE_CALLBACK_SECRET = os.getenv('ENCODE_CALLBACK_SECRET')
FFMPEG_BIN = os.getenv('FFMPEG_BIN', 'ffmpeg')
