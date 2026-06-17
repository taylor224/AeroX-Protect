# Phase 3 — 이벤트 + 스마트/스케줄 녹화

> 마스터 플랜: [`../PLAN.md`](../PLAN.md) · 디자인: [`../DESIGN.md`](../DESIGN.md) · 선행: [`phase-1.md`](phase-1.md)(카메라/capability/event-probe), [`phase-2.md`](phase-2.md)(세그먼트·캐시 전후버퍼·보존·타임라인).
> **구현 전 본 문서 + PLAN.md를 읽고, "10. Cross-feature Impact" 절을 반드시 확인·갱신**한다. 네임스페이스 `axp`, Flask MVC(view→controller→service/driver→model), Celery+Redis, 응답은 `ResponseBuilder`. 저장 타임스탬프는 **UTC `DATETIME(3)` 저장 / API는 epoch ms·ISO 직렬화 / 표시·스케줄 해석 KST**.

---

## 1. 목표 & 성공 기준(DoD)

P3는 "카메라가 무슨 일이 일어났는지 알려주면(이벤트), 시스템이 그것을 통일된 형태로 저장하고, 정책·스케줄에 따라 녹화/폐기/타임랩스/알림을 결정하며, 사용자는 이벤트로 타임라인을 필터링해 모션 위치 오버레이까지 보며 재생한다"를 완성한다.

**DoD (이 항목들이 단독 시연 가능해야 P3 완료):**

1. **이벤트 수신**: ONVIF PullPoint(또는 Base 폴백) / Hikvision `alertStream` / Hanwha SUNAPI 이벤트를 각 1대 이상 실기기/시뮬레이터에서 수신, 카메라당 구독 워커가 자동 기동·재구독·하트비트 유지.
2. **정규화**: 벤더 토픽 → 통일 타입(`motion`, `line_crossing`, `intrusion`, `tamper`, `audio`, `object` 등)으로 변환해 `events`에 적재(타입·시각(UTC ms)·소스·영역/좌표·스냅샷·raw payload). 동일 물리 이벤트의 start/end(또는 펄스)를 **디바운스/병합**해 하나의 `events` 행으로 관리.
3. **이벤트 기반 녹화**: 카메라·이벤트타입별 `event_policies`(action = record / discard / timelapse / notify_only, pre/post 초)에 따라, P2 캐시 롤링에서 **직전 N초 회수 + 이후 M초 보존**하여 `recordings(reason='event')` 생성. 연속 이벤트는 클립을 **확장/병합**(coalescing).
4. **스케줄 녹화**: 카메라별 주간 7×24(또는 분 해상도) 스케줄(`schedules`)로 연속/이벤트전용/오프 구간을 정의, 이벤트정책과 결합 규칙대로 동작. 연속녹화 구간은 `recordings(reason='schedule')`로 마킹.
5. **이벤트 필터 재생**: `GET /events`로 카메라·타입·기간·점수 필터 + 타임라인 마커 + 이벤트 클릭 → 해당 클립 재생(P2 playback 재사용). 재생 중 **모션 오버레이**(영역 폴리곤/박스) 표시.
6. **타임랩스**: 구간/이벤트 묶음 기반 ffmpeg 타임랩스 작업을 Celery로 생성, 진행률·결과물 다운로드.
7. **폴백**: 카메라가 이벤트 미지원(capability=false)일 때 UI가 명확히 안내하고, **서버측 모션감지는 P4 연계**임을 노출(P3에서는 stub 인터페이스만 제공).
8. **테스트**: 정규화 매핑·디바운스·정책 결정·스케줄 결합·전후버퍼 회수 경로에 unit/integration, 이벤트 필터 재생 e2e 1개 이상 그린.

---

## 2. 범위 (In-scope / Out-of-scope)

### In-scope
- 카메라측 이벤트 **구독·수신·정규화·저장**(ONVIF PullPoint/Base, Hikvision alertStream, Hanwha SUNAPI).
- 구독 **수명주기 관리**: 생성/갱신/재구독/하트비트/만료/자격증명 갱신/장애 백오프, 카메라 add/remove/credential-change에 반응.
- **이벤트 정책 엔진**(카메라×이벤트타입 → action + pre/post buffer + 쿨다운 + 활성 스케줄 윈도).
- **녹화 스케줄**(주간 그리드, 연속/이벤트/오프) 및 정책과의 결합 규칙.
- **전후버퍼 클립 생성**: P2 segment_indexer/캐시에서 회수→`recordings` 생성·병합.
- **이벤트 필터 타임라인/재생 API + UI**, **모션 오버레이** 메타 저장·렌더.
- **타임랩스** 생성 작업(ffmpeg) + 다운로드.
- 이벤트 발생 시 **알림 트리거 발행**(인앱 WS/배지). 외부 채널(푸시/이메일/웹훅) 실제 전송과 규칙엔진은 **P5**가 소비.

### Out-of-scope (다른 Phase)
- **서버측 객체 detection(YOLO)·사람/차량 분류·스마트서치**: P4. (P3는 `object` 정규화 타입과 `events`/`detections` 연결 지점만 제공.)
- **규칙엔진/스피커/IO/푸시·이메일·웹훅 실제 전송**: P5. (P3는 `axp.event.created` 내부 시그널·`event_outbox` 발행만.)
- 라이브 송출(go2rtc)·세그먼트 레코더 자체·다중HDD·보존정책 **엔진 구현**: P2 소유(P3는 호출만).
- 카메라 온보딩·capability/event 프로빙 **구현**: P1 소유(P3는 결과 소비).
- LPR·얼굴·오디오 분류·배회·혼잡 등 고급 분석: P6.

---

## 3. 선행 의존성

| 출처 | P3가 사용하는 산출물 | 사용처 |
|---|---|---|
| **P0** | `axp` 패키지 골격, MVC/Blueprint 등록, `BaseDB`(Snowflake ID·soft delete·audit 컬럼), `ResponseBuilder`, JWT `@login_required`/`@permission_required`, Celery `celery_use_db()`, 자격증명 암호화(`util.crypto`), Redis, WS 허브, i18n | 전 영역 |
| **P1** | `cameras`(vendor/driver/host/암호화 자격증명/capabilities JSON/status), `streams`(go2rtc_name, main/sub), `driver/onvif·isapi·sunapi`(인증·세션·엔드포인트), `service.capability_probe`(event 지원여부·이벤트 토픽 목록·PTZ 등), 카메라 CRUD 시그널 | 구독 워커가 카메라/자격증명/capability 취득, 이벤트 토픽 매핑 결정 |
| **P2** | `segments`(camera/disk/path/start_ts/end_ts/size), `recordings`(reason/retention_class/start_end/segment 참조), `service.segment_indexer`(시각→세그먼트 조회), **캐시 디스크 롤링 세그먼트(전후버퍼 원천)**, `service.storage_manager`(disk 선택), playback API(`GET /playback/timeline`, 클립 스트림/HLS), `task.transcode`(ffmpeg copy/transcode 헬퍼), `task.thumbnail` | 전후버퍼 회수·클립 materialize·타임라인 병합·타임랩스 소스 |
| **P4(역방향)** | (P3가 **제공**) `events` 모델·`axp.event.created` 시그널·서버측 모션 stub | P4 detection이 `events`에 object 타입 추가·링크 |
| **P5(역방향)** | (P3가 **제공**) `events`·`event_outbox`·정규화 타입 | P5 규칙엔진이 트리거로 소비 |

**P3 착수 전 확인(블로킹):** P2의 ① 캐시 세그먼트 보관시간(전버퍼 상한 = 캐시 잔존시간) ② `segment_indexer` 시각→세그먼트 조회 API 시그니처 ③ `recordings` 생성/병합 API ④ playback 타임라인 응답 스키마. P1의 ⑤ `capability_probe`의 event 토픽 표현 형식.

---

## 4. 데이터 모델

> 컨벤션(ams 패턴): PK `id BIGINT`(Snowflake, app 생성), 모든 시각 컬럼은 **UTC `DATETIME(3)` 저장 / API는 epoch ms·ISO 직렬화 / 표시·스케줄 해석 KST** + 조회/정렬용 `*_ts` 인덱스. 감사 컬럼 `created_at/updated_at/deleted_at`(soft delete), 생성 주체가 사람인 테이블만 `created_by_id`. 카메라/세그먼트 등 대량·고빈도 테이블은 **FK 미설정**(PLAN 성능 원칙) — 논리적 참조 컬럼 + 인덱스만. 스키마 `axp`(전용 DB라 테이블 prefix 없음).

신규 테이블: **`events`, `event_policies`, `schedules`, `timelapse_jobs`, `event_outbox`**. 보조: `camera_subscriptions`(구독 상태, 선택적으로 Redis만으로 대체 가능 — 아래 5.5 참조).

### 4.1 `events` — 정규화된 이벤트(고빈도, append 중심)

| 컬럼 | 타입 | 설명/인덱스 |
|---|---|---|
| `id` | BIGINT PK | Snowflake |
| `camera_id` | BIGINT | 논리 FK(cameras.id). idx `(camera_id, start_ts)` |
| `type` | VARCHAR(32) | 정규화 타입(아래 6.4 enum). idx `(type, start_ts)` |
| `subtype` | VARCHAR(48) NULL | 벤더 세부(예: `linedetection`, `fielddetection`, `regionEntrance`) |
| `state` | TINYINT | 0=active(start만 수신, 진행중) · 1=ended · 2=pulse(시작/끝 구분없는 단발). idx 부분조회용 |
| `start_ts` | DATETIME(3) | UTC. **카메라 시각 신뢰 불가 시 서버 수신 시각**(아래 6.6). idx |
| `end_ts` | DATETIME(3) NULL | active 동안 NULL |
| `duration_ms` | INT NULL | ended 시 채움(소요시간, 파생, 정렬·필터용) |
| `score` | SMALLINT NULL | 0–100(모션 민감도/AI conf 정규화). 없으면 NULL |
| `source` | VARCHAR(16) | `onvif` / `isapi` / `sunapi` / `server`(P4 모션 stub) / `manual` |
| `channel` | SMALLINT NULL | 멀티채널/멀티센서 카메라의 채널/스트림 번호 |
| `region` | JSON NULL | 모션/구역 메타: `{"w":1920,"h":1080,"shapes":[{"kind":"poly","pts":[[x,y],...],"name":"Zone1"},{"kind":"box","x":..,"y":..,"w":..,"h":..}],"grid":"base64-21x18"}` (정규화 좌표 0–1 권장; raw 픽셀이면 w/h로 환산) |
| `snapshot_path` | VARCHAR(512) NULL | 이벤트 스냅샷 상대경로(디스크 풀 기준). 없으면 재생시 세그먼트 프레임 추출 |
| `recording_id` | BIGINT NULL | 이 이벤트로 생성/연결된 클립(recordings.id). idx |
| `policy_action` | VARCHAR(16) NULL | 결정 결과 캐시: `record/discard/timelapse/notify_only` |
| `dedup_key` | VARCHAR(80) | `{camera_id}:{type}:{subtype}:{channel}` — active 병합·디바운스 키. idx `(dedup_key, state)` |
| `vendor_event_id` | VARCHAR(128) NULL | 벤더가 주는 고유 id(있으면 멱등 처리) |
| `raw` | JSON | 파싱 전/직후 원본(토픽/XML→dict, 디버깅·재처리용). MEDIUMTEXT 가능 |
| `created_at` | DATETIME(3) | 수신·삽입 시각(UTC) |
| `deleted_at` | DATETIME(3) NULL | 보존정리/수동삭제(soft). idx |

핵심 인덱스: `idx_cam_ts(camera_id, start_ts)`, `idx_type_ts(type, start_ts)`, `idx_dedup_state(dedup_key, state)`, `idx_recording(recording_id)`, `idx_active(state, start_ts)`(미종료 active 스윕용), `idx_deleted(deleted_at)`. 파티셔닝은 후속(월 RANGE) 고려.

### 4.2 `event_policies` — 카메라×이벤트타입 녹화/알림 정책

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `id` | BIGINT PK | Snowflake |
| `camera_id` | BIGINT NULL | NULL=전역 기본 정책(폴백). idx `(camera_id, event_type)` UNIQUE(soft-del 고려해 부분 unique 또는 앱 보장) |
| `event_type` | VARCHAR(32) | 정규화 타입 또는 `*`(해당 카메라 전체 폴백) |
| `subtype` | VARCHAR(48) NULL | 세분(예: line_crossing 중 특정 라인). NULL=type 전체 |
| `action` | VARCHAR(16) | `record` / `discard` / `timelapse` / `notify_only` |
| `pre_buffer_s` | SMALLINT | 전버퍼 초(캐시 잔존 상한 이내로 clamp) |
| `post_buffer_s` | SMALLINT | 후버퍼 초(이벤트 종료/펄스 후 추가 보존) |
| `cooldown_s` | SMALLINT | 동일 dedup_key 재트리거 억제 초(스팸/디바운스) |
| `min_score` | SMALLINT NULL | 이 점수 미만 이벤트 무시(노이즈 컷) |
| `retention_class` | VARCHAR(24) NULL | 생성 클립 보존등급(P2 보존정책 키). NULL=기본 |
| `notify` | BOOLEAN | action과 별개로 알림 발행 여부(record+notify 가능) |
| `active_schedule_id` | BIGINT NULL | 이 정책이 활성인 스케줄 윈도(없으면 항상). schedules.id |
| `enabled` | BOOLEAN default 1 | |
| 감사 | `created_at/updated_at/deleted_at/created_by_id/last_updated_by_id` | |

조회 우선순위(정책 해석, 6.7 결정엔진): `(camera_id, type, subtype)` > `(camera_id, type, NULL)` > `(camera_id, '*', NULL)` > `(NULL, type, NULL)` > `(NULL, '*', NULL)`.

### 4.3 `schedules` — 카메라별 녹화 스케줄(주간)

설계 선택: **요일×구간 룰 행** 방식(7×24 그리드를 룰로 압축; 분 해상도 지원, JSON 비대 회피, 부분수정 용이).

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `id` | BIGINT PK | Snowflake |
| `camera_id` | BIGINT | idx `(camera_id, day_of_week)` |
| `name` | VARCHAR(80) NULL | 프리셋명(여러 카메라 공유시 group_uuid로 묶기 가능) |
| `day_of_week` | TINYINT | 0=Mon … 6=Sun (KST 기준 해석) |
| `start_min` | SMALLINT | 자정 기준 분(0–1439, KST) |
| `end_min` | SMALLINT | 1–1440(1440=24:00). start<end 보장, 자정 넘김은 두 행으로 분할 |
| `mode` | VARCHAR(16) | `continuous`(상시) / `event`(이벤트전용) / `off`(녹화안함, 단 이벤트 알림은 정책 따름) / `motion_only`(이벤트 중 motion류만) |
| `priority` | SMALLINT default 0 | 구간 겹침 시 큰 값 우선(예외 구간) |
| `timezone` | VARCHAR(40) default `'Asia/Seoul'` | 해석 TZ(다지역 대비) |
| `enabled` | BOOLEAN default 1 | |
| `group_uuid` | VARCHAR(40) NULL | 동일 프리셋을 N카메라에 적용 시 묶음키 |
| 감사 | `created_at/updated_at/deleted_at/created_by_id/last_updated_by_id` | |

기본값: 카메라 생성 시(P1 시그널 수신) **24/7 continuous 1행** 또는 설정상 기본을 seeding(아래 7.3).

### 4.4 `timelapse_jobs` — 타임랩스 생성 작업

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `id` | BIGINT PK | Snowflake |
| `camera_id` | BIGINT | idx |
| `range_start_ts` / `range_end_ts` | DATETIME(3) | 소스 구간(UTC) |
| `source` | VARCHAR(16) | `range`(연속구간) / `events`(이벤트 묶음, event_ids) |
| `event_ids` | JSON NULL | source=events 시 대상 이벤트 |
| `speed_factor` | INT | 배속(예: 60 = 60배). 또는 `target_fps`+`sample_every` |
| `params` | JSON NULL | `{fps, scale, codec, sample_every_s}` |
| `status` | VARCHAR(16) | `queued/running/done/failed/canceled` |
| `progress` | SMALLINT | 0–100 |
| `celery_task_id` | VARCHAR(64) NULL | 취소·추적 |
| `output_path` | VARCHAR(512) NULL | 결과 mp4 경로 |
| `output_size` | BIGINT NULL | |
| `error` | VARCHAR(512) NULL | |
| `expires_at` | DATETIME(3) NULL | 산출물 보존 만료(임시물) |
| 감사 | `created_at/updated_at/deleted_at/created_by_id` | |

### 4.5 `event_outbox` — 알림/규칙 트리거 발행(P5 소비)

> in-process 시그널 + DB outbox 병행(시그널 유실/재시작 대비, at-least-once). P5가 폴링/구독해 처리·소거.

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `id` | BIGINT PK | Snowflake |
| `event_id` | BIGINT | events.id. idx |
| `camera_id` | BIGINT | idx |
| `event_type` | VARCHAR(32) | 빠른 필터 |
| `payload` | JSON | 직렬화된 이벤트 요약(P5가 추가 join 없이 처리) |
| `status` | VARCHAR(16) | `pending/consumed/failed`. idx `(status, created_at)` |
| `attempts` | SMALLINT default 0 | |
| `created_at` / `consumed_at` | DATETIME(3) | |

### 4.6 `camera_subscriptions` — 구독 상태(관측/제어, 선택)

> 구독 런타임 상태는 Redis(`axp:sub:{camera_id}` 해시: state, last_heartbeat_ts, renew_at_ts, fail_count, worker_id)로 다루고, **이 테이블은 영속 관측·UI 표기용 미러**(옵션). MVP는 Redis만으로도 가능하나, 재시작 후 마지막 상태·진단 로그를 위해 권장.

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `id` | BIGINT PK | |
| `camera_id` | BIGINT UNIQUE | |
| `protocol` | VARCHAR(16) | `onvif_pullpoint`/`onvif_base`/`isapi_alertstream`/`sunapi`/`none` |
| `state` | VARCHAR(16) | `connecting/active/degraded/stopped/error` |
| `last_event_ts` | DATETIME(3) NULL | 마지막 수신(하트비트 판단) |
| `renew_at_ts` | DATETIME(3) NULL | 다음 갱신 예정 |
| `fail_count` | SMALLINT | 연속 실패(백오프) |
| `last_error` | VARCHAR(512) NULL | |
| `updated_at` | DATETIME(3) | |

### 4.7 마이그레이션 SQL 스케치(MySQL 8, InnoDB/utf8mb4)

```sql
-- events ----------------------------------------------------------------
CREATE TABLE events (
  id              BIGINT       NOT NULL PRIMARY KEY,
  camera_id       BIGINT       NOT NULL,
  type            VARCHAR(32)  NOT NULL,
  subtype         VARCHAR(48)  NULL,
  state           TINYINT      NOT NULL DEFAULT 2,
  start_ts        DATETIME(3)  NOT NULL,
  end_ts          DATETIME(3)  NULL,
  duration_ms     INT          NULL,
  score           SMALLINT     NULL,
  source          VARCHAR(16)  NOT NULL,
  channel         SMALLINT     NULL,
  region          JSON         NULL,
  snapshot_path   VARCHAR(512) NULL,
  recording_id    BIGINT       NULL,
  policy_action   VARCHAR(16)  NULL,
  dedup_key       VARCHAR(80)  NOT NULL,
  vendor_event_id VARCHAR(128) NULL,
  raw             JSON         NULL,
  created_at      DATETIME(3)  NOT NULL,
  deleted_at      DATETIME(3)  NULL,
  INDEX idx_cam_ts (camera_id, start_ts),
  INDEX idx_type_ts (type, start_ts),
  INDEX idx_dedup_state (dedup_key, state),
  INDEX idx_recording (recording_id),
  INDEX idx_active (state, start_ts),
  INDEX idx_deleted (deleted_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- event_policies --------------------------------------------------------
CREATE TABLE event_policies (
  id                 BIGINT      NOT NULL PRIMARY KEY,
  camera_id          BIGINT      NULL,
  event_type         VARCHAR(32) NOT NULL,
  subtype            VARCHAR(48) NULL,
  action             VARCHAR(16) NOT NULL,
  pre_buffer_s       SMALLINT    NOT NULL DEFAULT 5,
  post_buffer_s      SMALLINT    NOT NULL DEFAULT 10,
  cooldown_s         SMALLINT    NOT NULL DEFAULT 10,
  min_score          SMALLINT    NULL,
  retention_class    VARCHAR(24) NULL,
  notify             TINYINT(1)  NOT NULL DEFAULT 1,
  active_schedule_id BIGINT      NULL,
  enabled            TINYINT(1)  NOT NULL DEFAULT 1,
  created_at         DATETIME(3) NOT NULL,
  updated_at         DATETIME(3) NOT NULL,
  deleted_at         DATETIME(3) NULL,
  created_by_id      BIGINT      NULL,
  last_updated_by_id BIGINT      NULL,
  INDEX idx_cam_type (camera_id, event_type),
  INDEX idx_deleted (deleted_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- schedules -------------------------------------------------------------
CREATE TABLE schedules (
  id                 BIGINT      NOT NULL PRIMARY KEY,
  camera_id          BIGINT      NOT NULL,
  name               VARCHAR(80) NULL,
  day_of_week        TINYINT     NOT NULL,
  start_min          SMALLINT    NOT NULL,
  end_min            SMALLINT    NOT NULL,
  mode               VARCHAR(16) NOT NULL,
  priority           SMALLINT    NOT NULL DEFAULT 0,
  timezone           VARCHAR(40) NOT NULL DEFAULT 'Asia/Seoul',
  enabled            TINYINT(1)  NOT NULL DEFAULT 1,
  group_uuid         VARCHAR(40) NULL,
  created_at         DATETIME(3) NOT NULL,
  updated_at         DATETIME(3) NOT NULL,
  deleted_at         DATETIME(3) NULL,
  created_by_id      BIGINT      NULL,
  last_updated_by_id BIGINT      NULL,
  INDEX idx_cam_dow (camera_id, day_of_week),
  INDEX idx_group (group_uuid),
  INDEX idx_deleted (deleted_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- timelapse_jobs --------------------------------------------------------
CREATE TABLE timelapse_jobs (
  id             BIGINT      NOT NULL PRIMARY KEY,
  camera_id      BIGINT      NOT NULL,
  range_start_ts DATETIME(3) NOT NULL,
  range_end_ts   DATETIME(3) NOT NULL,
  source         VARCHAR(16) NOT NULL,
  event_ids      JSON        NULL,
  speed_factor   INT         NOT NULL DEFAULT 60,
  params         JSON        NULL,
  status         VARCHAR(16) NOT NULL DEFAULT 'queued',
  progress       SMALLINT    NOT NULL DEFAULT 0,
  celery_task_id VARCHAR(64) NULL,
  output_path    VARCHAR(512) NULL,
  output_size    BIGINT      NULL,
  error          VARCHAR(512) NULL,
  expires_at     DATETIME(3) NULL,
  created_at     DATETIME(3) NOT NULL,
  updated_at     DATETIME(3) NOT NULL,
  deleted_at     DATETIME(3) NULL,
  created_by_id  BIGINT      NULL,
  INDEX idx_cam (camera_id),
  INDEX idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- event_outbox ----------------------------------------------------------
CREATE TABLE event_outbox (
  id          BIGINT      NOT NULL PRIMARY KEY,
  event_id    BIGINT      NOT NULL,
  camera_id   BIGINT      NOT NULL,
  event_type  VARCHAR(32) NOT NULL,
  payload     JSON        NOT NULL,
  status      VARCHAR(16) NOT NULL DEFAULT 'pending',
  attempts    SMALLINT    NOT NULL DEFAULT 0,
  created_at  DATETIME(3) NOT NULL,
  consumed_at DATETIME(3) NULL,
  INDEX idx_event (event_id),
  INDEX idx_cam (camera_id),
  INDEX idx_status_created (status, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- camera_subscriptions (optional mirror) --------------------------------
CREATE TABLE camera_subscriptions (
  id           BIGINT      NOT NULL PRIMARY KEY,
  camera_id    BIGINT      NOT NULL UNIQUE,
  protocol     VARCHAR(16) NOT NULL,
  state        VARCHAR(16) NOT NULL,
  last_event_ts DATETIME(3) NULL,
  renew_at_ts  DATETIME(3) NULL,
  fail_count   SMALLINT    NOT NULL DEFAULT 0,
  last_error   VARCHAR(512) NULL,
  updated_at   DATETIME(3) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

> **P2 `recordings` 영향**: `reason` enum에 `'event'`, `'schedule'` 값이 포함되어야 함(P2가 `continuous/manual` 정의). 미포함 시 P2 모델 변경 PR 필요 → 10절 Impact. P3는 신규 컬럼 추가 없이 P2의 recordings 생성 API만 사용.

---

## 5. 백엔드 설계

### 5.1 디렉터리 배치(PLAN 6장 구조 준수)

```
server/
├─ view/api/
│  ├─ event.py            # 이벤트 조회/필터/스냅샷/오버레이 메타
│  ├─ event_policy.py     # 정책 CRUD
│  ├─ schedule.py         # 녹화 스케줄 CRUD (주의: 카메라 녹화 스케줄. ams의 비행 schedule과 무관)
│  ├─ timelapse.py        # 타임랩스 작업 생성/상태/다운로드
│  └─ subscription.py     # (admin) 구독 상태 조회/강제 재구독
├─ controller/
│  ├─ event.py            # 조회·필터·정규화 결과 조립
│  ├─ event_policy.py
│  ├─ schedule.py
│  └─ timelapse.py
├─ service/
│  ├─ event_normalizer.py # 벤더 payload → 통일 Event dict (순수 함수, 매핑표)
│  ├─ event_pipeline.py   # 수신→디바운스/병합→정책결정→녹화호출→outbox (핵심)
│  ├─ event_policy_resolver.py # 정책 우선순위 해석 + 스케줄 결합
│  ├─ schedule_resolver.py     # (camera, ts)→mode 계산, 주간 그리드
│  └─ subscription_manager.py  # 구독 레지스트리/상태/Redis 미러
├─ driver/
│  ├─ onvif_event.py      # PullPoint/Base SOAP (PullMessages/Renew/Unsubscribe)
│  ├─ isapi_event.py      # alertStream(multipart) 스트리밍 파서
│  └─ sunapi_event.py     # SUNAPI attached/cgi 이벤트 취득
├─ task/list/
│  ├─ event_subscription.py  # per-camera 구독 워커(소프트 데몬) + 슈퍼바이저 beat
│  ├─ event_clip.py          # 전후버퍼 회수→recordings 생성/병합 (record action)
│  ├─ timelapse.py           # ffmpeg 타임랩스
│  ├─ event_snapshot.py      # 스냅샷 취득/세그먼트 프레임 추출 fallback
│  ├─ event_retention.py     # events soft-delete 정리(보존)
│  └─ active_event_sweeper.py# 끊긴 active 이벤트 강제 종료
└─ worker/                   # (P1/P2 소유) 변경 없음. 구독은 Celery 워커로.
```

### 5.2 API 표

> 공통: `/api/v1` prefix, `Authorization: Bearer`. 권한은 `@login_required` + `@permission_required('<perm>')`. 카메라 스코프 권한(특정 카메라만 접근)인 사용자는 응답에서 비인가 카메라 이벤트 제외(controller에서 허용 camera_id 집합 교집합). 페이지네이션 파라미터 ams 호환: `page, items_per_page, sort, order, q`.

| Method | Path | 권한 | 요청 | 응답(`data`) |
|---|---|---|---|---|
| GET | `/events` | `events:read` | query: `camera_id[]`, `type[]`, `subtype`, `start`(ms), `end`(ms), `min_score`, `has_recording`(bool), `state`, `page`, `items_per_page`, `sort=start_ts`, `order=desc`, `q` | `{count, items:[EventDTO]}` |
| GET | `/events/{id}` | `events:read` | — | `EventDTO`(region/raw 포함, raw는 admin만) |
| GET | `/events/{id}/snapshot` | `events:read` | — | `image/jpeg`(저장 스냅샷 or 세그먼트 추출 프레임, `Cache-Control: private`) |
| GET | `/events/{id}/overlay` | `events:read` | — | `{w,h,shapes:[...],ts_offset_ms}`(재생 오버레이용 정규화 메타) |
| GET | `/events/timeline` | `events:read` | `camera_id`, `start`, `end`, `bucket`(초, 마커 묶음), `type[]` | `{markers:[{ts,type,count,top_score,event_id}], coverage:[{start,end,reason}]}`(coverage=P2 녹화구간 병합) |
| POST | `/events/{id}/save` | `events:update` | `{lock:true, retention_class?}` | 연결 클립 보존 잠금(자동삭제 방지, 북마크). `EventDTO` |
| DELETE | `/events/{id}` | `events:delete` | — | soft delete. `{}` |
| GET | `/event-policies` | `policies:read` | `camera_id?` | `[EventPolicyDTO]`(전역+카메라 병합 뷰, 유효정책 미리보기 포함) |
| POST | `/event-policies` | `policies:update` | `EventPolicyInput` | 생성 `EventPolicyDTO` |
| PUT | `/event-policies/{id}` | `policies:update` | `EventPolicyInput` | 수정 |
| DELETE | `/event-policies/{id}` | `policies:update` | — | soft delete |
| POST | `/event-policies/resolve` | `policies:read` | `{camera_id, type, subtype?, at_ts?}` | 결정 미리보기 `{action, pre, post, schedule_mode, effective_source}` (디버그·UI 프리뷰) |
| GET | `/cameras/{id}/schedule` | `schedules:read` | — | `{rules:[ScheduleRuleDTO], grid:7x48or1440}`(그리드 파생 포함) |
| PUT | `/cameras/{id}/schedule` | `schedules:update` | `{rules:[...]}`(전체 치환) 또는 `{grid:[...]}` | 정규화·검증 후 저장. `{rules}` |
| POST | `/schedules/apply-group` | `schedules:update` | `{group_uuid?, rules, camera_ids[]}` | 다중 카메라 일괄 적용 |
| GET | `/timelapse` | `timelapse:read` | `camera_id?`, `status?`, paging | `{count, items:[TimelapseJobDTO]}` |
| POST | `/timelapse` | `timelapse:create` | `{camera_id, source, range_start, range_end, event_ids?, speed_factor, params?}` | `TimelapseJobDTO`(queued) |
| GET | `/timelapse/{id}` | `timelapse:read` | — | `TimelapseJobDTO`(progress) |
| GET | `/timelapse/{id}/download` | `timelapse:read` | — | `video/mp4`(done만, Range 지원; P2 다운로드 헬퍼 재사용) |
| POST | `/timelapse/{id}/cancel` | `timelapse:cancel` | — | Celery revoke + 상태=canceled |
| GET | `/subscriptions` | `admin` | — | `[SubscriptionDTO]`(상태/하트비트/오류) |
| POST | `/subscriptions/{camera_id}/resubscribe` | `admin` | — | 강제 재구독 트리거 |
| WS/SSE | `/events/stream` | `events:read` | (P0 WS 허브 채널 `events`) | 실시간 이벤트 push(라이브뷰 배지·타임라인 갱신). 카메라 스코프 필터링 |

권한 키 신설: `events:read/update/delete`, `policies:read/update`, `schedules:read/update`, `timelapse:read/create/cancel` — P0 권한맵(JSON)에 추가, admin은 전권. (PLAN §12.2 카탈로그 정렬, 10절 Impact.)

### 5.3 controller/service 책임 분리

- **view**: 파라미터 추출·검증(없으면 `ResponseBuilder.bad_request`), 권한·카메라 스코프 교집합, controller 호출, 예외→응답 매핑(`RowNotFoundException`→404 등 ams 패턴).
- **controller**: 트랜잭션 경계·DTO 조립. 무거운 작업은 Celery `.delay()`로 위임(전후버퍼 회수, 타임랩스, 스냅샷). 정책/스케줄 CRUD 검증.
- **service**:
  - `event_normalizer`: **순수 함수**(I/O 없음) — 벤더 raw → `NormalizedEvent`(dict). 테스트 용이.
  - `event_pipeline`: 수신 1건 처리 오케스트레이션(아래 5.6 의사코드). driver/normalizer/resolver/task/outbox 호출.
  - `event_policy_resolver`: 우선순위 정책 선택 + `schedule_resolver`로 현재 mode 결합 → 최종 action.
  - `schedule_resolver`: `(camera_id, ts)` → `continuous|event|motion_only|off`. 룰을 메모리 캐시(카메라별, 변경시 무효화).
  - `subscription_manager`: 카메라별 구독 메타 등록/상태전이, Redis 미러, capability 기반 protocol 선택.

### 5.4 driver 인터페이스(추상 + 벤더 구현)

```python
# driver/onvif_event.py / isapi_event.py / sunapi_event.py 공통 계약
class EventSource(Protocol):
    def open(self, camera: Camera) -> None: ...      # 구독/연결 수립(자격증명·세션)
    def poll(self, timeout_s: float) -> list[dict]:  # raw 이벤트 배치 반환(블로킹/롱폴)
        ...                                          #   onvif: PullMessages, isapi: 스트림 read,
                                                     #   sunapi: attached read/cgi poll
    def renew(self) -> None: ...                     # PullPoint 구독 갱신(onvif). 그 외 no-op/재연결
    def close(self) -> None: ...
    @property
    def needs_renew_at(self) -> int | None: ...      # UTC ms, onvif TerminationTime 기반
    @property
    def healthy(self) -> bool: ...                   # 마지막 수신/연결 상태
```

- P1 드라이버(인증·base url·암호화 자격증명 복호화)를 재사용/주입. 이벤트 드라이버는 그 위에 **이벤트 채널**만 추가.
- 모든 네트워크 호출 `timeout` 필수, 예외는 `sentry_sdk.capture_exception` 후 상위에서 백오프.

### 5.5 이벤트 구독 워커 설계 (Celery 기반 소프트 데몬)

**모델**: "카메라당 장수명 구독 루프"를 Celery 워커에서 운영. 두 가지 옵션 중 **A(전용 큐 장수명 태스크)** 채택, **B(slot 재무장)** 폴백.

- **슈퍼바이저(beat, `*/30s`)** `supervise_subscriptions`:
  1. `cameras` 중 event-capable(capabilities.event.supported && enabled && deleted_at NULL) 목록 로드.
  2. Redis `axp:sub:{camera_id}` 상태 점검: 없거나 `stopped/error` 또는 `last_heartbeat_ts`가 임계(예: 3×예상 하트비트) 초과 → `run_subscription.apply_async(args=[camera_id], queue='subs')`.
  3. capability 변경/자격증명 변경 시(P1 시그널 또는 버전 컬럼 비교) 기존 루프에 **중단 플래그**(Redis `axp:sub:{id}:stop=1`) 설정 → 재기동.
  4. 삭제/비활성 카메라 → 중단 플래그 + 정리.
- **구독 루프 태스크** `run_subscription(camera_id)` (`queue='subs'`, `acks_late`, `time_limit` 없음/매우 김, soft loop):
  ```
  drv = make_event_source(camera)        # protocol = capability 기반 선택
  drv.open()
  set redis state=active, worker_id, heartbeat
  while not stop_flag(camera_id):
      if drv.needs_renew_at and now >= renew_threshold: drv.renew()
      raw_batch = drv.poll(timeout_s=10)   # 롱폴/스트림 읽기(블로킹 상한 10s)
      heartbeat()                          # poll 반환마다 갱신
      for raw in raw_batch:
          event_pipeline.handle(camera, raw, source=protocol)   # 5.6
      if drv 연결 끊김/예외: break
  drv.close(); set state=stopped
  ```
  - **재구독/재연결**: 루프 탈출(예외/타임아웃/renew 실패) → 태스크 종료. 슈퍼바이저가 다음 주기에 재기동(지수 백오프: `fail_count`에 따라 `min(2^n, 60)s` 지연; Redis에 기록).
  - **하트비트**: poll 주기마다(이벤트 없어도 timeout 반환 시) Redis `last_heartbeat_ts` 갱신. ONVIF는 빈 PullMessages 응답, ISAPI는 keep-alive 경계/주기적 heartbeat 이벤트, SUNAPI는 폴 응답이 하트비트.
  - **단일성 보장**: `run_subscription` 진입 시 `SET axp:sub:{id}:lock worker_id NX EX 90`(워커별 lease, 주기 갱신)로 중복 루프 방지(워커 N대 환경).
  - **동시성**: `subs` 큐는 카메라 수만큼 동시 슬롯 필요 → Celery `-Q subs` 전용 워커 풀(`--concurrency`=카메라수 또는 gevent/eventlet로 I/O 다중화). go2rtc·녹화 큐와 **분리**해 상호 영향 차단.

> 대안(향후): 카메라 다수(>수십)·gevent 부적합 시, 구독을 **별도 경량 데몬 프로세스**(asyncio, `worker/event_subscriber/`)로 분리하고 Celery는 후처리만 담당. P3 MVP는 Celery `subs` 큐 + gevent 권장.

### 5.6 이벤트 처리 파이프라인 의사코드 (`event_pipeline.handle`)

```
# NOTE: 메모리/내부 연산은 epoch ms로 다루되, 저장 컬럼(events.*_ts/created_at 등)은 DATETIME(3) UTC.
def handle(camera, raw, source):
    n = event_normalizer.normalize(camera, raw, source)   # NormalizedEvent | None
    if n is None: return                                  # 무시 토픽(heartbeat 등)

    # 1) 멱등 (벤더 event id 있으면)
    if n.vendor_event_id and Event.exists(camera.id, n.vendor_event_id):
        return

    now = utc_ms()
    n.start_ts = n.ts if camera.trust_clock else now      # 6.6 시각 정책
    dedup = f"{camera.id}:{n.type}:{n.subtype}:{n.channel}"

    # 2) 상태머신: start / end / pulse
    if n.state == 'start':
        active = Event.get_active_by_dedup(dedup)
        if active:                                         # 중복 start → 갱신만
            active.touch(now); db.commit(); return
        ev = Event.create(camera, n, state=ACTIVE, dedup, source)
    elif n.state == 'end':
        ev = Event.get_active_by_dedup(dedup)
        if not ev:                                         # end만 옴 → 짧은 펄스로 합성
            ev = Event.create(camera, n, state=ENDED, dedup, source, start_ts=now)
        ev.close(end_ts=n.start_ts or now)                # duration 계산
    else:  # pulse
        ev = Event.create(camera, n, state=PULSE, dedup, source)

    # 3) 디바운스/쿨다운 (정책 cooldown_s)
    pol = event_policy_resolver.resolve(camera.id, n.type, n.subtype, at_ts=ev.start_ts)
    if pol is None or not pol.enabled: db.commit(); return
    if pol.min_score and (n.score or 0) < pol.min_score: db.commit(); return
    if within_cooldown(dedup, pol.cooldown_s):            # Redis last_trigger_ts
        ev.policy_action = 'discard(cooldown)'; db.commit(); return

    # 4) 스케줄 결합 (schedule_resolver) — 이미 resolve가 active_schedule + 글로벌 스케줄 반영
    mode = schedule_resolver.mode(camera.id, ev.start_ts)  # continuous/event/motion_only/off
    action = combine(pol.action, mode, n.type)             # 6.7 결합표

    ev.policy_action = action
    # 5) 액션 실행
    if action == 'record':
        # 클립 생성/병합은 Celery로 (전후버퍼 회수, I/O)
        event_clip.materialize.delay(ev.id, pol.pre_buffer_s, pol.post_buffer_s,
                                     pol.retention_class)
        mark_trigger(dedup)                                # 쿨다운 시작
    elif action == 'timelapse':
        # 구간 타임랩스 버킷에 적재(배치) 또는 즉시 작업
        timelapse_bucket.add(camera.id, ev)
    # discard/notify_only: 클립 없음

    # 6) 스냅샷 (옵션, 설정시) — 비동기
    if camera.event_snapshot_enabled and not n.snapshot_path:
        event_snapshot.capture.delay(ev.id)

    # 7) 알림/규칙 트리거 발행 (P5 소비) — outbox + in-proc 시그널 + WS push
    if pol.notify or action == 'notify_only':
        EventOutbox.create(ev)                             # at-least-once
        signals.event_created.send(ev.id)                  # in-process (P4/P5 훅)
        ws_hub.publish('events', ev.to_ws_dict(), scope=camera.id)
    db.commit()
```

전후버퍼 회수(`event_clip.materialize`) 의사코드:

```
# NOTE: 메모리/내부 연산은 epoch ms로 다루되, 저장 컬럼(events/recordings.*_ts)은 DATETIME(3) UTC.
def materialize(event_id, pre_s, post_s, retention_class):
    ev = Event.get(event_id)
    pre_s = min(pre_s, P2.cache_retention_s)               # 캐시 잔존 상한 clamp
    start = ev.start_ts - pre_s*1000
    # active면 아직 진행 — post는 종료 후 재호출 or 워치독으로 연장
    end = (ev.end_ts or now) + post_s*1000

    # 진행 중(active)이고 미종료면, 일단 start..now 구간 확보 + post 연장 스케줄
    segs = segment_indexer.find(ev.camera_id, start, end)  # P2 (캐시+레코드 디스크)
    if not segs:                                           # 캐시에 없음(전버퍼 초과/지연)
        rec = recordings.create_event(ev, segs=[], note='no_buffer'); return

    # 같은 카메라에서 [start,end]와 겹치는 reason=event recording 있으면 병합/확장
    existing = recordings.find_overlapping(ev.camera_id, start, end, reason='event')
    if existing:
        rec = recordings.extend(existing, start, end, segments=segs)
    else:
        rec = recordings.create_from_segments(
            camera=ev.camera_id, reason='event', segments=segs,
            start_ts=start, end_ts=end, retention_class=retention_class)
    ev.recording_id = rec.id; db.commit()
    # 썸네일/스냅샷 후속 (P2 thumbnail 재사용)
    thumbnail.generate.delay(rec.id)
```

> **핵심**: 전후버퍼는 **재인코딩 없이** P2 캐시/레코드 세그먼트를 `recordings`에 인덱싱(참조)하는 것. 실제 파일 이동/병합 정책은 P2 `recordings`(세그먼트 참조 vs copy)에 따른다. P2가 "recording = segment id 목록"이면 P3는 목록만 만들고 끝. "recording = 단일 mp4 concat"이면 `task.transcode`의 copy-concat 호출.

### 5.7 정책/스케줄 결합 결정엔진 (`combine`)

| pol.action \ schedule mode | continuous | event | motion_only | off |
|---|---|---|---|---|
| record (motion류) | record(이미 상시; 이벤트는 마킹/북마크) | record | record | discard(녹화 off; 단 notify는 별도) |
| record (line/intrusion/tamper/object) | record(이벤트 클립 별도 마킹) | record | discard | discard |
| timelapse | timelapse | timelapse | timelapse(motion만) | discard |
| notify_only | notify_only | notify_only | notify_only(motion만) | notify_only |
| discard | discard | discard | discard | discard |

- `continuous` 구간에서도 이벤트는 **마킹/북마크/알림**을 위해 `events`에 저장하고, 별도 event 클립을 만들지 않고 기존 연속 녹화에 **이벤트 마커**만 연결(중복 저장 회피, recording_id=현재 진행중 연속 recording). 단 보존등급 상향이 필요하면 해당 구간을 event retention으로 승격.
- `off` + notify_only/notify=true: 녹화 없이 알림만(현관 초인종류 활용).

---

## 6. 이벤트 수신·정규화

### 6.1 ONVIF (PullPoint 우선, Base 폴백)

표준 흐름(WS-BaseNotification / WS-Eventing, onvif-zeep):

1. **GetEventProperties** (선택) — 지원 토픽 트리·메시지 스키마 확인(P1 capability_probe가 이미 수행 가능, 결과 재사용).
2. **CreatePullPointSubscription** → 응답에서 `SubscriptionReference`(EndpointReference의 Address) + `CurrentTime` + `TerminationTime` 수신. 일부 기기는 `InitialTerminationTime`(예: `PT1H`) 지정 가능.
3. 루프: **PullMessages**(`Timeout`=PT10S, `MessageLimit`=N) → `NotificationMessage[]`. 각 메시지: `Topic`(예: `tns1:RuleEngine/CellMotionDetector/Motion`), `Message`(SimpleItem/ElementItem: `IsMotion`/`State`, `UtcTime`, `Source`(VideoSource/Rule 등), `Data`). 빈 응답 = 하트비트.
4. **Renew**(`TerminationTime`=PT1H 등)로 만료 전 갱신. 갱신 실패 시 재CreatePullPoint.
5. 종료 시 **Unsubscribe**.

세부:
- `SubscriptionReference` 주소가 상대/내부IP로 오는 기기 다수 → **호스트/포트를 카메라 host로 재작성**(P1과 동일 보정).
- 인증: WS-UsernameToken(Digest, nonce/created) 또는 HTTP Digest. 카메라 시간 동기 안 맞으면 UsernameToken nonce 거부 → P1 device GetSystemDateAndTime로 **시계 오프셋 보정** 후 created 생성.
- **Base Notification 폴백**: PullPoint 미지원 기기는 **Subscribe(콜백 주소)** 방식 → 서버가 수신 엔드포인트(`POST /onvif/notify/{camera_id}`, 내부 only/토큰)로 받아 같은 normalizer로 처리. 대부분 PullPoint 우선(NAT/방화벽 안전).
- Pull 메시지의 `PropertyOperation`(Initialized/Changed/Deleted) + `State`(true/false)로 **start/end** 판정.

### 6.2 Hikvision ISAPI (`alertStream`)

- **GET** `http://{host}/ISAPI/Event/notification/alertStream` (HTTP Digest 인증), 응답은 **`multipart/x-mixed-replace; boundary=...`** 장수명 스트림.
- 각 파트: 헤더(`Content-Type: application/xml` 또는 `text/plain`/`image/jpeg`(스냅샷 동봉 가능)) + 바디. 바디는 `<EventNotificationAlert>` XML:
  - `eventType`(예: `VMD`, `linedetection`, `fielddetection`(intrusion), `regionEntrance/Exiting`, `tamperdetection`, `shelteralarm`, `scenechangedetection`, `io`, `videoloss`, `facedetection`),
  - `eventState`(`active`/`inactive`), `eventDescription`, `channelID`/`dynChannelID`, `dateTime`(ISO8601, TZ 포함 가능), `activePostCount`(반복 active 카운트 = 진행중 펄스),
  - 룰 메타: `DetectionRegionList`/`detectionTarget`, 좌표(`RegionCoordinatesList`의 정규화 0–1000 좌표), 라인 정보.
- **파싱 전략**: 스트림을 boundary로 분할 → 멀티파트 reader. XML 파트는 `lxml`로 파싱. JPEG 파트가 오면 같은 이벤트의 스냅샷으로 임시 저장→`snapshot_path`.
- **start/end**: `eventState=active`(+`activePostCount` 증가) → start/진행, `inactive` → end. 일부 펌웨어는 active만 주기 송신(2초 간격) → **마지막 active 후 N초 무수신 = 종료**로 합성(active_event_sweeper).
- 연결 keep-alive: 서버 read timeout을 길게(예: 60s) + heartbeat 이벤트(`videoloss`/`IO` 없이 빈 keep-alive 라인) 처리. 끊기면 재연결.
- 멀티채널 NVR/카메라: `channelID`로 채널 분리(`events.channel`).

### 6.3 Hanwha SUNAPI

- 취득 방식(기기/펌웨어별 택1, capability_probe 결과로 결정):
  1. **이벤트 스트리밍(권장)**: `GET /stw-cgi/eventstatus.cgi?msubmenu=eventstatus&action=monitor` (또는 `attributes`/`check`) — 일부 모델은 멀티파트/롱폴 스트림으로 상태 변화 푸시.
  2. **폴링 폴백**: `GET /stw-cgi/eventstatus.cgi?...&action=check` 주기 호출로 현재 이벤트 비트맵 취득 → 직전과 diff하여 start/end 합성(주기 1–2s).
  3. **ONVIF 폴백**: SUNAPI 이벤트 미지원/제한 모델은 ONVIF PullPoint 사용(SUNAPI 카메라도 ONVIF 지원).
- 응답 키(예): 이벤트 종류별 채널/상태(`MotionDetection`, `Tampering`, `DefocusDetection`, `Shock`, `IVA`(line/intrusion/enter/exit/appear/disappear), `AudioDetection`, `SoundClassification`(P6), `Face`(P6)). IVA 룰은 룰 인덱스·좌표 포함.
- 인증: HTTP Digest. 좌표는 정규화/픽셀 혼재 → 모델별 보정표.

### 6.4 정규화 타입(통일 enum)

| 정규화 `type` | 의미 | 비고 |
|---|---|---|
| `motion` | 픽셀/셀 모션 | 가장 흔함, region grid 동반 가능 |
| `line_crossing` | 가상 라인 통과(트립와이어) | 방향(in/out) subtype |
| `intrusion` | 영역 침입/체류(field) | 들어옴/머무름 |
| `region_enter` / `region_exit` | 영역 진입/이탈 | line의 영역판 |
| `loitering` | 배회 | (지원 기기만; 고급은 P6) |
| `object_removed` / `object_left` | 사물 제거/방치 | |
| `tamper` | 탬퍼(가림/이동/디포커스) | defocus/scene_change 통합 |
| `audio` | 음성/소리 감지 | sound classification은 P6 |
| `io` | 디지털 입력(센서) | 도어/PIR 등 |
| `video_loss` / `video_blind` | 영상 끊김/가림 | 진단 |
| `object` | (P4) AI 객체(사람/차량 등) | P3는 타입만 예약, 적재는 P4 |
| `face` / `lpr` | (P6) | 예약 |

### 6.5 벤더 토픽 매핑표 (정규화 핵심)

> `event_normalizer`가 이 표(파이썬 dict) + 정규식으로 매핑. 매칭 실패 토픽은 `type='unknown'`로 저장(분석·확장용) 후 정책상 기본 discard.

| 정규화 type | ONVIF Topic (tns1/tnsaxis 등) | Hikvision `eventType` | Hanwha(SUNAPI/ONVIF) |
|---|---|---|---|
| `motion` | `RuleEngine/CellMotionDetector/Motion`, `VideoSource/MotionAlarm` | `VMD` | `MotionDetection` / ONVIF 동일 |
| `line_crossing` | `RuleEngine/LineDetector/Crossed`, `RuleEngine/TamperDetector`(X) | `linedetection` | IVA `PassLine`/`LineCrossing` |
| `intrusion` | `RuleEngine/FieldDetector/ObjectsInside`, `RuleEngine/IntrusionDetector` | `fielddetection` | IVA `IntrudedObject`/`Intrusion` |
| `region_enter` | `RuleEngine/FieldDetector/...Enter` | `regionEntrance` | IVA `Enter`/`Appear` |
| `region_exit` | `.../...Exit` | `regionExiting` | IVA `Exit`/`Disappear` |
| `tamper` | `RuleEngine/TamperDetector/Tamper`, `VideoSource/ImageTooBlurry`(defocus) | `tamperdetection`, `shelteralarm`, `scenechangedetection`, `defocus` | `Tampering`, `DefocusDetection` |
| `audio` | `AudioAnalytics/Audio/DetectedSound`, `AudioSource/AudioTooLoud` | `audioexception` | `AudioDetection` |
| `io` | `Device/Trigger/DigitalInput`, `Device/IO/...` | `IO`, `inputport` | `Alarm Input`/`DI` |
| `video_loss` | `VideoSource/SignalLoss`, `VideoSource/GlobalSceneChange` | `videoloss`, `videomismatch` | `VideoLoss` |
| `object_left`/`object_removed` | `RuleEngine/...ObjectLeft/Removed` | `unattendedBaggage`/`attendedBaggage` | IVA `Appear`/`Disappear`(룰의존) |
| `object`(P4) | `RuleEngine/MyRuleDetector/...`(메타데이터 분석) | `ANPR`/`facedetection`/스마트 이벤트 | DeepLearning IVA(객체 클래스) → P4에서 매핑 |

- 좌표/영역: 각 벤더 좌표계를 **정규화(0–1)** 로 변환해 `events.region.shapes`에 저장(렌더 시 영상 해상도와 무관하게 오버레이). Hikvision 0–1000, ONVIF NormalizedBounds(-1..1 또는 0..1), Hanwha 모델별 → 변환 유틸 `region_normalizer(vendor, raw, frame_w, frame_h)`.
- 방향/룰명: `subtype`에 벤더 룰명·라인명 보존(필터·오버레이 라벨).

### 6.6 시각(clock) 정책
- 카메라 시계 신뢰도 플래그 `camera.trust_clock`(P1 프로빙: NTP 동기 여부/서버와 오프셋<±2s면 true).
- `trust_clock=true`: 이벤트의 `UtcTime`/`dateTime`을 `start_ts`로 사용(전후버퍼 정밀).
- `false`: **서버 수신 시각**을 사용(전후버퍼는 캐시 기준이므로 서버 시각이 일관). raw에 카메라 시각 보존.
- 내부 비교/연산은 UTC(epoch ms), 저장은 UTC `DATETIME(3)`. 표시·스케줄 해석만 KST(또는 `schedules.timezone`).

### 6.7 중복/노이즈 억제(요약)
- `dedup_key`로 active 1건 유지(start 중복 흡수).
- `cooldown_s`로 동일 키 재트리거 억제(record 액션 한정; 알림은 별도 throttle).
- `active_event_sweeper`(beat `*/30s`): `state=active`이고 `start_ts < now - max_active_age`(타입별, 예 motion 30s·intrusion 120s·기본 60s)인 이벤트 강제 `end`(end_ts=last_seen). ISAPI active-only/연결 끊김 보정.
- 폭주 방어: 카메라당 분당 이벤트 상한(Redis 토큰버킷) 초과 시 샘플링+`degraded` 표기, raw는 카운트만.

---

## 7. 스마트/스케줄 녹화

### 7.1 이벤트 정책(요약 위 4.2/5.7)
- UI에서 카메라별 타입×action 매트릭스 편집(pre/post/cooldown/min_score/retention/notify). 전역 기본 + 카메라 오버라이드.

### 7.2 전·후 버퍼 (P2 캐시 활용)
- **전버퍼**: 이벤트 시각 − pre_s. P2 캐시 디스크에 항상 도는 세그먼트에서 회수. **상한 = 캐시 잔존시간**(예: 캐시가 60s만 보관하면 pre_s≤60). UI에서 clamp + 경고.
- **후버퍼**: 이벤트 종료(또는 펄스) + post_s. active 이벤트는 **종료 시점에 post 연장 재계산**(워치독: 진행 중 클립은 now까지 잠정, 종료 신호 또는 sweeper 종료 후 확정).
- 클립 = P2 `recordings(reason='event')`로 세그먼트 인덱싱. 재인코딩 없음.

### 7.3 스케줄(주간) 결합
- `schedule_resolver.mode(camera, ts)`: ts(KST 변환)→요일·분 → 적용 룰 중 `priority` 최댓값 → mode. 룰 없음=기본(`continuous` 또는 설정).
- 카메라 생성 시(P1 시그널) 기본 스케줄 seeding(설정 `default_schedule_mode`, 기본 `continuous` 24/7). 변경은 `PUT /cameras/{id}/schedule`로 전체 치환(검증: 겹침 허용+priority, 0–1440 범위, 자정 넘김 분할).
- 연속 녹화 자체(reason='continuous')는 **P2 레코더 슈퍼바이저**가 수행 — P3 스케줄은 "이 구간 연속 켜라/꺼라"를 **P2에 지시**(P2 레코더가 schedule_resolver를 참조하거나, P3가 P2 supervisor에 enable/disable 시그널). 결합점은 10절 Impact에 명시(권장: P2 레코더가 P3 `schedule_resolver`를 import해 구간별 on/off).

### 7.4 모션/구역 오버레이
- 정규화 region(0–1 좌표 shapes)을 `events.region`에 저장.
- 재생 시 `GET /events/{id}/overlay` → 프론트가 video 위에 SVG/Canvas로 폴리곤/박스/라인 렌더(해상도 독립). 라벨=subtype/룰명, 색=타입.
- 모션 grid(셀 비트맵)는 base64로 저장, 오버레이 시 반투명 히트맵. AI 박스(P4)는 같은 오버레이 레이어에 다른 색으로 합류.

### 7.5 타임랩스 (ffmpeg)
- `task.timelapse`(Celery): 소스 세그먼트(P2 segment_indexer로 구간/이벤트 묶음→세그먼트 목록) → ffmpeg.
  - 방식 A(프레임 샘플링): `-vf "select='not(mod(n,K))',setpts=N/FRAME_RATE/TB"` 또는 `fps` 필터로 다운샘플 후 인코드.
  - 방식 B(구간 concat 후 setpts): 세그먼트 concat(demuxer) → `setpts=PTS/{speed}` → libx264(crf, preset) 인코드.
  - 이벤트 묶음: 각 이벤트 ±패딩 구간만 추출·concat → 압축 타임랩스(하이라이트).
- 진행률: ffmpeg `-progress` 파이프 파싱 → `timelapse_jobs.progress` 갱신. 취소: Celery revoke + 프로세스 종료.
- 산출물 디스크: P2 storage_manager로 record/temp 풀에 기록, `expires_at`로 자동정리(`event_retention`/P2 retention 연계).

---

## 8. 프론트엔드 (TS) — DESIGN.md 적용

> React 18 + Vite 7 + TS + Tailwind + Radix/shadcn + TanStack Query/Table + dnd-kit. ams 패턴(페이지별 디렉터리, `@`=`src/`, Axios+JWT 인터셉터, i18n ko/en). 디자인은 **Tesla 미니멀**: 흰 캔버스/사진 우선/그림자·그라데이션·테두리 지양, 단일 액센트 **Electric Blue `#3E6AE1`**(주 CTA·활성 상태), 4px 라운드, 0.33s 트랜지션, 텍스트 Carbon Dark `#171A20`/Graphite `#393C41`/Pewter `#5C5E62`. **이벤트는 사진/영상이 주인공**이므로 이벤트 카드/타임라인은 스냅샷 썸네일을 전면에 두고 UI 크롬은 최소화.

페이지/컴포넌트 (`frontend/src/pages/events/`, `.../cameras/schedule/`, 공용 `components/`):

### 8.1 `EventTimeline`
- 가로 시간축 레인(카메라별 행 또는 단일 카메라 확대). 상단 날짜/줌(시/일), 좌우 스크롤.
- **coverage 바**(연속/이벤트 녹화 구간) = 얕은 회색(`#EEEEEE`) 바, 이벤트 마커 = 작은 점/세로 틱(타입별 색은 절제: 기본 Carbon, 활성/선택 시 Electric Blue). Unch 그림자 없음.
- 마커 클릭 → 클립 재생(아래 player). hover 시 미니 스냅샷 미리보기(사진 우선). 밀집 구간은 `bucket`으로 묶어 개수 배지.
- `GET /events/timeline` + 가상 스크롤(대량). TanStack Query 캐싱.

### 8.2 `EventFilter`
- 좌측/상단 필터 패널: 카메라 멀티선택, 타입 토글 칩(motion/line/intrusion/tamper/...), 기간(프리셋: 1h/24h/7d/커스텀), min_score 슬라이더, "녹화있음만" 토글, 검색어.
- 디자인: 흰 배경, 칩은 4px 라운드·테두리 대신 배경 톤(선택=Electric Blue 텍스트/연한 blue 배경). 결과는 카드 그리드 또는 타임라인에 반영.
- URL 쿼리 동기화(공유·새로고침 유지).

### 8.3 이벤트 목록/재생 (`EventList` + `EventPlayer` with `MotionOverlay`)
- 이벤트 카드: **스냅샷 썸네일 전면**(2:1 비율, 12px 라운드, overflow hidden — DESIGN 카드 규칙), 좌상단 타입/시각 라벨(흰 텍스트, 그림자 없이 이미지 어둠에 의존), 우측 작은 점수/카메라명.
- 클릭 → `EventPlayer`: P2 playback 클립 플레이어 재사용(WebRTC/MSE/HLS 또는 mp4 Range). 재생 위에 **`MotionOverlay`**(절대배치 SVG/Canvas): `GET /events/{id}/overlay`의 shapes를 video 실제 표시 영역에 맞춰 스케일(ResizeObserver). 폴리곤=반투명 채움 + Electric Blue 외곽선, 박스/라인 동일 팔레트, 라벨 칩.
- 액션: 다운로드(P2), 북마크/보존잠금(`POST /events/{id}/save`), 삭제.

### 8.4 `ScheduleEditor` (카메라 녹화 스케줄)
- 7행(요일)×시간 그리드(15분 또는 1시간 셀). 셀을 드래그로 칠하며 mode 지정(continuous=Electric Blue, event=연한 blue/회색, motion_only=점선 톤, off=흰색). dnd-kit/포인터 드래그 페인팅.
- 모드 팔레트(상단), 프리셋 저장/불러오기(`group_uuid`), 다중 카메라 적용(`POST /schedules/apply-group`).
- 저장 시 그리드→룰 압축(연속 동일 셀 병합) 후 `PUT`. 디자인: 테두리 최소, 셀 간 1px 구분(`#EEEEEE`), 라운드 없음(그리드), 트랜지션 0.33s.

### 8.5 `EventPolicyMatrix`
- 카메라 선택 → 타입(행)×설정(action 드롭다운, pre/post/cooldown 숫자, min_score, notify 토글) 테이블(TanStack Table). 전역 기본 vs 오버라이드 시각 구분(오버라이드 셀만 Electric Blue 점). "유효정책 미리보기"는 `/event-policies/resolve` 호출.

### 8.6 `TimelapsePanel`
- 구간/이벤트 선택(타임라인 범위 드래그 or 이벤트 다중선택) → 배속/품질 선택 → 생성. 진행률 바(Electric Blue), 완료 시 다운로드 버튼. 작업 목록(상태/진행률) 테이블.

### 8.7 실시간/알림 표시
- P0 WS 허브 `events` 채널 구독 → 라이브뷰 카메라 타일에 이벤트 펄스 배지(타입 점), 이벤트 페이지 상단 토스트(sonner). 절제된 단색, 점멸 대신 0.33s 페이드.

### 8.8 i18n/접근성
- 모든 라벨 ko/en(react-intl). 타입·action 라벨 매핑. 시각은 KST 표시(저장 UTC `DATETIME(3)`→API epoch ms→KST 포맷). 터치 타깃 ≥44px, 키보드 내비.

---

## 9. 작업 분해 (순서 있는 체크리스트)

1. **선행 계약 확정(블로킹)**: P2 캐시 잔존시간·segment_indexer·recordings 생성/병합/overlap API, playback 타임라인 스키마; P1 capability event 토픽 형식. (없으면 14절·AskUserQuestion.)
2. **모델/마이그레이션**: `events/event_policies/schedules/timelapse_jobs/event_outbox/(camera_subscriptions)` + `recordings.reason` enum 확장(P2 협의). SQL 산출.
3. **정규화 코어**: `service/event_normalizer.py` + 매핑표 + `region_normalizer` (순수함수, unit test 먼저).
4. **드라이버**: `driver/onvif_event.py`(PullPoint/Base) → `isapi_event.py`(alertStream multipart) → `sunapi_event.py`(stream/poll/onvif fallback). 각자 `EventSource` 계약. 시뮬레이터/녹화 fixture로 테스트.
5. **파이프라인**: `service/event_pipeline.py`(상태머신·dedup·cooldown), `event_policy_resolver`, `schedule_resolver`.
6. **구독 워커**: `task/event_subscription.py`(`run_subscription` + `supervise_subscriptions` beat), Redis 상태/락/하트비트, 백오프, `subs` 큐 구성(celeryconfig). `active_event_sweeper`.
7. **녹화 연동**: `task/event_clip.py`(전후버퍼 회수·병합), `event_snapshot.py`(스냅샷/프레임 추출).
8. **스케줄↔P2 연동**: P2 레코더가 `schedule_resolver` 참조하도록 결합(또는 enable/disable 시그널). 기본 스케줄 seeding.
9. **API/컨트롤러**: event/event_policy/schedule/timelapse/subscription view+controller, 권한키 추가(P0 권한맵), Blueprint 등록.
10. **타임랩스**: `task/timelapse.py`(ffmpeg, 진행률, 취소).
11. **outbox/시그널**: `event_outbox` 발행 + `signals.event_created` + WS push(P5/P4 훅 지점).
12. **프론트**: EventTimeline → EventFilter → EventList/Player+MotionOverlay → ScheduleEditor → EventPolicyMatrix → TimelapsePanel → 실시간 배지. i18n.
13. **보존**: `event_retention`(events soft-delete/raw 정리), 타임랩스 산출물 만료 정리(P2 retention 연계).
14. **테스트 전수**: unit/integration/e2e(12절), 회귀(P1 카메라/P2 녹화·재생 영향 점검).
15. **문서 갱신**: 본 문서 14절 해소분 PLAN 반영, 10절 Impact 확정.

---

## 10. 다른 기능/Phase에 미치는 영향 (Cross-feature Impact) ★

| 대상 | 영향 | 조치 |
|---|---|---|
| **P2 `recordings`** | `reason` enum에 `'event'`,`'schedule'` 필요. 세그먼트 인덱싱/병합/overlap-find API를 P3가 호출 | P2와 enum·API 시그니처 합의. 없으면 P2 소규모 PR(컬럼 X, 값만). 병합(extend) 미지원 시 P3가 별 클립 생성+coalesce 로직 보유 |
| **P2 캐시 디스크** | 전버퍼 상한 = 캐시 잔존시간. 캐시 보관시간 변경이 pre_buffer clamp에 직접 영향 | 설정값을 P3 resolver가 읽어 clamp. 캐시 축소 시 정책 경고 |
| **P2 레코더 슈퍼바이저** | 스케줄(continuous/off)이 연속 녹화 on/off를 좌우 | **결합점 결정 필요**(14절 Q1): (a) P2 레코더가 `schedule_resolver` import (권장) (b) P3가 P2에 enable/disable 시그널 |
| **P2 playback/타임라인** | 이벤트 마커·coverage를 타임라인에 합성. P3 `/events/timeline`이 P2 녹화구간을 포함 | P2 타임라인 응답 스키마 재사용/확장. 프론트 타임라인 컴포넌트 공유 가능 |
| **P1 cameras/capabilities** | 이벤트 지원여부·토픽·trust_clock·protocol 선택 근거. credential/capability 변경 시 재구독 | P1 capability_probe 결과 스키마에 event 토픽·protocol 포함 확인. 카메라 CRUD 시그널 구독 |
| **P1 드라이버(auth/session)** | 이벤트 드라이버가 P1 인증·base url·복호화 재사용 | 공통 클라이언트 주입, 중복 구현 금지 |
| **P0 권한맵(JSON)** | `event/policy/schedule/timelapse` 권한키 신설 | P0 권한 정의·UI 권한 편집에 키 추가, admin 전권 |
| **P0 WS 허브** | `events` 채널 추가(실시간 푸시), 카메라 스코프 필터 | 허브에 채널·스코프 필터 등록 |
| **P0 Celery/큐** | `subs` 전용 큐(장수명 구독) + 후처리 큐 분리, gevent/concurrency | docker-compose `axp-worker`에 subs 워커 추가(또는 별도 서비스) |
| **P4 AI** | `object` 정규화 타입·`events`·`detections` 링크·`signals.event_created` 훅. 서버측 모션 stub | P3가 모델·시그널·타입 예약 제공. P4가 detection→events 연결, 서버 모션 구현 |
| **P5 자동화/알림** | `event_outbox`·시그널을 트리거로 소비. notify_only/notify 플래그 | P3는 발행만, 실제 채널 전송·규칙 평가는 P5. 페이로드 스키마 합의 |
| **P6** | LPR/face/audio classification 타입 예약(`face/lpr`) | enum 자리만, 구현 P6 |
| **보존정책** | `events` 대량 증가(고빈도). retention/파티셔닝 부담 | `event_retention` + 인덱스/파티션 설계, raw 보관기간 분리 |

---

## 11. 리스크 & 완화

| 리스크 | 영향 | 완화 |
|---|---|---|
| 벤더 펌웨어/모델별 이벤트 스키마·좌표·동작 편차 큼 | 정규화 누락·오매핑 | 매핑표 + `unknown` fallback 저장, raw 보존으로 사후 매핑/재처리, 모델별 회귀 fixture |
| ISAPI active-only(종료 미통지)·연결 끊김 | active 이벤트 미종료·중복 | sweeper로 강제 종료, dedup 병합, 재연결 백오프 |
| ONVIF 시계 불일치 → 인증/시각 오류 | 구독 실패·전후버퍼 부정확 | clock 오프셋 보정, `trust_clock`로 서버 시각 폴백 |
| 카메라 다수 시 장수명 구독 동시성 | Celery 워커 점유·블로킹 | `subs` 전용 큐 + gevent I/O 다중화, lease 락 단일성, 필요시 별도 데몬 분리 |
| 캐시 잔존 < pre_buffer | 전버퍼 부족 | clamp + UI 경고, "no_buffer" 마킹 |
| 이벤트 폭주(노이즈/탬퍼 반복) | DB·녹화·알림 폭주 | cooldown, min_score, 토큰버킷 rate limit, degraded 표기 |
| `events` 테이블 급팽창 | 쿼리·스토리지 부담 | 인덱스 신중·월 파티셔닝, raw 분리 보관/조기 정리, soft-del 배치 |
| 전후버퍼/타임랩스 ffmpeg 부하 | CPU·디스크 | copy 우선(전후버퍼 무재인코딩), 타임랩스만 인코딩+동시성 제한 큐 |
| 자격증명 평문 노출 | 보안 | P0 암호화 저장만 사용, 로그/raw에서 비밀 마스킹, API 응답에 자격증명·내부URL 미노출 |
| Base Notification 콜백 수신 엔드포인트 | SSRF/위조 | 내부망 only + 카메라별 토큰 경로, 출처 IP 검증 |

---

## 12. 테스트 계획 (unit/integration/e2e)

**Unit**
- `event_normalizer`: 벤더별 raw(저장된 실제 PullMessages XML / alertStream 멀티파트 / SUNAPI 응답 fixture) → 기대 NormalizedEvent. start/end/pulse, 좌표 정규화, unknown 처리.
- `region_normalizer`: Hikvision 0–1000 / ONVIF / Hanwha → 0–1 변환 경계값.
- `event_policy_resolver`: 우선순위(카메라>전역, subtype>type>*) 선택.
- `schedule_resolver`: 요일·분 경계, 자정 넘김 분할, priority 겹침, TZ 변환(KST).
- `combine`: 정책×스케줄 결정표 전 케이스.
- 디바운스/cooldown/sweeper 시각 로직.

**Integration (DB+Celery eager + mock driver)**
- 파이프라인 end-to-end(mock EventSource가 start→end 시퀀스 주입) → `events` 적재·병합·`event_clip` 호출·`recordings(reason='event')` 생성(P2 segment_indexer mock)·`event_outbox` 발행.
- 구독 워커 수명주기: 기동→하트비트→renew→강제 stop→슈퍼바이저 재기동(Redis 상태 검증), 백오프.
- 전후버퍼: 캐시 세그먼트 mock에서 pre/post 회수·clamp·overlap 병합·no_buffer.
- 스케줄 CRUD↔resolver, 정책 CRUD↔resolve API.
- 타임랩스: 작은 fixture 세그먼트로 ffmpeg 실행(또는 ffmpeg mock) → 산출물·진행률·취소.

**e2e (프론트+백엔드, Playwright)**
- 이벤트 필터→타임라인 마커→클립 재생→모션 오버레이 표시(좌표 스케일 검증) 1 시나리오 그린.
- ScheduleEditor 그리드 페인팅→저장→resolver 반영.
- 타임랩스 생성→진행률→다운로드.

**회귀**: P1 카메라 온보딩/라이브, P2 녹화/연속/재생/다운로드/보존이 P3 도입 후 정상(특히 P2 레코더-스케줄 결합, recordings reason 변경).

---

## 13. 성능·보안 체크포인트

**성능**
- `events` 쓰기 고빈도: 배치 commit(파이프라인 1건씩이나 워커별 짧은 트랜잭션), 불필요 FK/JOIN 없음(논리 참조+인덱스), `selectinload`로 N+1 회피(목록 DTO).
- 전후버퍼는 **무재인코딩**(세그먼트 인덱싱). 타임랩스만 인코딩, 동시성 제한 큐.
- 구독은 `subs` 전용 큐 + I/O 다중화, 녹화/AI 큐와 격리(상호 영향 차단).
- 타임라인/필터 쿼리는 `(camera_id,start_ts)`/`(type,start_ts)` 인덱스 사용, 기간 상한·페이지네이션 강제, 마커는 bucket 집계.
- Redis로 dedup/cooldown/rate limit/heartbeat(DB 부하 회피).

**보안**
- 모든 API `@login_required`+세부 권한, **카메라 스코프 교집합**으로 비인가 카메라 이벤트/스냅샷 차단.
- 스냅샷·클립·타임랩스 다운로드는 해당 카메라 권한 확인 후 제공(직접 경로 노출 금지, 서버 프록시).
- 자격증명: P0 암호화 저장만 사용, 복호화는 메모리 한정, 로그/`raw`/응답에서 비밀·내부 URL 마스킹.
- Base Notification/SSE 등 수신 엔드포인트: 내부망 only + 토큰 경로 + 출처 검증(SSRF/위조 방지).
- 입력 검증(기간·페이지·enum 화이트리스트), XML 파싱은 외부 엔티티 비활성(XXE 방지, `lxml` resolve_entities=False).
- 패키지 최신 stable(onvif-zeep/lxml/requests), 알려진 취약점 점검.
- 감사: 정책/스케줄 변경 `created_by/last_updated_by` + audit_logs.

---

## 14. 미해결 질문 / 결정 필요 사항

- **Q1. 스케줄↔연속녹화 결합점**: (a) P2 레코더가 P3 `schedule_resolver`를 직접 참조(권장, 단일 진실원) vs (b) P3가 P2 레코더 슈퍼바이저에 enable/disable 시그널. → P2 소유자와 합의 필요.
- **Q2. `recordings.reason` 확장 주체**: P2가 enum에 `event/schedule` 포함하는지, 아니면 P3가 별도 마킹 컬럼? (권장: P2 enum 확장.)
- **Q3. 클립 실체**: P2 `recordings`가 "세그먼트 id 목록 참조"인지 "단일 mp4 concat"인지에 따라 전후버퍼 materialize 구현이 달라짐. (권장: 참조 방식, 무재인코딩.)
- **Q4. 구독 실행체**: Celery `subs` 큐(gevent)로 충분한 카메라 규모 상한? 초과 시 별도 asyncio 데몬(`worker/event_subscriber/`)으로 분리할 임계 카메라수.
- **Q5. SUNAPI 이벤트 1차 취득 방식**: 타깃 Hanwha 모델군에서 eventstatus 스트리밍 지원 여부(아니면 폴링/ONVIF). 실기기 확인 필요.
- **Q6. ONVIF Base Notification 콜백 지원 여부**: PullPoint 미지원 기기 대상으로 콜백 수신 엔드포인트를 P3에서 열지(보안·NAT 고려) vs PullPoint 전용으로 한정.
- **Q7. `events` 보존정책**: raw 보관기간(예 7d) vs 이벤트 메타 보관기간(예 90d) 분리값, 파티셔닝 도입 시점.
- **Q8. 전버퍼 상한(캐시 잔존시간) 기본값**: P2 캐시 보관시간 기본값 확정 → pre_buffer clamp 상한.
- **Q9. 멀티채널/멀티센서 카메라**: `events.channel` 단위 정책/스케줄을 카메라 단위로 둘지 채널 단위로 확장할지.

> 확정 시 본 문서 해당 절 + `../PLAN.md`(필요 시 7장 데이터 모델·9장 로드맵)에 반영.

### 14.1 구현 시 채택한 결정 (2026-06-05, P3 구현)
- **Q1. 스케줄↔연속녹화 결합**: (a) **P2 레코더가 `schedule_resolver`를 직접 참조**(단일 진실원). `worker/recorder/supervisor.py::_desired_cameras()`가 continuous-policy 카메라를 `schedule_resolver.mode(cid, now)=='off'`면 제외. 강제/진행중 `recordings`(manual/event)는 항상 우선(override).
- **Q2. `recordings.reason` 확장**: **P2 enum 확장 채택** — `REASON_EVENT='event'`, `REASON_SCHEDULE='schedule'` 추가. 별도 마킹 컬럼 없음.
- **Q3. 클립 실체**: **참조 방식·무재인코딩**. 이벤트 클립 = `Recording(reason=event, retention_class=event)`을 `[start-pre, end+post]` 구간에 생성 → 해당 구간 세그먼트를 retention_engine이 보호. 겹치면 `find_overlapping`+`extend`로 **coalesce**(별 클립 난립 방지). pre는 `cache_buffer_seconds`로 clamp.
- **Q4. 구독 실행체**: Celery 일반 워커 + **`supervise_subscriptions` beat(30s)**가 event-capable 카메라별 `run_subscription` 장수명 태스크 보장(Redis lease/heartbeat). 이벤트 지원 카메라 0이면 no-op. 임계 카메라수 초과 시 별도 asyncio 데몬(`worker/event_subscriber/`) 분리는 후속.
- **Q5. SUNAPI 취득**: `eventstatus` 스트리밍 우선, 실패 시 폴링/ONVIF fallback. `sunapi_event.diff_status`로 상태 전이만 이벤트화(테스트 가능 순수함수).
- **Q6. ONVIF 콜백**: **PullPoint 전용**. Base Notification 콜백 수신 엔드포인트는 보안(SSRF/위조)·NAT 고려해 **미개방**(후속, 내부망+토큰 경로 한정 시 재검토).
- **Q7. `events` 보존**: `cleanup_events`(daily 04:00) — raw 페이로드 조기 정리 + 메타 보관기간 분리(기본 raw 7d / 메타 90d, 설정화 후속), soft-delete 배치. 월 파티셔닝은 임계 도달 시(후속).
- **Q8. 전버퍼 상한**: P2 `storage_policies.cache_buffer_seconds`(기본 **60s**)를 `event_clip.materialize`가 읽어 `pre_s=min(pre_buffer_s, cache_seconds)` clamp.
- **Q9. 멀티채널**: MVP **카메라 단위 정책/스케줄**. `events.channel`은 정규화·기록만(dedup 키에 포함). 채널 단위 정책/스케줄 확장은 후속.
- **이벤트 수신 시각(§6.6)**: `trust_clock=false` 기본 — `start_ts=utcnow()`(서버 수신 시각)로 P2 캐시(컨테이너 UTC)와 정합 → 전후버퍼 회수 정확. 카메라 시각은 `raw`에 보존.
- **권한키**: `events`(read/update/delete), `policies`(read/update), `schedules`(read/update), `timelapse`(read/create/cancel) 신설(P0 카탈로그). 카메라 스코프 교집합으로 비인가 카메라 이벤트/스냅샷/클립 차단(superuser 우회).
- **기본 정책 seeding**: 전역 `motion→record`(pre5/post10/cooldown10/notify) + 전역 `*→notify_only`. `seed()` 멱등(전역 정책 부재 시만).
- **카메라 DTO**: `camera.to_dict`에 `id`(numeric, str) 추가 — 프론트가 이벤트(`camera_id` numeric)와 카메라를 조인하는 키(타 DTO와 일관).

### 14.2 검증 메모
실카메라 부재 → 드라이버/정규화는 **픽스처 unit 테스트**(ISAPI alertStream 멀티파트·ONVIF PullMessages·SUNAPI eventstatus → NormalizedEvent, region 0–1 변환). 파이프라인(상태머신/dedup/cooldown/min_score)·resolver(스케줄 KST 요일·자정넘김·priority, 정책 specificity)·`combine` 결정표·API(simulate→이벤트→클립, 스코프 필터, 정책·스케줄·타임랩스 CRUD)는 **integration 테스트**(SQLite+fakeredis). 이벤트→클립→재생·스케줄·타임랩스는 **go2rtc `exec:ffmpeg` 합성 패턴**으로 e2e 검증: `simulate(motion+region)` → `recordings(reason=event)` 생성 → 이벤트 목록/타임라인 마커·coverage/오버레이(0–1 폴리곤)/클립 세그먼트 재생 → 스케줄 off 페인팅→resolver `off`→`combine=discard` → 타임랩스 생성→완료→mp4 다운로드(`tests/_p3_event_check.py`, **18 checks green**). **backend pytest 146 passed**, 프론트 `tsc --noEmit`/`vite build` 무에러.
