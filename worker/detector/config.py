"""Detector worker env (PLAN P4 §6.1). No camera config here — the server's CameraJobSpec
drives everything."""
import os

SERVER_API_URL = os.getenv('SERVER_API_URL', 'http://axp-backend:10000/api/v1')
NODE_NAME = os.getenv('NODE_NAME', 'builtin')
JOIN_TOKEN = os.getenv('JOIN_TOKEN')                 # remote node bootstrap (one-time)
NODE_TOKEN = os.getenv('NODE_TOKEN')                 # pre-shared scoped token (skips join)
GPU_ENABLED = os.getenv('GPU_ENABLED', 'false').lower() == 'true'
FORCE_BACKEND = os.getenv('FORCE_BACKEND')           # 'fake' → skip torch/ultralytics
HEARTBEAT_INTERVAL_S = int(os.getenv('HEARTBEAT_INTERVAL_S', '5'))
REPORT_INTERVAL_S = float(os.getenv('REPORT_INTERVAL_S', '1.0'))
ASSIGN_POLL_S = float(os.getenv('ASSIGN_POLL_S', '5'))
DETECTOR_BIND = os.getenv('DETECTOR_BIND', '0.0.0.0:8099')
