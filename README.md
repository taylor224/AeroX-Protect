# AeroXProtect (axp)

Open-source NVR (Network Video Recorder). Product name **AeroXProtect**, code namespace **axp**.

> Planning lives in [`PLAN.md`](PLAN.md) (master + §12 SSOT) and [`plan/`](plan/) (per-phase).
> Design tokens in [`DESIGN.md`](DESIGN.md). **Read PLAN.md §12 before changing cross-phase contracts.**

## Stack

Flask 3 + SQLAlchemy 2 + PyMySQL + uWSGI · Celery + Redis · go2rtc media hub ·
MySQL 8 (metadata) · React 18 + Vite 7 + TypeScript + Tailwind + shadcn · JWT auth.

## Services (`docker compose up`)

`axp-mysql · axp-redis · axp-go2rtc · axp-backend · axp-worker · axp-detector · axp-frontend`

## Quick start (development)

```bash
cp .env.example .env          # then edit secrets
docker compose up --build     # 7 services come up healthy
# backend:  http://localhost:10000/api/v1/healthz
# frontend: http://localhost:3000
```

First admin is created from `BOOTSTRAP_ADMIN_*` env on `seed-admin`
(run automatically by the backend entrypoint when the users table is empty).

## Backend dev (without Docker)

```bash
poetry install
poetry run migrate         # create schema `axp` + all tables
poetry run seed            # seed roles / permissions / settings
poetry run seed-admin      # create first admin from BOOTSTRAP_ADMIN_* env
python -m server           # dev server on :10000
poetry run pytest          # tests
```

## Phase status

- **P0 (Scaffold)** ✅ — repo/Docker/auth+RBAC/core models/design shell. [`plan/phase-0.md`](plan/phase-0.md)
- **P1 (Camera onboarding + live view)** ✅ — ONVIF/Hikvision-ISAPI/Hanwha-SUNAPI drivers, capability probe + WS-Discovery, encrypted credentials, go2rtc re-streaming, WebRTC→fMP4 live grid (dnd-kit), PTZ, dashboards + ACL. [`plan/phase-1.md`](plan/phase-1.md)
- **P2 (Recording + storage)** ✅ — segment-based ffmpeg recorder (`axp-recorder`), multi-disk pool + free-space watchdog + disk discovery, retention/rotation, timeline playback (segment-chained MP4 range), clip export (copy/transcode). [`plan/phase-2.md`](plan/phase-2.md)
- **P3 (Events + smart/schedule recording)** ✅ — vendor event normalization (ONVIF PullPoint / Hikvision ISAPI alertStream / Hanwha SUNAPI), pipeline (state machine, dedup, cooldown, min-score) → per-camera/global policies × weekly schedule (KST), event clips from the P2 cache buffer (no re-encode, coalesced), motion overlay, event timeline, schedule paint editor, timelapse. [`plan/phase-3.md`](plan/phase-3.md)
- **P4 (AI object detection + search)** ✅ — pluggable YOLO detector worker (CUDA/CPU/fake fallback), distributed inference nodes (join/heartbeat/assignments with scoped tokens, capacity bin-packing + failover rebalance), detection ingest (track down-sampling, zone attribution, segment linking), smart object search (clip/track grouping) + playback bbox overlay, detection zones, object triggers → P3 `events(type=object)` → recording. [`plan/phase-4.md`](plan/phase-4.md)
- **P5 (automation + monitors + notifications)** ✅ — rule engine (event/object/schedule/manual triggers → conditions → actions) consuming the P3 event outbox, action drivers (HMAC-signed webhooks with SSRF guard, speaker/IO, SMTP email, VAPID web-push), 60-second one-time monitor pairing → audience=monitor scoped JWT → kiosk display, per-user notification subscriptions (priority/quiet-hours/mute), and an external API (opaque scoped tokens, events/state, webhook subscriptions, SSE) for Home Assistant. [`plan/phase-5.md`](plan/phase-5.md)
- **P6 (advanced AI / SMS / multi-NVR)** — next.

Recording uses HDD bind-mounts under `/mnt/axp/disk*` (dev: `./media/disk*`). Register a disk in the Storage page, toggle continuous recording on a camera, then scrub the Playback timeline.

> No real cameras? Add a synthetic go2rtc stream and watch a tile light up:
> set a `cam_synthetic_sub` `exec:ffmpeg ... testsrc ... -f rtsp {output}` stream in `go2rtc/go2rtc.yaml`.
