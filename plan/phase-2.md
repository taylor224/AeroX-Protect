# Phase 2 — 녹화 + 스토리지 엔진

> 마스터 플랜 [`../PLAN.md`](../PLAN.md) 4절(핵심 설계 원칙)·디자인 [`../DESIGN.md`](../DESIGN.md)을 먼저 읽고 시작한다.
> 본 Phase는 P1(go2rtc 재스트림·`cameras`·`streams`)에 의존하며, P3(이벤트/스케줄 녹화)·P4(AI 메타)·P6(이중녹화/암호화/공유링크)가 본 Phase의 세그먼트·캐시버퍼·스토리지 풀을 직접 소비한다.
> 네임스페이스 `axp`. 백엔드는 ams-front MVC(View→Controller→Service/Driver→Model→Task) 패턴을 그대로 TS/Python에 이식한다.

---

## 1. 목표 & 성공 기준(DoD)

**목표**: go2rtc 재스트림을 입력으로, 카메라별 ffmpeg copy-codec 세그먼트를 다중 HDD 풀에 롤링 기록하고, 세그먼트를 MySQL에 인덱싱하여 타임라인 재생·클립 다운로드를 제공한다. 보존/로테이션·여유공간 워치독·신규 디스크 감지를 갖춘 운영 가능한 스토리지 엔진을 완성한다.

**DoD (이 Phase 단독으로 시연 가능해야 함)**:
1. 카메라에 대해 **상시(continuous)** 녹화를 켜면 `recorder_supervisor`가 ffmpeg를 띄워 ~10s 세그먼트를 캐시 디스크에 기록하고, `segments` 테이블에 디스크·경로·start/end_ts·size가 인덱싱된다.
2. ffmpeg 프로세스가 죽거나 스트림이 끊겨도 supervisor가 백오프로 자동 재시작하고, 헬스 상태가 API로 노출된다.
3. **수동(manual)** 녹화: 사용자가 버튼으로 시작/종료하면 해당 구간이 `recordings(reason=manual)`로 보호 마킹되어 로테이션 대상에서 제외된다.
4. **다중 HDD 풀**: `disks`에 마운트/용량/예약여유/역할(system|cache|record)을 등록하고, 쓰기는 정책(least-used/per-camera/RR)으로 분산, 세그먼트가 여러 디스크에 샤딩되어 기록된다.
5. **여유공간 워치독**: 어떤 디스크든 `reserved_free` 침범이 임박하면 즉시 로테이션을 트리거하고, system 디스크 보호 공간은 항상 확보된다.
6. **신규 디스크 감지**: 백그라운드 스캔이 미등록 마운트를 발견하면 UI에 "녹화 풀에 추가?" 프롬프트가 뜨고, 역할을 지정해 등록할 수 있다.
7. **보존/로테이션**: 카메라별 보존(일수 AND 용량)·용량 초과 정책(delete_oldest|stop_recording|warn_only)을 설정하고, Celery 주기 작업이 정책대로 오래된 세그먼트를 삭제한다. 설정 용량이 현재 풀 용량을 초과하면 경고가 표시된다.
8. **타임라인 재생**: 세그먼트 인덱스 기반으로 특정 카메라·시각으로 seek/스크럽하여 연속 재생(HLS 또는 MP4 range)되며, 빈 구간(녹화 없음)이 타임라인에 시각적으로 표시된다.
9. **클립 내보내기**: 임의 [start, end] 구간을 원본 copy(빠름) 또는 온디맨드 H.264 재인코딩으로 내보내 다운로드한다. 작업은 Celery 큐로 처리되고 진행률이 표시된다.
10. 전/후 버퍼 메커니즘(직전 N초 회수 + 이후 M초 보존)이 서비스로 구현되어 P3가 호출만 하면 동작한다(본 Phase에서는 수동 트리거로 검증).
11. 모든 API에 인가(`@login_required` + `@permission_required`)가 적용되고, 비인가 카메라/디스크 정보가 응답에 노출되지 않는다. unit/integration/e2e 테스트 통과.

---

## 2. 범위 (In-scope / Out-of-scope)

### In-scope
- 세그먼트 레코더(`recorder_supervisor`) + per-camera ffmpeg(copy-codec) + 헬스/재시작.
- 녹화 모드: **continuous**, **manual**.
- 캐시 디스크 롤링 = 전버퍼. 전/후 버퍼 회수/보존 **메커니즘**(P3가 사용).
- 스토리지 풀: `disks` 등록·역할·여유공간 워치독·다중 경로·부하분산(least-used/per-camera/RR)·세그먼트 DB 인덱싱·디렉터리 샤딩.
- 신규 디스크 감지(백그라운드 스캔 → UI 프롬프트).
- 보존/로테이션: 카메라별(일수+용량)·용량초과 정책·Celery 주기 작업·설정 초과 경고.
- 타임라인 재생: 세그먼트 스티칭·seek·스크럽, 재생 API, HLS/MP4 제공.
- 클립 내보내기/다운로드: 원본 copy + 온디맨드 H.264 재인코딩, 작업 큐.
- 프론트: Timeline, Player, StorageManager, RetentionSettings, ExportDialog.

### Out-of-scope (다른 Phase)
- 스케줄/이벤트/모션 녹화 트리거 → **P3** (본 Phase의 전후버퍼·세그먼트 API만 제공).
- AI detection 메타 부착·객체 기반 타임라인 마커 → **P4**.
- 규칙엔진 연동 녹화·알림 → **P5**.
- 이중녹화(failover)·엣지녹화·세그먼트 암호화·워터마크·외부 공유링크 → **P6** (단, `recordings.retention_class`, `disks.role`, 샤딩 경로 등 확장 포인트는 본 Phase에서 미리 둔다).
- 타임랩스·북마크·썸네일 스프라이트(타임라인 호버 프리뷰의 고급형) → **P3** (본 Phase는 세그먼트 키프레임 단건 썸네일까지만).
- 라이브뷰/PTZ/카메라 온보딩 → **P1** (소비만).

---

## 3. 선행 의존성

| 의존 | 출처 | 본 Phase에서의 사용 |
|---|---|---|
| `cameras` 테이블(id, name, enabled, capabilities) | P1 | 녹화 대상·권한 스코프 |
| `streams` 테이블(camera_id, role main/sub, codec, go2rtc_name) | P1 | ffmpeg 입력 소스 결정(녹화=main, 썸네일=가능시 sub) |
| go2rtc 재스트림 엔드포인트 | P1 | ffmpeg `-i rtsp://axp-go2rtc:8554/{go2rtc_name}` |
| `users`/`roles`/`permissions`(JSON 권한맵) + JWT/`@permission_required` | P0 | API 인가 |
| `ResponseBuilder`, `BaseDB`/`KST`/Snowflake ID, soft-delete/감사 컬럼 | P0 | 응답/모델 컨벤션 |
| Celery + Redis(broker), `@shared_task`/`@celery_use_db()`, `celeryconfig.beat_schedule` | P0 | 주기/큐 작업 |
| `settings` 테이블 | P0 | 전역 기본값(기본 세그먼트 길이, 캐시 보존시간 등) |

**신규 권한 키**(P0 권한맵에 추가): `recordings:read`, `recordings:control`(상시/수동 토글), `playback:read`, `clips:export`, `storage:read`, `storage:manage`, `retention:manage`. 카메라 단위 ACL은 P0의 per-camera 권한 구조를 재사용한다.

**환경/인프라 전제**: `axp-backend`·`axp-worker` 컨테이너에 ffmpeg(>=6.0) 설치, HDD들이 호스트에서 `/mnt/axp/disk*`로 마운트되어 컨테이너에 **동일 경로 bind-mount**. `psutil` 의존성 추가. 디스크 스캔용으로 컨테이너에 host `/proc/mounts` 및 `lsblk`(또는 host의 마운트 목록) 접근 가능해야 함(아래 6.7 참조).

---

## 4. 데이터 모델 (테이블·컬럼·타입·인덱스 / 마이그레이션 SQL 스케치)

> 전용 DB이므로 테이블 prefix 없음. 모든 테이블 BIGINT PK(Snowflake), `created_at`/`updated_at`, 주요 테이블 `deleted_at`. 시간은 **UTC 저장(naive UTC)**, 표시 시 KST 변환(녹화 타임스탬프 정확성). `_ts`는 UTC `DATETIME(3)`(밀리초), 길이는 ms 단위.

### 4.1 `disks` — 스토리지 풀 멤버
| 컬럼 | 타입 | 설명 |
|---|---|---|
| id | BIGINT PK | Snowflake |
| name | VARCHAR(100) | 표시명(예: "Record HDD 1") |
| mount_path | VARCHAR(500) UNIQUE | 마운트 경로(`/mnt/axp/disk1`) |
| device | VARCHAR(200) | 블록 디바이스(`/dev/sdb1`), 진단용 |
| fs_uuid | VARCHAR(100) | 파일시스템 UUID(마운트 변동 대비 식별) |
| role | ENUM('system','cache','record') | 역할. cache=전후버퍼 롤링, record=장기보존 |
| enabled | TINYINT(1) default 1 | 쓰기 대상 포함 여부 |
| reserved_free_bytes | BIGINT | 항상 비워둘 예약 공간(워치독 임계) |
| total_bytes | BIGINT | 최근 스캔된 총 용량 |
| free_bytes | BIGINT | 최근 스캔된 여유(워치독·부하분산 판단 캐시) |
| weight | INT default 100 | RR/least-used 가중치(용량 다른 디스크 보정) |
| status | ENUM('online','offline','readonly','error') | 마운트/쓰기 가능 상태 |
| last_seen_at | DATETIME(3) | 마지막 정상 스캔 시각 |
| created_by_id / last_updated_by_id | BIGINT | 감사 |
| created_at / updated_at / deleted_at | DATETIME(3) | |

인덱스: `idx_disks_role_enabled (role, enabled, deleted_at)`, `uq_disks_mount (mount_path)`, `uq_disks_fs_uuid (fs_uuid)`.

### 4.2 `storage_policies` — 카메라별 보존/배치 정책
| 컬럼 | 타입 | 설명 |
|---|---|---|
| id | BIGINT PK | |
| camera_id | BIGINT | NULL=전역 기본 정책(fallback) |
| segment_seconds | INT default 10 | 세그먼트 길이 |
| container | ENUM('fmp4','mpegts') default 'fmp4' | 세그먼트 컨테이너(6.2 근거) |
| record_mode | ENUM('off','continuous') default 'off' | 본 Phase 상시 토글(manual은 별도 트리거) |
| balance_strategy | ENUM('least_used','per_camera','round_robin') default 'least_used' | 쓰기 분산 |
| pinned_disk_id | BIGINT NULL | per_camera 시 고정 디스크(없으면 첫 배치 후 고정) |
| retention_days | INT NULL | 상시 보존 일수(NULL=무제한, 용량만) |
| retention_max_bytes | BIGINT NULL | 카메라별 용량 상한(NULL=풀 비례) |
| over_capacity_policy | ENUM('delete_oldest','stop_recording','warn_only') default 'delete_oldest' | 초과 시 동작 |
| cache_buffer_seconds | INT default 60 | 캐시(전버퍼) 최소 보존 길이 — 이벤트 회수용 |
| event_retention_days | INT NULL | (P3 대비) 이벤트 보존 분리. 본 Phase 미사용·컬럼만 |
| created_by_id / last_updated_by_id / created_at / updated_at / deleted_at | | 감사/타임스탬프 |

인덱스: `uq_policy_camera (camera_id, deleted_at)`(카메라당 1 활성), `idx_policy_mode (record_mode)`.

### 4.3 `segments` — 세그먼트 인덱스(핵심·고빈도 INSERT/조회)
> 한 카메라가 ~10s마다 1행 → 카메라 16대·30일 ≈ 4.1M rows. 조회는 거의 항상 `(camera_id, start_ts 범위)`. **FK 미설정**(성능), 카메라/디스크 참조는 애플리케이션 보장.

| 컬럼 | 타입 | 설명 |
|---|---|---|
| id | BIGINT PK | Snowflake(시간순 ≈ 단조 증가) |
| camera_id | BIGINT NOT NULL | 인덱스 |
| disk_id | BIGINT NOT NULL | 물리 위치 |
| rel_path | VARCHAR(500) NOT NULL | 디스크 루트 기준 상대경로(`{camera}/2026/06/05/14/seg-...mp4`) |
| start_ts | DATETIME(3) NOT NULL | 세그먼트 시작(UTC) |
| end_ts | DATETIME(3) NOT NULL | 세그먼트 끝(UTC) |
| duration_ms | INT NOT NULL | 실제 길이 |
| size_bytes | BIGINT NOT NULL | 파일 크기 |
| container | ENUM('fmp4','mpegts') | |
| video_codec | VARCHAR(20) | 'h264'/'h265' (스트림 메타 복사) |
| has_audio | TINYINT(1) | |
| width / height | SMALLINT | |
| first_keyframe_ms | INT default 0 | 세그먼트 내 첫 키프레임 오프셋(seek 정확도) |
| reason | ENUM('continuous','manual') default 'continuous' | 본 Phase 범위(P3가 event/schedule 추가) |
| storage_tier | ENUM('cache','record') | 현재 위치한 디스크 역할(승격 추적) |
| corrupt | TINYINT(1) default 0 | 무결성 검사 실패 마킹(재생 제외) |
| created_at | DATETIME(3) server_default now(3) | |

인덱스(설계 핵심):
- `idx_seg_cam_start (camera_id, start_ts)` — **타임라인/재생 주조회**(범위 스캔). 커버링 위해 `end_ts` 포함 고려.
- `idx_seg_disk_start (disk_id, start_ts)` — 디스크별 로테이션 스캔(오래된 것부터 삭제).
- `idx_seg_tier_start (storage_tier, start_ts)` — 캐시→record 승격/캐시 롤링.
- `idx_seg_reason (camera_id, reason, start_ts)` — manual 보호 구간 조회.
- soft-delete 없음(삭제 = 파일 삭제 + row DELETE, 보존 정책 단순화). 단 manual 보호는 아래 `recordings`로 마킹.

> **파티셔닝(권장, 대규모)**: `segments`를 `start_ts` 기준 RANGE 파티션(월별)으로 두면 로테이션이 파티션 DROP으로 O(1)에 가깝게 처리 가능. MVP는 단일 테이블 + 인덱스로 시작하고, 14절 결정사항으로 둔다.

### 4.4 `recordings` — 논리 녹화 구간(보호·내보내기 단위)
> 세그먼트는 물리, recordings는 논리(연속 구간/보호 마킹/내보내기 결과). 보존 정책이 manual/event를 보호하는 기준.

| 컬럼 | 타입 | 설명 |
|---|---|---|
| id | BIGINT PK | |
| camera_id | BIGINT NOT NULL | |
| reason | ENUM('continuous','manual','event','schedule') | 본 Phase는 continuous/manual |
| retention_class | ENUM('default','protected','event') default 'default' | protected=로테이션 제외(manual/북마크) |
| start_ts | DATETIME(3) NOT NULL | |
| end_ts | DATETIME(3) NULL | NULL=진행 중(manual 녹화 중) |
| created_by_id | BIGINT NULL | manual 시작자(감사) |
| note | VARCHAR(500) NULL | 메모/사유 |
| created_at / updated_at / deleted_at | DATETIME(3) | |

인덱스: `idx_rec_cam_start (camera_id, start_ts)`, `idx_rec_protect (camera_id, retention_class, start_ts)`(로테이션 시 보호 구간 교차 판정).

### 4.5 `export_jobs` — 클립 내보내기/트랜스코드 작업
| 컬럼 | 타입 | 설명 |
|---|---|---|
| id | BIGINT PK | |
| camera_id | BIGINT NOT NULL | |
| requested_by_id | BIGINT NOT NULL | |
| start_ts / end_ts | DATETIME(3) | 내보낼 구간 |
| mode | ENUM('copy','transcode') | copy=무재인코딩, transcode=H.264 재인코딩 |
| container | ENUM('mp4','mkv') default 'mp4' | |
| transcode_preset | VARCHAR(50) NULL | 예: 'h264_1080p', 'h264_720p' |
| status | ENUM('queued','processing','done','failed','expired') default 'queued' | |
| progress | TINYINT default 0 | 0–100 |
| celery_task_id | VARCHAR(100) NULL | 진행 조회/취소 |
| output_disk_id | BIGINT NULL | 결과 저장 디스크 |
| output_rel_path | VARCHAR(500) NULL | 결과 파일 |
| output_size_bytes | BIGINT NULL | |
| download_token | VARCHAR(100) UNIQUE | 다운로드 인증 토큰 |
| error_message | VARCHAR(1000) NULL | |
| expires_at | DATETIME(3) NULL | 결과 자동 정리 시각(기본 +24h) |
| created_at / updated_at | DATETIME(3) | |

인덱스: `idx_export_status (status, created_at)`, `idx_export_requester (requested_by_id, created_at)`, `uq_export_token (download_token)`, `idx_export_expires (expires_at)`.

### 4.6 `recorder_health` — supervisor 헬스 스냅샷(경량, UPSERT)
> 카메라당 1행. 빈번 갱신이라 별도 테이블(메인 테이블 부하 격리). 영속 가벼우면 Redis로 대체 가능(14절).

| 컬럼 | 타입 | 설명 |
|---|---|---|
| camera_id | BIGINT PK | |
| state | ENUM('stopped','starting','recording','reconnecting','error') | |
| pid | INT NULL | ffmpeg PID |
| last_segment_at | DATETIME(3) NULL | 마지막 세그먼트 기록 시각(stall 판정) |
| restart_count | INT default 0 | |
| last_error | VARCHAR(1000) NULL | |
| updated_at | DATETIME(3) | |

### 4.7 마이그레이션 SQL 스케치 (MySQL 8)
```sql
CREATE TABLE disks (
  id BIGINT PRIMARY KEY,
  name VARCHAR(100) NOT NULL,
  mount_path VARCHAR(500) NOT NULL,
  device VARCHAR(200), fs_uuid VARCHAR(100),
  role ENUM('system','cache','record') NOT NULL DEFAULT 'record',
  enabled TINYINT(1) NOT NULL DEFAULT 1,
  reserved_free_bytes BIGINT NOT NULL DEFAULT 0,
  total_bytes BIGINT DEFAULT 0, free_bytes BIGINT DEFAULT 0,
  weight INT NOT NULL DEFAULT 100,
  status ENUM('online','offline','readonly','error') NOT NULL DEFAULT 'online',
  last_seen_at DATETIME(3),
  created_by_id BIGINT, last_updated_by_id BIGINT,
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  deleted_at DATETIME(3) NULL,
  UNIQUE KEY uq_disks_mount (mount_path),
  UNIQUE KEY uq_disks_fs_uuid (fs_uuid),
  KEY idx_disks_role_enabled (role, enabled, deleted_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE storage_policies (
  id BIGINT PRIMARY KEY,
  camera_id BIGINT NULL,
  segment_seconds INT NOT NULL DEFAULT 10,
  container ENUM('fmp4','mpegts') NOT NULL DEFAULT 'fmp4',
  record_mode ENUM('off','continuous') NOT NULL DEFAULT 'off',
  balance_strategy ENUM('least_used','per_camera','round_robin') NOT NULL DEFAULT 'least_used',
  pinned_disk_id BIGINT NULL,
  retention_days INT NULL,
  retention_max_bytes BIGINT NULL,
  over_capacity_policy ENUM('delete_oldest','stop_recording','warn_only') NOT NULL DEFAULT 'delete_oldest',
  cache_buffer_seconds INT NOT NULL DEFAULT 60,
  event_retention_days INT NULL,
  created_by_id BIGINT, last_updated_by_id BIGINT,
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  deleted_at DATETIME(3) NULL,
  UNIQUE KEY uq_policy_camera (camera_id, deleted_at),
  KEY idx_policy_mode (record_mode)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE segments (
  id BIGINT PRIMARY KEY,
  camera_id BIGINT NOT NULL,
  disk_id BIGINT NOT NULL,
  rel_path VARCHAR(500) NOT NULL,
  start_ts DATETIME(3) NOT NULL,
  end_ts DATETIME(3) NOT NULL,
  duration_ms INT NOT NULL,
  size_bytes BIGINT NOT NULL,
  container ENUM('fmp4','mpegts') NOT NULL DEFAULT 'fmp4',
  video_codec VARCHAR(20), has_audio TINYINT(1) DEFAULT 0,
  width SMALLINT, height SMALLINT,
  first_keyframe_ms INT NOT NULL DEFAULT 0,
  reason ENUM('continuous','manual') NOT NULL DEFAULT 'continuous',
  storage_tier ENUM('cache','record') NOT NULL DEFAULT 'cache',
  corrupt TINYINT(1) NOT NULL DEFAULT 0,
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  KEY idx_seg_cam_start (camera_id, start_ts, end_ts),
  KEY idx_seg_disk_start (disk_id, start_ts),
  KEY idx_seg_tier_start (storage_tier, start_ts),
  KEY idx_seg_reason (camera_id, reason, start_ts)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
-- 대규모 시: ALTER ... PARTITION BY RANGE (TO_DAYS(start_ts)) (월별 파티션)

CREATE TABLE recordings (
  id BIGINT PRIMARY KEY,
  camera_id BIGINT NOT NULL,
  reason ENUM('continuous','manual','event','schedule') NOT NULL,
  retention_class ENUM('default','protected','event') NOT NULL DEFAULT 'default',
  start_ts DATETIME(3) NOT NULL,
  end_ts DATETIME(3) NULL,
  created_by_id BIGINT NULL, note VARCHAR(500) NULL,
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  deleted_at DATETIME(3) NULL,
  KEY idx_rec_cam_start (camera_id, start_ts),
  KEY idx_rec_protect (camera_id, retention_class, start_ts)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE export_jobs (
  id BIGINT PRIMARY KEY,
  camera_id BIGINT NOT NULL,
  requested_by_id BIGINT NOT NULL,
  start_ts DATETIME(3) NOT NULL, end_ts DATETIME(3) NOT NULL,
  mode ENUM('copy','transcode') NOT NULL DEFAULT 'copy',
  container ENUM('mp4','mkv') NOT NULL DEFAULT 'mp4',
  transcode_preset VARCHAR(50) NULL,
  status ENUM('queued','processing','done','failed','expired') NOT NULL DEFAULT 'queued',
  progress TINYINT NOT NULL DEFAULT 0,
  celery_task_id VARCHAR(100) NULL,
  output_disk_id BIGINT NULL, output_rel_path VARCHAR(500) NULL,
  output_size_bytes BIGINT NULL,
  download_token VARCHAR(100) NOT NULL,
  error_message VARCHAR(1000) NULL,
  expires_at DATETIME(3) NULL,
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  UNIQUE KEY uq_export_token (download_token),
  KEY idx_export_status (status, created_at),
  KEY idx_export_requester (requested_by_id, created_at),
  KEY idx_export_expires (expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE recorder_health (
  camera_id BIGINT PRIMARY KEY,
  state ENUM('stopped','starting','recording','reconnecting','error') NOT NULL DEFAULT 'stopped',
  pid INT NULL,
  last_segment_at DATETIME(3) NULL,
  restart_count INT NOT NULL DEFAULT 0,
  last_error VARCHAR(1000) NULL,
  updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

---

## 5. 백엔드 설계 (API 표 / controller·service·driver·task 구성)

### 5.1 디렉터리 구성 (PLAN 6절 구조 준수)
```
server/
├─ view/api/
│  ├─ recording.py      # 상시/수동 토글, 헬스
│  ├─ playback.py       # 타임라인·세그먼트 인덱스·재생(HLS/MP4 range)
│  ├─ export.py         # 클립 내보내기/다운로드
│  └─ storage.py        # disks·정책·디스크감지·풀 상태
├─ controller/
│  ├─ recording.py  playback.py  export.py  storage.py  retention.py
├─ model/
│  ├─ disk.py  storage_policy.py  segment.py  recording.py  export_job.py  recorder_health.py
├─ service/
│  ├─ recorder_supervisor.py   # 프로세스 매니저(워커 진입점에서 구동)
│  ├─ segment_indexer.py       # 세그먼트 파일→DB 인덱싱(감시/스캔)
│  ├─ storage_manager.py       # 디스크 선택·부하분산·여유공간 워치독
│  ├─ retention_engine.py      # 보존/로테이션 알고리즘
│  ├─ disk_scanner.py          # 마운트/lsblk/psutil 스캔
│  ├─ playback_planner.py      # 구간→세그먼트 리스트→재생 플랜(스티칭)
│  └─ ffmpeg.py                # ffmpeg 명령행 빌더/실행 래퍼(공용)
├─ driver/
│  └─ go2rtc.py                # (P1 제공) 재스트림 URL 조회
└─ task/list/
   ├─ retention.py     # 주기 로테이션
   ├─ disk_scan.py     # 신규 디스크/용량 스캔
   ├─ segment_sweep.py # 캐시→record 승격, 고아 파일/인덱스 정합
   ├─ transcode.py     # export 작업(copy/transcode)
   └─ thumbnail.py     # 세그먼트 키프레임 썸네일(타임라인 호버)
```
> **recorder_supervisor는 Celery가 아니라 `axp-worker`(recorder) 컨테이너의 장기 실행 프로세스**다(PLAN: `worker/recorder/`). Celery는 단발/주기 작업용. supervisor는 DB의 `storage_policies.record_mode`를 폴링/구독해 ffmpeg 자식 프로세스를 관리한다.

### 5.2 API 표 (모두 `/api/v1` 프리픽스, JWT 필수, 응답 `ResponseBuilder`)

#### 녹화 제어 (`recording.py`)
| Method | Path | 권한 | 요청 | 응답 |
|---|---|---|---|---|
| GET | `/recording/cameras/{camera_id}/status` | recordings:read + 카메라ACL | — | `{record_mode, health:{state,last_segment_at,restart_count}, active_manual:bool}` |
| PUT | `/recording/cameras/{camera_id}/mode` | recordings:control | `{mode:'off'|'continuous'}` | 갱신된 status. supervisor에 reconcile 시그널 |
| POST | `/recording/cameras/{camera_id}/manual/start` | recordings:control | `{note?}` | `{recording_id, start_ts}` (진행중 recordings 생성, reason=manual) |
| POST | `/recording/cameras/{camera_id}/manual/stop` | recordings:control | `{recording_id}` | `{recording_id, end_ts}` (end_ts 확정, retention_class=protected) |
| GET | `/recording/health` | storage:read | — | 전체 카메라 헬스 배열(대시보드) |

#### 재생 (`playback.py`)
| Method | Path | 권한 | 요청 | 응답 |
|---|---|---|---|---|
| GET | `/playback/cameras/{camera_id}/timeline` | playback:read + ACL | `from,to`(UTC), `resolution`(버킷 초, 예 60) | `{ranges:[{start,end}], gaps:[...], events:[](P3 placeholder)}` — 녹화 유무 구간(스크럽바용) |
| GET | `/playback/cameras/{camera_id}/segments` | playback:read | `from,to` | `[{id,start_ts,end_ts,duration_ms,first_keyframe_ms,container,codec}]` (재생 플랜) |
| GET | `/playback/cameras/{camera_id}/index.m3u8` | playback:read | `from,to` | HLS VOD 플레이리스트(세그먼트→`#EXTINF`, gap=`#EXT-X-DISCONTINUITY`) |
| GET | `/playback/segments/{segment_id}/data` | playback:read | `Range` 헤더 | 세그먼트 바이트(`206 Partial Content`, `Accept-Ranges: bytes`) |
| GET | `/playback/cameras/{camera_id}/frame` | playback:read | `ts`(UTC) | 해당 시각 키프레임 JPEG(스크럽 미리보기) — 온디맨드 ffmpeg |
| GET | `/playback/segments/{segment_id}/thumb` | playback:read | — | 세그먼트 대표 썸네일 JPEG(캐시) |

#### 내보내기/다운로드 (`export.py`)
| Method | Path | 권한 | 요청 | 응답 |
|---|---|---|---|---|
| POST | `/export/jobs` | clips:export | `{camera_id,start_ts,end_ts,mode,container?,transcode_preset?}` | `{job_id, status:'queued'}` (Celery enqueue) |
| GET | `/export/jobs/{job_id}` | clips:export(소유 or admin) | — | `{status,progress,download_token?,output_size_bytes?,error_message?}` |
| GET | `/export/jobs` | clips:export | `page,items_per_page` | 본인 작업 목록(서버 페이지네이션) |
| DELETE | `/export/jobs/{job_id}` | clips:export(소유) | — | 취소(Celery revoke) 또는 결과 삭제 |
| GET | `/export/download/{download_token}` | clips:export(토큰검증) | `Range` | 결과 파일 다운로드(`Content-Disposition: attachment`, range 지원) |

#### 스토리지/디스크 (`storage.py`)
| Method | Path | 권한 | 요청 | 응답 |
|---|---|---|---|---|
| GET | `/storage/disks` | storage:read | — | 등록 디스크 + 실시간 용량/사용률/status |
| POST | `/storage/disks` | storage:manage | `{mount_path,name,role,reserved_free_bytes,weight,enabled}` | 생성된 disk(스캔 결과로 폼 prefill) |
| PUT | `/storage/disks/{id}` | storage:manage | role/enabled/reserved/weight/name | 갱신. enabled→false 시 신규쓰기 제외(기존 세그먼트 유지) |
| DELETE | `/storage/disks/{id}` | storage:manage | `{mode:'unregister'|'evacuate'}` | unregister=인덱스만 제거 경고 / evacuate=세그먼트 다른 디스크로 이전 작업 enqueue |
| GET | `/storage/discover` | storage:manage | — | 미등록 마운트 후보 `[{mount_path,device,fs_uuid,total_bytes,free_bytes}]` |
| GET | `/storage/pool` | storage:read | — | 풀 요약(역할별 합계·여유·예상 보존일수·경고) |
| GET | `/storage/policies` / `/storage/policies/{camera_id}` | storage:read | — | 정책 조회(카메라별 + 전역 fallback) |
| PUT | `/storage/policies/{camera_id}` | retention:manage | 4.2 필드 | 정책 갱신 + **용량 검증 경고**(설정이 풀 용량 초과 시 `warnings[]` 동봉) |

> 인가 공통: 카메라 스코프 API는 `@permission_required` 후 컨트롤러에서 `camera_id`가 사용자 ACL에 포함되는지 재확인. 응답에는 권한 있는 카메라/디스크만. 다운로드는 `download_token` + 요청자 동일성/권한 재검.

### 5.3 컨트롤러/서비스 역할 요약
- **RecordingController**: 모드 토글 시 `storage_policies.record_mode` 갱신 → supervisor에 reconcile(아래 5.4). manual start/stop은 `recordings` 생성/마감 + 해당 구간 세그먼트 `reason=manual` 마킹.
- **PlaybackController** + **playback_planner**: 구간 질의 → `segments` 인덱스 조회 → 연속/갭 계산 → 재생 플랜(HLS/MP4/range) 생성. seek는 `first_keyframe_ms`로 보정.
- **ExportController** + **transcode task**: 구간을 덮는 세그먼트 추출 → copy(concat) 또는 transcode → `export_jobs` 상태/진행률 갱신.
- **StorageController** + **storage_manager**/**disk_scanner**: 디스크 CRUD·발견·풀 요약·쓰기 디스크 선택·워치독.
- **RetentionController** + **retention_engine**: 정책 평가·로테이션 실행(주기 task가 호출).

### 5.4 supervisor reconcile 채널
API가 모드를 바꾸면 즉시 반영되도록 **Redis pub/sub 채널** `axp:recorder:reconcile`에 `{camera_id, action}`을 publish. recorder_supervisor가 구독하여 해당 카메라 ffmpeg를 start/stop. pub/sub 유실 대비, supervisor는 주기(예: 10s)로 DB `storage_policies`를 폴링해 desired state와 actual state를 맞추는 **수렴 루프**도 함께 둔다(이벤트+폴링 이중화).

---

## 6. 녹화·스토리지 엔진

### 6.1 데이터 흐름
```
go2rtc(rtsp://axp-go2rtc:8554/{go2rtc_name})  ← 카메라당 1연결(P1)
        │ copy (무재인코딩)
   recorder_supervisor ── per-camera ffmpeg ──▶ cache disk: /{cache}/{camera}/YYYY/MM/DD/HH/seg-<ts>.mp4
        │                                            │ (close 콜백/감시)
        │                                       segment_indexer ──▶ INSERT segments(tier=cache)
        ▼ (주기) segment_sweep: cache→record 승격(이동/하드링크) + tier 갱신
   storage_manager: 쓰기 디스크 선택(부하분산) · 여유공간 워치독
   retention_engine(Celery): 보존(일수+용량)·용량초과정책 로테이션
```

### 6.2 세그먼트 컨테이너 선택: fMP4 vs MPEG-TS (근거)
| 기준 | fragmented MP4 (선택, 기본) | MPEG-TS |
|---|---|---|
| 무재인코딩 copy | O | O |
| 브라우저 직접 재생(MSE/`<video>`) | **O (MP4 range로 바로)** | X(HLS 컨테이너 필요) |
| HLS 호환 | O (LL-HLS/fMP4 세그먼트) | O (전통 HLS) |
| 손상 복원력(중간부터 재생) | 보통(moof 단위) | **강함(패킷 자기복원)** |
| 메타/seek 정확성 | **강함** | 보통 |
| H.265 + 브라우저 | 제한적(코덱 의존) | 제한적 |

**결정**: 기본 **fMP4**(`-f segment`의 mp4 + `-movflags +frag_keyframe+empty_moov+default_base_moof`). 이유: 다운로드/재생을 재인코딩 없이 브라우저·MP4 range로 바로 줄 수 있고 seek 정확. 단, `storage_policies.container`로 **MPEG-TS 선택 가능**(불안정 네트워크/H.265 카메라에서 복원력 우선 시). HLS 제공 시 fMP4 세그먼트는 fMP4-HLS, TS 세그먼트는 전통 HLS로 매핑.

### 6.3 ffmpeg 세그먼트 명령행 (실제)
공통 입력 옵션(P1 camera.py 패턴 계승):
```
ffmpeg -hide_banner -loglevel warning \
  -rtsp_transport tcp -rw_timeout 5000000 -stimeout 5000000 \
  -use_wallclock_as_timestamps 1 -fflags +genpts \
  -i rtsp://axp-go2rtc:8554/{go2rtc_name} \
```
**fMP4 세그먼트(기본, copy)**:
```
  -map 0:v:0 -map 0:a? -c copy \
  -f segment -segment_time 10 -segment_atclocktime 1 \
  -reset_timestamps 1 -strftime 1 \
  -segment_format mp4 \
  -segment_format_options movflags=+frag_keyframe+empty_moov+default_base_moof \
  "/mnt/axp/disk1/{camera}/%Y/%m/%d/%H/seg-%Y%m%d-%H%M%S.mp4"
```
**MPEG-TS 세그먼트(대안)**:
```
  -map 0:v:0 -map 0:a? -c copy \
  -f segment -segment_time 10 -segment_atclocktime 1 \
  -reset_timestamps 1 -strftime 1 -segment_format mpegts \
  "/mnt/axp/disk1/{camera}/%Y/%m/%d/%H/seg-%Y%m%d-%H%M%S.ts"
```
포인트:
- `-c copy`로 **무재인코딩**(CPU 거의 0). `-segment_atclocktime 1`로 벽시계 정렬(세그먼트 경계가 카메라 간 정렬 → 타임라인 스티칭/seek 단순).
- copy 모드에서 세그먼트는 **GOP(키프레임) 경계**에서 잘림 → 정확히 10s가 아닐 수 있음. seek 정확도는 `first_keyframe_ms`와 재생 시 미세 보정으로 해결. (카메라 GOP를 2s로 설정 권장 — P1 capability와 연계, 14절.)
- `%Y/%m/%d/%H` strftime로 **디렉터리 샤딩 자동 생성**(시간당 폴더). 한 폴더에 ~360 파일(10s·1h)로 inode 적정.
- **디스크 전환**: 출력 경로의 디스크 루트를 바꾸려면 ffmpeg 재시작이 필요(단일 프로세스는 단일 경로). 따라서 부하분산은 **(a) 카메라별 디스크 고정(per_camera)** 이 가장 간단·효율. least_used/RR은 시간(예: HH 폴더 롤오버) 단위로 supervisor가 ffmpeg를 무중단 핸드오버(겹치기)하거나, **세그먼트 후처리 이동(segment_sweep)** 으로 분산(6.6). MVP: per_camera 기본 + sweep 기반 record 디스크 분산.

> **세그먼트 인덱싱 방식 2안**:
> (A) **감시(watch)**: supervisor가 출력 디렉터리를 `inotify`(watchdog 라이브러리)로 감시, 파일 close 시 `ffprobe`로 메타 추출 후 INSERT. 실시간성↑.
> (B) **segment muxer 콜백**: ffmpeg `-f segment`는 직전 세그먼트가 닫힐 때 다음 파일을 연다 → "현재 파일 외 나머지는 완성됨"을 이용해 폴링 스캔.
> **채택**: (A) watchdog + 주기 reconcile 스캔(B로 누락 보정). 메타는 `ffprobe -show_streams -show_format -print_format json`.

### 6.4 recorder_supervisor 설계
- 위치: `worker/recorder/` 진입점(`axp-worker` 컨테이너, `--role recorder`). 단일 프로세스 + per-camera 자식 ffmpeg.
- 상태머신(카메라별): `stopped → starting → recording → reconnecting → error → stopped`.
- 핵심 루프(의사코드):
```python
class RecorderSupervisor:
    procs: dict[camera_id, FFmpegProc]  # PID, popen, last_segment_at, restart_count, backoff

    def run(self):
        subscribe('axp:recorder:reconcile')  # 이벤트
        while True:
            desired = load_desired_state()      # storage_policies.record_mode + manual active
            for cam in desired.recording:
                if cam not in self.procs or self.procs[cam].dead():
                    self.start(cam)
            for cam in list(self.procs):
                if cam not in desired.recording and not desired.manual(cam):
                    self.stop(cam)
            self.health_check()                 # stall 감지·재시작·DB upsert
            wait(reconcile_signal_or_timeout=10)

    def start(self, cam):
        disk = storage_manager.pick_write_disk(cam)   # 6.5
        url  = go2rtc.restream_url(cam.main_stream)
        cmd  = ffmpeg.build_segment_cmd(cam, disk, policy)
        proc = spawn(cmd); set_state(cam,'starting')

    def health_check(self):
        for cam, p in self.procs.items():
            if p.poll() is not None:                   # 죽음
                self.restart_with_backoff(cam)         # 2s→×1.5→max 30s
            elif now - p.last_segment_at > STALL(=3×seg): # 멈춤
                kill(p); self.restart_with_backoff(cam)
            upsert_recorder_health(cam, state, p.pid, p.last_segment_at, p.restart_count)
```
- **stall 판정**: 마지막 세그먼트 close 이후 `3 × segment_seconds` 초과 시 멈춤으로 간주(카메라 끊김/ffmpeg 행). camera.py의 STALL_TIMEOUT 패턴 계승.
- **백오프**: 재시작 폭주 방지(2s→×1.5→30s 상한), `restart_count` 누적해 임계 초과 시 `error` 상태 + 알림(P5에서 라우팅).
- **graceful stop**: `SIGINT`로 ffmpeg에 보내 현재 세그먼트 flush 후 종료(데이터 손실 최소화), 미응답 시 SIGKILL.
- **manual 녹화**와 상시는 **동일 ffmpeg 프로세스**를 공유(상시 켜져 있으면 manual은 구간 마킹만, 상시 꺼져 있으면 manual이 ffmpeg를 일시 구동). 즉 manual = "녹화 보장 + 보호 마킹".

### 6.5 다중 HDD 풀 · 쓰기 디스크 선택 · 부하분산
`storage_manager.pick_write_disk(camera)`:
```
후보 = disks where role in ('cache' for live write) and enabled and status='online'
       and free_bytes - reserved_free_bytes > MIN_HEADROOM(예: 5GB)
if 후보 비어있음: 워치독 강제 로테이션 1회 시도 → 재평가; 여전히 없으면 over_capacity_policy 적용
strategy = policy.balance_strategy
  per_camera:   policy.pinned_disk_id ?? hash(camera_id) % len(후보) → 고정(첫 선택 시 pinned 저장)
  least_used:   argmax(free_bytes - reserved) (가중 weight 반영: (free-reserved)*weight 최대)
  round_robin:  전역 카운터 % len(후보) (시간 폴더 롤오버마다 회전)
```
- **쓰기 디스크 역할**: 라이브 세그먼트는 항상 **cache** 역할 디스크에 먼저 기록(전버퍼 보장·SSD 권장). 이후 `segment_sweep`이 보존 대상이면 **record** 디스크로 승격(이동/하드링크). cache 디스크가 없으면 record에 직접 기록(소규모 구성 허용).
- **읽기 분산**: 세그먼트가 여러 디스크에 흩어져 있으므로 재생 시 자연히 여러 스핀들에서 읽힘. playback_planner는 디스크 status를 보고 offline 디스크 세그먼트는 갭으로 표시.
- **부하분산 단순화 채택**: copy-ffmpeg는 단일 경로 → **카메라→디스크 매핑은 per_camera(고정)을 기본**, 풀 전체 균형은 sweep이 record 디스크로 분산하며 달성. least_used/RR은 "신규 카메라 배치"와 "sweep 목적지 선택"에서 사용.

### 6.6 캐시(전/후 버퍼) 메커니즘
- **전버퍼** = cache 디스크의 롤링 세그먼트 자체. `cache_buffer_seconds`(기본 60s) 동안의 세그먼트는 항상 디스크에 존재 → 이벤트 발생 시 "직전 N초"는 **이미 파일로 존재**하므로 RAM 불필요.
- **이벤트 회수 API(서비스 레벨, P3가 호출)**: `cache_buffer.retain(camera_id, event_ts, pre=N, post=M) -> recording_id`
```
start = event_ts - N; end = event_ts + M
세그먼트(camera, start..end) 조회 → 없거나 진행중인 끝부분은 post 만료까지 대기 마킹
recordings 생성(reason='event'(P3)/'manual', retention_class='protected', start, end)
교차 세그먼트들을 reason 보호 마킹(로테이션 제외)
```
- **후버퍼**: post 구간은 미래 → 해당 시간까지 supervisor가 계속 기록(상시면 자동, 비상시면 이벤트가 임시 녹화 ON 유지)하고, end 도달 시 구간 확정. 본 Phase는 상시 ON 가정에서 메커니즘만 구현·검증, 실제 트리거 연결은 P3.
- **캐시 롤링 보존**: cache 디스크는 `cache_buffer_seconds`(또는 디스크 여유 임계)까지만 유지하고 그 이전 세그먼트는 (a) 보존 대상이면 record로 승격, (b) 아니면(상시 OFF·보호 아님) 삭제.

### 6.7 신규 디스크 감지 (disk_scanner)
- 방법(컨테이너 환경 고려):
  - 1차: `psutil.disk_partitions(all=False)` → 마운트 목록·fstype. 컨테이너는 host `/proc/mounts`를 봐야 하므로 `psutil.disk_partitions`가 컨테이너 마운트만 보면 **host `/host/proc/mounts` bind-mount**를 파싱(또는 `/mnt/axp/*` 디렉터리 스캔으로 bind된 디스크 발견).
  - 보강: `lsblk -J -o NAME,MOUNTPOINT,SIZE,FSTYPE,UUID`(host 권한 필요 시 호스트 측 헬퍼) — device/fs_uuid 매핑.
  - 용량: `shutil.disk_usage(mount_path)` 또는 `psutil.disk_usage`.
- 후보 산정: 마운트되어 있고 fstype이 실파일시스템(ext4/xfs/btrfs/zfs 등)이며, `disks`에 (mount_path 또는 fs_uuid)로 미등록인 항목.
- 표면화: `GET /storage/discover`가 후보 반환 → 프론트 StorageManager가 배너/모달로 "녹화 풀에 추가?" + 역할 선택(cache/record) + reserved_free 입력 → `POST /storage/disks`.
- 안전장치: system 디스크(루트 `/`가 위치한 마운트)는 후보에서 제외하거나 role=system 고정 제안. 등록 전 **쓰기 가능 검증**(임시 파일 write/delete) + fs_uuid 기록(마운트 경로 변동 추적).
- 주기: `disk_scan` Celery task 5분 간격 + 용량(free/total) 갱신(`disks.free_bytes` 캐시 → 워치독/부하분산이 사용).

### 6.8 여유공간 워치독
- 트리거 이중화: (a) `disk_scan`(5분)에서 임계 평가, (b) `storage_manager.pick_write_disk` 호출 시 즉시 평가, (c) `retention` 주기(예: 매 분) 평가.
- 규칙:
```
for disk in record/cache disks:
    if disk.free_bytes <= disk.reserved_free_bytes + SOFT_MARGIN:
        retention_engine.free_space(disk, target=disk.reserved_free_bytes + HARD_MARGIN)
    if disk.free_bytes <= disk.reserved_free_bytes:   # 임박/침범
        강제 즉시 로테이션(가장 오래된 비보호 세그먼트부터)
system 디스크: free <= reserved 이면 critical 경고(녹화 영향 없게 record/cache와 분리 운영)
```
- system 동작 공간은 system 역할 디스크 분리 + record/cache의 reserved_free로 **항상 확보**.

### 6.9 보존/로테이션 (retention_engine)
- 평가 단위: 카메라별 정책(일수 AND 용량) + 디스크별 여유. 보호(`recordings.retention_class in ('protected','event')`) 구간 세그먼트는 **삭제 제외**.
- 의사코드(주기 `retention` task):
```python
def run_retention():
    # 1) 일수 기반(카메라별)
    for cam, pol in active_policies():
        if pol.retention_days:
            cutoff = utcnow() - days(pol.retention_days)
            for seg in segments(cam).older_than(cutoff).not_protected():
                delete_segment(seg)   # 파일 unlink + row DELETE
    # 2) 용량 기반(카메라별 상한)
    for cam, pol in active_policies():
        cap = pol.retention_max_bytes or pool_share(cam)   # NULL이면 풀 비례 배분
        used = sum_size(cam)
        if used > cap and pol.over_capacity_policy == 'delete_oldest':
            for seg in segments(cam).oldest_first().not_protected():
                delete_segment(seg); used -= seg.size
                if used <= cap: break
        elif used > cap and pol.over_capacity_policy == 'stop_recording':
            set_record_paused(cam, True); raise_warning(cam,'capacity_full')
        elif used > cap and pol.over_capacity_policy == 'warn_only':
            raise_warning(cam,'capacity_exceeded')
    # 3) 디스크 여유(워치독 보강) — 풀 전체에서 가장 오래된 비보호부터
    for disk in record_cache_disks():
        while free(disk) < disk.reserved_free_bytes + HARD_MARGIN:
            seg = oldest_unprotected_on(disk)
            if not seg: raise_critical(disk,'no_evictable_space'); break
            delete_segment(seg)

def delete_segment(seg):
    try: os.unlink(abs_path(seg))
    except FileNotFoundError: pass
    db.delete(seg)   # 인덱스 정합: 파일 먼저, DB 나중 (고아 인덱스 < 고아 파일)
```
- **설정 초과 사전 경고**: 정책 저장 시(`PUT /storage/policies`) 모든 카메라 `retention_max_bytes` 합 + 예약여유 > 풀 record 용량이면 `warnings:['pool_overcommit']` 반환. 또한 `retention_days × 카메라 평균 비트레이트 추정 용량` > 가용 용량이면 "보존일수 미달 가능" 경고. UI가 표시.
- **삭제 순서 원칙**: 파일 unlink → DB row 삭제(중간 실패 시 고아 인덱스만 남고, `segment_sweep`이 고아 인덱스/고아 파일 양방향 정리).
- **빈 디렉터리 정리**: 시간 폴더가 비면 rmdir(주기 sweep).

### 6.10 Celery 작업 정의 (`celeryconfig.beat_schedule` 추가)
```python
beat_schedule.update({
  'axp_run_retention':        {'task':'server.task.list.retention.run_retention',         'schedule': crontab(minute='*')},      # 매분 여유/용량 점검
  'axp_disk_scan':            {'task':'server.task.list.disk_scan.scan_disks',             'schedule': crontab(minute='*/5')},    # 5분 디스크/용량
  'axp_segment_sweep':        {'task':'server.task.list.segment_sweep.sweep',              'schedule': crontab(minute='*/2')},    # 캐시→record 승격·고아 정리
  'axp_expire_export_jobs':   {'task':'server.task.list.transcode.expire_export_jobs',     'schedule': crontab(hour='*', minute='17')},  # 만료 결과 정리
  'axp_thumbnail_backfill':   {'task':'server.task.list.thumbnail.backfill_thumbnails',    'schedule': crontab(minute='*/10')},
})
imports = ("server.task.list",)
```
큐 작업(이벤트성, beat 아님): `transcode.run_export_job(job_id)`(POST /export/jobs에서 `.delay()`), `storage.evacuate_disk(disk_id)`(디스크 제거 시). 모든 task는 ams 패턴대로 `@shared_task()` + `@celery_use_db()`로 작성하고 예외는 `sentry_sdk.capture_exception`.

---

## 7. 재생·다운로드

### 7.1 타임라인 데이터(스크럽바)
- `GET /playback/.../timeline?from&to&resolution`: `segments`를 `(camera_id, start_ts)` 인덱스로 범위 조회 후, 인접 세그먼트(gap < 2×seg)를 병합해 **연속 녹화 구간 ranges[]** 와 **gaps[]** 를 산출. resolution(버킷)으로 다운샘플해 응답 페이로드 축소(긴 기간 줌아웃 대비). P3 이벤트 마커/P4 객체 마커는 같은 응답의 `events[]`/`objects[]` 슬롯으로 확장(본 Phase 빈 배열).
- 표시: DESIGN.md대로 타임라인은 어두운 트랙 + 녹화 구간만 채워진 막대(여백=갭), 1개 accent로 현재 재생 위치 표시.

### 7.2 재생(스티칭·seek)
두 가지 제공, 클라이언트가 택일:
- **A. HLS VOD** `index.m3u8?from&to`: 세그먼트를 `#EXTINF`로 나열, 갭은 `#EXT-X-DISCONTINUITY`. fMP4면 `#EXT-X-MAP`(init) 포함, TS면 전통 HLS. 세그먼트 본문은 `/playback/segments/{id}/data`로 서빙. 장점: 가변 구간/긴 재생/네이티브 seek. hls.js 사용.
- **B. MP4 direct(단일/소수 세그먼트)**: 짧은 구간/단일 세그먼트는 `/playback/segments/{id}/data`를 `<video>` + Range로 바로 재생(가장 단순·저지연).
- **seek/스크럽**: 사용자가 시각 T로 점프 → planner가 T를 포함하는 세그먼트 찾기 → 그 세그먼트 시작부터 로드하되 `currentTime` 보정. copy 세그먼트라 정확 seek은 키프레임 단위 → `first_keyframe_ms`로 시작 보정, 프레임 정밀 미리보기는 `/frame?ts=`(온디맨드 디코드 JPEG)로 대체.
- **range 서빙 구현**: `playback/segments/{id}/data`는 `Range` 헤더 파싱 → `206` + `Content-Range`/`Accept-Ranges: bytes`. Flask `send_file`은 `conditional=True`로 range 자동 지원(ams의 `send_file`/`partial_content` 패턴 활용). 디스크 offline이면 404+갭.

### 7.3 `/frame?ts=` (스크럽 미리보기 / 스냅샷)
해당 시각을 포함하는 세그먼트에서 단일 프레임 추출:
```
ffmpeg -hide_banner -loglevel error -ss <offset_in_seg> -i <segment> -frames:v 1 -q:v 3 -f mjpeg pipe:1
```
결과 JPEG은 단기 캐시(Redis/디스크). 세그먼트 대표 썸네일(`/thumb`)은 `thumbnail` task가 세그먼트 첫 키프레임으로 미리 생성.

### 7.4 클립 내보내기 / 트랜스코드
`POST /export/jobs` → `export_jobs` 생성 → `transcode.run_export_job.delay(job_id)`.
- 대상 세그먼트: `segments(camera, start..end)` 조회(경계 세그먼트 포함).
- **copy 모드(빠름, 무재인코딩)** — concat demuxer:
```
# list.txt: file '/abs/seg1.mp4' ...
ffmpeg -hide_banner -f concat -safe 0 -i list.txt \
  -ss <start_trim> -to <end_trim> -c copy -movflags +faststart out.mp4
# 경계 트림은 키프레임 단위 한계 → 정확 트림 필요 시 transcode 모드 안내
```
- **transcode 모드(정확 트림 + 호환성 H.264)**:
```
ffmpeg -hide_banner -f concat -safe 0 -i list.txt \
  -ss <start_trim> -to <end_trim> \
  -c:v libx264 -preset veryfast -crf 23 -pix_fmt yuv420p \
  -vf "scale=-2:1080" \           # preset별(1080p/720p)
  -c:a aac -b:a 128k -movflags +faststart out.mp4
```
- 진행률: ffmpeg `-progress pipe:1`(out_time_ms 파싱) → 총 구간 대비 % → `export_jobs.progress` 갱신(주기적 commit). 취소는 Celery revoke + 프로세스 kill.
- 결과 저장: record 디스크의 `exports/{job_id}/clip.mp4`, `download_token` 발급, `expires_at=+24h`. `expire_export_jobs`가 만료분 파일/row 정리.
- 다운로드: `GET /export/download/{token}` → 토큰·권한 검증 후 `send_file(..., as_attachment=True, conditional=True)`(Range 지원, 큰 파일 스트리밍).
- H.265 원본의 브라우저 재생은 transcode(H.264) 결과로 보장. copy 결과는 다운로드용(로컬 플레이어).

---

## 8. 프론트엔드(TS)

> React 18 + Vite + TS + Tailwind + Radix/shadcn + TanStack Query. DESIGN.md(Tesla) 적용: 흰 캔버스/풍부한 여백/그림자·그라데이션 배제/단일 accent `#3E6AE1`/4px 라운드/0.33s 트랜지션. **단, 플레이어/타임라인 영역은 영상 가독성을 위해 Carbon Dark(`#171A20`) 표면 사용**(영상이 주인공 — "photography-first"의 NVR 변용). UI 텍스트 14px, 헤딩 Carbon Dark/본문 Graphite.

### 8.1 페이지/컴포넌트
- `pages/playback/` — 재생 페이지(좌: 카메라 선택, 중앙: Player, 하단: Timeline).
- `pages/storage/` — StorageManager(디스크 풀) + RetentionSettings(보존 정책).
- 컴포넌트:
  - **`<Player>`**: hls.js(HLS) / 네이티브 `<video>`(MP4 range) 토글. Carbon Dark 베젤리스 표면, 컨트롤바는 frosted(반투명 흰 0.75) 위에 14px 라벨. 재생/일시정지·속도(1x/2x/4x)·다운로드 버튼(accent 1개)·스냅샷.
  - **`<Timeline>`**: 가로 스크럽바. 어두운 트랙에 녹화 ranges만 채워진 막대(갭=빈 공간), 현재 위치는 `#3E6AE1` 1px 라인. 줌(시/일/주), 드래그 seek, 호버 시 `/frame?ts=` 미리보기 썸네일 팝오버. P3 이벤트/P4 객체 마커 레이어 슬롯 예약. TanStack Query로 `timeline` 캐시, 줌 변경 시 resolution 파라미터 조정.
  - **`<ScrubPreview>`**: 호버 좌표→ts 변환→프레임 미리보기(디바운스).
  - **`<StorageManager>`**: 디스크 카드 그리드(역할 배지·사용률 막대·status). 신규 디스크 발견 시 상단 배너 "새 디스크가 감지되었습니다 — 녹화 풀에 추가?"(Radix Dialog) → 역할/예약여유 입력. 그림자 없이 여백·테두리 최소.
  - **`<RetentionSettings>`**: 카메라별 보존(일수+용량) 폼(Formik+Yup 패턴), over_capacity_policy 라디오, 저장 시 백엔드 `warnings[]`를 인라인 경고로 표시(풀 초과/보존일수 미달 가능). 예상 보존일수 추정 표시.
  - **`<ExportDialog>`**: 구간(타임라인 드래그 선택) + 모드(copy/transcode) + 프리셋. 생성 후 `<ExportJobsList>`(TanStack Query 폴링)로 진행률·다운로드 버튼.
  - **`<RecorderStatusBadge>`**: 카메라별 헬스(recording/reconnecting/error) — 라이브/카메라 페이지에서 재사용.
- 라우팅/메뉴: P0 `menu.config`에 storage/playback 권한별 노출. API는 Axios + JWT 인터셉터(ams 패턴), 403→signin.

### 8.2 상호작용/모션
- 모든 상태 전환 0.33s cubic-bezier. 버튼 색상 전환만(스케일/이동 금지). 타임라인 seek은 즉각 반영 + 백그라운드 로딩 인디케이터(frosted).
- i18n ko/en, 시간 표시 KST(저장 UTC→표시 변환). 용량/숫자 `,` 포맷.

---

## 9. 작업 분해 (순서 있는 체크리스트)

1. **모델/마이그레이션**: `disks, storage_policies, segments, recordings, export_jobs, recorder_health` 모델 + SQL. 권한 키 추가(P0 권한맵).
2. **disk_scanner + storage CRUD API**: 발견(`/discover`)·등록·풀 요약(`/pool`). psutil/lsblk·쓰기검증·fs_uuid.
3. **storage_manager**: `pick_write_disk`(전략별) + 여유공간 워치독 골격.
4. **ffmpeg 빌더(service/ffmpeg.py)** + 세그먼트 명령행(fMP4/TS) 단위 검증(샘플 RTSP/파일).
5. **recorder_supervisor**(worker/recorder): 상태머신·spawn·헬스·백오프·graceful stop + Redis reconcile + 폴링 수렴.
6. **segment_indexer**: watchdog inotify + ffprobe 메타 → `segments` INSERT(tier=cache) + reconcile 스캔.
7. **recording API**: 모드 토글(→reconcile), manual start/stop(recordings+세그먼트 보호 마킹), health.
8. **segment_sweep task**: cache→record 승격(전략 분산), 고아 파일/인덱스 정합, 빈 폴더 정리.
9. **retention_engine + retention task**: 일수+용량+디스크여유 로테이션, over_capacity_policy, 설정 초과 경고.
10. **playback_planner + playback API**: timeline(ranges/gaps), segments, HLS m3u8, segment range 서빙, `/frame`.
11. **thumbnail task + `/thumb`**: 세그먼트 키프레임 썸네일.
12. **export API + transcode task**: copy(concat)·transcode(H.264) + 진행률 + download_token + 만료정리.
13. **프론트 Player/Timeline**: hls.js + range, 스크럽/seek/미리보기.
14. **프론트 StorageManager/RetentionSettings/ExportDialog/RecorderStatusBadge**.
15. **docker-compose**: HDD bind-mount, ffmpeg 설치, `axp-worker`(recorder role) 서비스, host /proc/mounts·lsblk 접근.
16. **테스트(unit/integration/e2e)** + 회귀(P1 라이브 영향 없음 확인).
17. PLAN.md·본 문서 "10/14" 갱신.

---

## 10. 다른 기능/Phase에 미치는 영향 (Cross-feature Impact) ★

| 대상 | 영향 / 본 Phase가 제공·요구하는 계약 |
|---|---|
| **P1 카메라/라이브** | go2rtc 재스트림 **소비자 추가**(녹화). go2rtc는 카메라당 1연결을 라이브+녹화+AI가 공유하므로 카메라 부하 불변. 단 go2rtc 재스트림 **이름 규칙·main/sub 매핑**을 본 Phase가 의존 → P1이 `streams.go2rtc_name`·codec/res 메타를 정확히 채워야 함. 카메라 삭제 시 녹화/세그먼트 처리(중단+보존정책) 훅 필요(P1 삭제 흐름에 콜백 추가). 라이브 페이지에 RecorderStatusBadge 추가. **카메라 GOP/키프레임 간격**(2s 권장)이 세그먼트 seek 정확도에 영향 → P1 capability/설정과 연계(14절). |
| **P3 이벤트/스마트/스케줄 녹화** | 본 Phase가 핵심 인프라 제공: ① `cache_buffer.retain(camera, ts, pre, post)` 전후버퍼 회수 서비스, ② `recordings(reason='event'/'schedule', retention_class='event')` 생성·세그먼트 보호 마킹 규약, ③ `segments.reason` 확장 슬롯, ④ timeline 응답의 `events[]` 슬롯. P3는 트리거만 붙이면 녹화/보존이 동작. 보존 분리(`event_retention_days`) 컬럼 선반영. **스케줄 녹화**는 `record_mode`를 시간대별로 토글하는 형태로 supervisor 수렴 루프 재사용. |
| **P4 AI** | AI 워커는 go2rtc에서 메인 스트림을 별도 소비(녹화와 독립). detection 메타는 본 Phase 세그먼트 시간축에 매핑(timeline `objects[]` 슬롯·세그먼트 start_ts 기준). AI 기반 녹화/마커는 P3·P4가 본 Phase recordings/segments에 연결. **세그먼트 시간 정확성(UTC ms)** 이 메타 정렬의 전제 → 본 Phase가 보장. |
| **P5 자동화/모니터/알림** | recorder_health `error`/디스크 워치독 critical/용량 초과 경고를 **알림 이벤트 소스**로 노출(P5 규칙엔진/푸시가 구독). 모니터(로컬 디스플레이)는 playback API/HLS 재사용. |
| **P6 패리티/폴리시** | 이중녹화(failover)는 storage_manager 디스크 선택을 다중 목적지로 확장(설계 여지 둠). 세그먼트 암호화/워터마크는 ffmpeg 파이프·세그먼트 컨테이너 계층에 삽입(fMP4 선택이 유리). 외부 공유링크는 export `download_token` 메커니즘을 scoped 토큰으로 확장. 엣지녹화 import는 `segments` 인덱싱 경로 재사용. |
| **인증/RBAC(P0)** | 신규 권한 키 7종 추가. 카메라/디스크 스코프 응답 필터링 필수(비인가 정보 비노출). 다운로드 토큰 권한 재검. |
| **DB/성능(횡단)** | `segments`는 최대 빈도 테이블 → 인덱스 설계·FK 회피·(대규모) 월별 파티셔닝이 전체 DB 성능에 직결. 로테이션 대량 DELETE는 배치(LIMIT)로 분할해 락 시간 최소화. |
| **인프라/배포(횡단)** | HDD bind-mount·동일 경로·ffmpeg·host 마운트 가시성 요구 → docker-compose/k8s(PV/hostPath) 변경. recorder는 장기 프로세스라 별도 워커 컨테이너로 스케일/재시작 격리. |
| **시간대(횡단)** | 세그먼트/녹화는 **UTC 저장**, 표시는 KST. PLAN의 "저장 UTC 권장"을 본 Phase가 강제(녹화 타임스탬프 정확성). 기존 ams의 KST-naive 저장 컨벤션과 **상충** → 미디어 시간 컬럼만 UTC로 통일(14절 확정 필요). |

---

## 11. 리스크 & 완화

| 리스크 | 영향 | 완화 |
|---|---|---|
| copy 세그먼트가 키프레임 경계로만 잘림 → 정확 seek/트림 한계 | 재생 위치/클립 경계 오차(최대 GOP) | 카메라 GOP 2s 권장, `first_keyframe_ms` 보정, 정확 트림은 transcode 모드 제공, 프레임 미리보기 `/frame` |
| ffmpeg 행/스트림 끊김으로 세그먼트 누락(녹화 공백) | 증거 공백 | stall 감지(3×seg)·백오프 재시작·헬스 알림(P5), reconcile 폴링 이중화, gap을 타임라인에 명시 |
| 디스크 가득/풀 오버커밋 | 녹화 중단·시스템 불안정 | reserved_free 워치독(다중 트리거)·system 디스크 분리·정책 저장 시 사전 경고·over_capacity_policy 선택 |
| 마운트 경로 변동/디스크 탈착 | 세그먼트 경로 깨짐·오삭제 | fs_uuid 기준 식별·status(offline) 표시·offline 디스크는 삭제/쓰기 대상 제외, 재마운트 시 재연결 |
| `segments` 폭증으로 조회/로테이션 지연 | 타임라인 느림·DELETE 락 | 인덱스 최적화·월별 파티셔닝·배치 삭제(LIMIT)·timeline 다운샘플 |
| 다수 카메라 동시 transcode로 CPU 폭주 | 시스템 부하 | export 전용 Celery 큐 동시성 제한(concurrency=N)·copy 우선 안내·preset veryfast |
| watchdog inotify 누락(대량 파일/네트워크 FS) | 인덱스 누락 | 주기 reconcile 스캔으로 보정·고아 파일/인덱스 양방향 정리 |
| copy 직접 다운로드의 H.265 브라우저 비호환 | 재생 불가 | 다운로드는 로컬재생용, 브라우저 재생은 transcode 결과/HLS로 보장 |
| go2rtc/카메라 메타 부정확(codec/res) | 잘못된 컨테이너/재생 실패 | ffprobe로 세그먼트 실측 메타 저장(스트림 메타 맹신 X) |

---

## 12. 테스트 계획 (unit/integration/e2e)

**Unit**
- `storage_manager.pick_write_disk`: 전략별(least_used 가중/per_camera 고정/RR), 후보 없음·예약여유 경계.
- `retention_engine`: 일수/용량/디스크여유 각각·보호 구간 제외·삭제 순서(파일→DB)·over_capacity_policy 3종.
- `playback_planner`: ranges/gaps 병합, seek 세그먼트 매핑, `first_keyframe_ms` 보정.
- ffmpeg 빌더: fMP4/TS/transcode/concat 명령행 문자열·옵션.
- disk_scanner: 후보 산정(미등록·system 제외·fstype 필터), fs_uuid 매칭.

**Integration**(테스트 RTSP 소스=ffmpeg testsrc 또는 샘플 mp4 루프 → 임시 go2rtc 또는 직접)
- supervisor: 모드 ON→세그먼트 파일 생성→`segments` INSERT, 프로세스 kill→자동 재시작+restart_count 증가, 모드 OFF→정지.
- manual start/stop: recordings 생성/마감 + 세그먼트 reason 보호 → 로테이션에서 제외 확인.
- 캐시버퍼 retain: pre/post 구간 세그먼트 protected 마킹, 후버퍼 미래 구간 도달 후 확정.
- retention task: 오래된 비보호 삭제 + 보호 보존 + 디스크 여유 회복.
- playback range: `206`/`Content-Range` 정확, HLS m3u8 세그먼트/discontinuity 정합.
- export copy/transcode: 결과 길이≈요청 구간, 진행률 갱신, download_token 다운로드(Range), 만료 정리.
- disk discover→register→쓰기 검증→풀 반영.

**E2E**(프론트)
- 카메라 상시 녹화 ON → 잠시 후 Timeline에 구간 표시 → 클릭 seek → Player 재생.
- 타임라인 드래그 구간 선택 → ExportDialog(copy) → 진행률 → 다운로드.
- StorageManager에서 신규 디스크 배너 → 역할 지정 등록 → 풀 사용률 갱신.
- RetentionSettings 보존 과다 설정 → 경고 인라인 표시.

**회귀**: P1 라이브/PTZ가 녹화 추가로 영향 없는지(go2rtc 연결 수·라이브 지연), 권한 없는 사용자 카메라/디스크/다운로드 접근 차단.

---

## 13. 성능·보안 체크포인트

**성능**
- 녹화 copy=무재인코딩(CPU≈0); 재인코딩은 export/`/frame`/thumbnail 온디맨드만(PLAN 원칙4).
- `segments` 인덱스로만 조회(테이블 풀스캔 금지), FK 미사용, N+1 회피(구간 일괄 조회). timeline 다운샘플로 페이로드 제한.
- 로테이션/스윕은 배치(LIMIT) + off-peak 친화. 대규모는 파티션 DROP.
- 재생/다운로드는 `send_file` 스트리밍 + Range(전체 로드 금지), HLS로 대용량 분할.
- recorder는 별도 워커 컨테이너로 격리, ffmpeg 자원(스레드) 최소 옵션.

**보안**
- 모든 API JWT + `@permission_required` + 카메라/디스크 ACL 재검, 응답에 비인가 항목 비노출.
- 다운로드: `download_token`(추측불가 랜덤) + 요청자/권한/만료 검증, 경로 조작 방지(세그먼트 abs 경로는 서버가 disk_id+rel_path로만 구성, 사용자 입력 경로 미수용 → **path traversal 차단**).
- ffmpeg 인자에 사용자 입력 직접 삽입 금지(카메라/디스크 ID→서버 매핑값만 사용), 명령은 리스트 인자(shell=False).
- 디스크 등록 시 쓰기검증·system 보호, 임의 마운트 경로 등록은 storage:manage 권한자만.
- 자격증명(P0 암호화)·go2rtc URL 등 민감정보 로그/응답 노출 금지.
- 패키지 최신 stable(ffmpeg, psutil, watchdog, hls.js), 알려진 취약점 점검.

---

## 14. 미해결 질문 / 결정 필요 사항

1. **시간 저장 표준**: 미디어 시간 컬럼을 **UTC**로 통일(녹화 정확성) — ams의 KST-naive 컨벤션과 상충. 미디어 테이블만 UTC로 분리할지 전사 UTC 전환할지 사용자 확정 필요.
2. **세그먼트 파티셔닝**: MVP 단일 테이블+인덱스로 시작하고 임계(예: 5M rows) 도달 시 월별 RANGE 파티션 전환 — 시점/자동화 합의.
3. **카메라 GOP/키프레임 간격**: seek/트림 정확도를 위해 카메라를 2s GOP로 설정 권장 — P1 카메라 설정 적용 범위(자동 강제 vs 권장)와 연계.
4. **부하분산 기본값**: per_camera(고정) 기본 + sweep 분산을 채택했는데, 라이브 단계에서 least_used 무중단 핸드오버(ffmpeg 겹치기)까지 구현할지(복잡도 vs 균형).
5. **recorder_health 영속화**: DB 테이블 vs Redis(빈번 갱신). 대시보드 실시간성·부하 고려해 택일.
6. **HLS vs MP4-range 기본 재생기**: 기본을 HLS(hls.js)로 둘지, 단일 세그먼트는 MP4 우선으로 자동 분기할지 UX 확정.
7. **cache 디스크 필수 여부**: 소규모(디스크 1개) 구성에서 cache 역할 없이 record 직접 기록 허용 범위(전후버퍼 보장 수준).
8. **컨테이너 내 호스트 마운트 가시성**: `/host/proc/mounts` bind vs lsblk 호스트 헬퍼 — 배포 환경(권한)별 채택 방식 확정(k8s hostPath 포함).
9. **export 결과 보존**: 기본 24h 자동만료 — 사용자별 다운로드 후 즉시 삭제/보존기간 정책 확정.

### 14.1 구현 시 채택한 결정 (2026-06-05, P2 구현)
- **1. 시간 저장**: 전 계층 **naive UTC**(P0/P1과 동일, SSOT §12.1). 세그먼트 `start_ts`는 ffmpeg `strftime`(컨테이너 TZ=UTC) 파일명에서 파싱 → naive UTC. 표시 KST.
- **세그먼트 디렉터리(★ 단순화)**: ffmpeg segment muxer가 부모 디렉터리를 생성하지 않아 시간 샤딩(`%Y/%m/%d/%H`) 대신 **카메라별 평면 디렉터리**(`{disk}/{camera_id}/seg-<ts>.mp4`, 시작 시 1회 생성). 시/일 경계 안전. 시간 샤딩은 후속(§14-2 파티셔닝과 함께).
- **2. 파티셔닝**: MVP **단일 테이블 + 인덱스**. 월별 RANGE 파티션은 임계 도달 시(후속).
- **세그먼트 인덱싱**: inotify 대신 **스캔 기반**(`segment_indexer`가 settle된 파일을 ffprobe→INSERT) — bind/네트워크 마운트에 견고. recorder 루프가 매 틱 호출.
- **3. GOP**: 카메라 2s GOP **권장**(강제 아님). copy seek 오차는 `first_keyframe_ms`+클라이언트 보정.
- **4. 부하분산**: **per_camera 핀 기본** + sweep이 record 디스크로 분산. least_used/RR도 지원(`pick_write_disk`). 라이브 무중단 핸드오버는 후속.
- **5. recorder_health**: **DB 테이블**(specced)로 영속.
- **6. 재생기**: WS/HLS 대신 **MP4 range 세그먼트 체이닝**(`<video>` + 'ended'→다음 세그먼트). HLS m3u8는 보너스 제공(외부 플레이어용). Flask WebSocket 불필요·헤드리스 검증 가능.
- **7. cache 디스크 선택**: 단일 디스크 구성 시 **record 직접 기록 허용**(`pick_write_disk` cache→record 폴백). sweep은 단일 디스크면 in-place tier 승격.
- **8. 호스트 마운트**: 디스크는 `AXP_DISK_ROOT(/mnt/axp)` 하위에 **bind-mount**, `disk_scanner`가 루트 서브디렉터리 스캔(+psutil). lsblk/blkid는 선택(fs_uuid best-effort).
- **9. export 보존**: 기본 **24h 자동만료**(`expire_export_jobs`).
- **recorder 배치**: Celery 아닌 **별도 `axp-recorder` 컨테이너**(`python -m worker.recorder`, `SNOWFLAKE_INSTANCE=3`). 모드 변경은 Redis `axp:recorder:reconcile` publish + 10s 폴링 수렴 이중화.

### 14.2 검증 메모
실카메라 부재 → 스토리지/보존/플레이백/ffmpeg 로직은 **unit 테스트**(pick_write_disk 전략·retention 일수/용량/보호·timeline ranges/gaps·ffmpeg 빌더·disk_scanner). 녹화→재생→내보내기는 **go2rtc `exec:ffmpeg` 합성 패턴**을 recorder가 녹화 → 세그먼트 인덱싱 → 타임라인/세그먼트 range 재생 → copy export 다운로드로 e2e 검증(`tests/_p2_recording_check.py`). **backend pytest 107 passed**, 프론트 `tsc`/`vite build` 무에러.
