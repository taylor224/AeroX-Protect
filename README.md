# AeroXProtect (axp)

Open-source, self-hosted **NVR (Network Video Recorder)** — camera onboarding, continuous
and event recording, AI object/face/plate detection, automation, and remote viewing in a
single Docker stack. Product name **AeroXProtect**, code namespace **axp**.

> Design tokens in [`DESIGN.md`](DESIGN.md).

## Features

### Cameras & live view
- **Multi-vendor onboarding** — ONVIF, Hikvision (ISAPI), and Hanwha (SUNAPI) drivers with
  capability probing and WS-Discovery auto-detection on the LAN.
- **Encrypted credentials** — camera passwords sealed with a Fernet key, never returned to clients.
- **go2rtc media hub** — every camera is re-streamed once; the UI consumes WebRTC (low latency)
  with automatic fallback to fMP4/MSE.
- **Live grid** with drag-and-drop layout, PTZ control, two-way audio (talk-back), fisheye
  dewarp (WebGL), and multi-page dashboards with timed page rotation.

### Recording & storage
- **Segment-based recorder** (`axp-recorder`) writing rolling MP4 segments per camera.
- **Multi-disk pool** with disk discovery, free-space watchdog, retention/rotation, and
  disk-health / RAID monitoring.
- **Timeline playback** — gap-aware segment-chained MP4 with range scrubbing.
- **Clip export** — copy or transcode, watermarking, and AES password-protected archives.
- **Smart / scheduled recording** — per-camera and global policies × weekly schedule,
  event-triggered clips cut from the cache buffer (no re-encode), dual-record (sub-stream),
  edge-record SD gap-fill, and archiving to S3 / SMB / local.

### Events & AI
- **Vendor event normalization** — ONVIF PullPoint, Hikvision alertStream, Hanwha SUNAPI →
  a unified pipeline (state machine, dedup, cooldown, min-score).
- **Object detection** — pluggable YOLO detector worker (CUDA / CPU / fake fallback) with
  distributed inference nodes (join/heartbeat/assignments, capacity bin-packing, failover).
- **Smart search** — semantic CLIP search, object/track grouping, playback bbox overlay,
  detection zones, people counting, loitering, animal / audio classification, and smoke-fire.
- **LPR & face** — license-plate reads with watchlists, and a consent-based face identity
  registry with cosine matching and erasure support.

### Automation, notifications & integrations
- **Rule engine** — event / object / schedule / system / webhook triggers → conditions
  (AND/OR correlation) → actions: HMAC-signed webhooks (SSRF-guarded), camera enable/disable,
  speaker/IO, SMTP email, VAPID web-push, and Twilio SMS.
- **Monitors / kiosk** — one-time pairing → scoped monitor JWT → unattended wall display.
- **Notifications** — per-user subscriptions with priority, quiet-hours, and mute.
- **External API** — opaque scoped tokens, events/state, webhook subscriptions, and SSE for
  Home Assistant and other consumers.
- **Maps** — Leaflet with Google Maps Tiles support for camera placement.

### Remote, federation & access control
- **Remote portal** — ephemeral coturn-style TURN HMAC credentials feeding live/talk WebRTC
  from outside the LAN.
- **Multi-NVR federation** — a hub aggregates member NVRs' cameras and events via their
  external API, with sync cache and live event fan-out.
- **Access control** — door/credential management with relock handling and security alerts.

### Security
- JWT auth (`aud` ∈ web / monitor / node / api / share, `typ` ∈ access / refresh) with
  Argon2 password hashing, RBAC permissions, and login brute-force lockout.
- SSRF guards on outbound webhooks and camera probing (blocks loopback / link-local /
  cloud-metadata `169.254.169.254`).
- **Fail-closed in production** — refuses to boot if `SECRET_KEY` / `JWT_SECRET` /
  `CREDENTIAL_ENC_KEY` are left at insecure defaults.

## UI tour

Screenshots taken from a running instance (Korean locale; every label is i18n-ed, with
English included).

### Login

JWT session login. The first admin account is bootstrapped from `BOOTSTRAP_ADMIN_*` env.

![Login](docs/screenshots/login.png)

### Live

The home page: a multi-camera live wall backed by go2rtc (MSE-first with WebRTC/fMP4
fallback, automatic H.265→H.264 transcode). Grid layouts are saved as dashboards with
multi-page rotation; tiles support enlarge-in-place, per-tile HD/SD stream selection, PTZ,
talk-back, and fisheye dewarp.

![Live](docs/screenshots/live.png)

### Events & playback

Recording browser merged with the event feed: pick a camera, get a gap-aware timeline with
event markers, filterable by event type (motion, line-cross, intrusion, tamper, object) and
date range. Playback is segment-chained MP4 over hls.js with on-demand transcode; bookmarks,
manual recording, and clip export live here too.

![Events](docs/screenshots/events.png)

### Cameras

Camera inventory and onboarding — ONVIF / Hikvision (ISAPI) / Hanwha (SUNAPI) drivers,
WS-Discovery LAN scan, batch add, per-camera streams, privacy masks, AI settings, firmware
info, and encrypted credential storage.

![Cameras](docs/screenshots/cameras.png)

### Storage

Recording disk pool: discovered disks can be added to the pool, usage and health are
monitored (S.M.A.R.T./RAID guide included), and per-camera retention policies control
rotation.

![Storage](docs/screenshots/storage.png)

### Archive

Long-term archiving of recordings to local / S3 / SMB targets with per-job tracking.

![Archive](docs/screenshots/archive.png)

### Maps

Camera placement on a geographic map (Leaflet — OpenStreetMap by default, Google Map Tiles
optional). Multiple named maps with camera markers that deep-link to live view.

![Maps](docs/screenshots/maps.png)

### Monitors (kiosk)

Unattended wall displays: pair a monitor once with a code, and it gets a scoped token that
can only render its assigned dashboard (`/monitor`).

![Monitors](docs/screenshots/monitors.png)

### Automation — visual flows

n8n-style flow list with per-flow enable toggles and run history. Flows replace a classic
rule engine: trigger → condition → action graphs.

![Automation](docs/screenshots/automation.png)

The editor is a node canvas (@xyflow/react + elk auto-layout): trigger sources, if/else
conditions, delay, and action nodes (push, email, SMS, webhook, record, camera on/off,
speaker, IO) wired through ok/err and true/false branches, with `{{trigger.*}} / {{nodes.*}}`
templating and run replay overlaid on the graph.

![Flow editor](docs/screenshots/flow-editor.png)

### AI

Per-camera AI toolbox: object search over detections, detection zone editor, object
triggers, counting/loitering lines, audio classification, global detector settings, and
distributed inference node management.

![AI](docs/screenshots/ai.png)

### Smart search

Free-text semantic search over recorded detections (CLIP embeddings when a model is
available, text fallback otherwise), with index refresh.

![Search](docs/screenshots/search.png)

### LPR

License plate reads per camera with search, plus a plate watchlist (block/allow labels)
that raises events on match.

![LPR](docs/screenshots/lpr.png)

### Faces

Consent-based face identity registry: recent face detections, enrolled people management,
cosine matching, and one-click erasure of a person's embeddings.

![Faces](docs/screenshots/faces.png)

### Access control

Doors and credentials with an access log (granted/denied and reason), door relock handling,
and security alerts.

![Access control](docs/screenshots/access.png)

### Users

User management with roles and RBAC permissions, account state, and last-login audit.

![Users](docs/screenshots/users.png)

### Settings

System settings: timezone, default UI language, external share URL, WebRTC LAN IP, map
provider, SMS (Twilio), remote-portal TURN, feature flags, and more.

![Settings](docs/screenshots/settings.png)

### Federation (flag-gated)

A hub NVR can aggregate cameras and events from member NVRs over their external API
(`/federation`, off by default behind the `federation` feature flag).

## Stack

| Layer | Tech |
|---|---|
| Backend | Flask 3 · SQLAlchemy 2 · PyMySQL · uWSGI |
| Async / workers | Celery · Redis (broker + denylist) |
| Media | go2rtc (re-stream, WebRTC, RTSP) · ffmpeg |
| Metadata DB | MySQL 8 |
| AI | YOLO (CUDA/CPU) · CLIP · ByteTrack |
| Frontend | React 18 · Vite 7 · TypeScript · Tailwind · shadcn |
| Auth / crypto | JWT (PyJWT) · Argon2 · Fernet (cryptography) |

## Services (`docker compose up`)

`axp-mysql · axp-redis · axp-go2rtc · axp-backend · axp-worker · axp-detector · axp-frontend`

## Quick start (development)

```bash
cp .env.example .env          # then fill in real secrets (see notes below)
docker compose up --build     # services come up healthy
# backend:  http://localhost:10000/api/v1/healthz
# frontend: http://localhost:3000
```

The first admin is created from `BOOTSTRAP_ADMIN_*` env on `seed-admin` (run automatically by
the backend entrypoint when the users table is empty).

Generate the camera-credential encryption key for `.env`:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

## Backend dev (without Docker)

```bash
poetry install
poetry run migrate         # create schema `axp` + all tables
poetry run seed            # seed roles / permissions / settings
poetry run seed-admin      # create first admin from BOOTSTRAP_ADMIN_* env
python -m server           # dev server on :10000
poetry run pytest          # tests
```

## Notes

- Recordings live under `/mnt/axp/disk*` (dev: `./media/disk*`). Register a disk in the
  Storage page, enable recording on a camera, then scrub the Playback timeline.
- **No real cameras?** Add a synthetic go2rtc stream and watch a tile light up — set a
  `cam_synthetic_sub` `exec:ffmpeg ... testsrc ... -f rtsp {output}` stream in
  `go2rtc/go2rtc.yaml`.

## License

AGPL-3.0-or-later.
