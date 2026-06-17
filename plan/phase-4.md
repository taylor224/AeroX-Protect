# Phase 4 — AI 객체인식 + 검색

> 마스터 플랜: [`../PLAN.md`](../PLAN.md) · 디자인: [`../DESIGN.md`](../DESIGN.md) · 선행: [`phase-1.md`](phase-1.md)(카메라/streams/go2rtc), [`phase-2.md`](phase-2.md)(segments·recordings·playback·storage), [`phase-3.md`](phase-3.md)(events·event_pipeline·signals·event_outbox).
> **구현 전 본 문서 + PLAN.md를 읽고 "10. Cross-feature Impact" 절을 반드시 확인·갱신**한다. 네임스페이스 `axp`, Flask MVC(view→controller→service/driver→model), Celery+Redis, 응답은 `ResponseBuilder`. 저장 타임스탬프는 **UTC `DATETIME(3)` 저장 / API epoch ms·ISO 직렬화 / 표시 KST**(PLAN §12.1). 단, 노드↔서버 JSON 보고의 `ts`(epoch ms 전송)는 전송 포맷이므로 유지 — DB 컬럼만 `DATETIME(3)`. PK는 Snowflake BIGINT, soft delete + 감사 컬럼(공통 mixin). 대량·고빈도 테이블은 **FK 미설정**(논리참조 + 인덱스).
> 레퍼런스 코드: `../ams-front/worker/runway_monitor/`(pipeline/detector/tracker/annotator/zones/clip_filter/small_object_detector/camera/server/config). 본 Phase는 이 워커를 NVR 멀티카메라·플러그블 백엔드·분산노드·결과보고용으로 **일반화하여 확장**한다.

---

## 1. 목표 & 성공 기준(DoD)

P4는 "go2rtc가 재스트리밍하는 카메라 영상에서 별도 AI 워커가 YOLO로 객체(사람/차량/동물 등)를 검출·추적하고, 그 결과를 시간정렬된 메타데이터로 저장하여, 사용자가 '언제 어느 카메라에 사람이 나왔는가'를 검색해 클립으로 재생하고, 특정 객체 검출을 트리거로 녹화/이벤트를 생성하며, GPU on/off·CPU·외부 노드 사이에서 detection 부하를 분배한다"를 완성한다.

**DoD (이 항목들이 단독 시연 가능해야 P4 완료):**

1. **Detector 워커 기동**: `worker/detector/`가 카메라별로 go2rtc 재스트림(`rtsp://axp-go2rtc:8554/{go2rtc_name}`)에서 프레임을 취득 → YOLO 추론 → supervision(ByteTrack) 추적 → 결과를 서버에 보고. 카메라별 **처리 FPS 제한**과 **검출 구역(detection_zone) 마스크**, **모델/클래스 선택**이 적용된다.
2. **백엔드 토글(pluggable)**: 단일 `Detector` 인터페이스 아래 **CudaYolo / CpuYolo / RemoteNode** 구현이 환경·노드 능력·`ai_settings`에 따라 선택된다. GPU 미탑재/비활성 서버에서 CPU로 동작하고, GPU 활성 시 자동 가속, 부족 시 외부 노드로 오프로드된다(시연: GPU off→CPU, GPU on→CUDA, 노드 추가→오프로드).
3. **detection 메타 저장**: 추적된 객체가 `detections`(camera, ts, class, confidence, bbox, track_id, zone, segment/recording 참조)에 적재되고, **P2 세그먼트·P3 이벤트와 시간정렬 결합**(재생 시 bbox 오버레이 복원 가능).
4. **객체 검색(Smart Search)**: `GET /detections/search`로 **클래스·시간·카메라·구역·최소 confidence**로 녹화를 검색("사람 나온 클립")해 타임라인 마커 + 썸네일 카드 + 클립 재생(P2 playback 재사용)으로 표출. 인덱스로 16대·수일치 데이터에서 응답한다.
5. **객체 트리거 녹화/이벤트**: `object_triggers`(카메라×클래스×구역×조건) 매칭 시 **P3 events(`type='object'`) 생성 → P3 event_pipeline이 정책에 따라 P2 recording 생성**. **디바운스/쿨다운**으로 동일 트랙 반복·스팸을 억제한다.
6. **분산 AI**: `ai_nodes` 레지스트리 + **join 프로토콜**(등록 → scoped 노드 토큰 인증 → 하트비트), 카메라별 detection **할당**(assignment), 노드 능력 기반 **로드 분배**, 노드 장애 시 **재할당**. 단일 서버(내장 GPU)와 외부 노드 혼합 운영이 가능하다.
7. **detection 오버레이**: 재생 화면 위에 저장된 bbox/track 경로를 **오버레이 재생**하고(`GET /detections/overlay`), 옵션으로 **라이브 오버레이**(어노테이트 MJPEG/메타 WS)를 표시한다.
8. **테스트**: detector 백엔드 추상화·결과 보고·검색 쿼리·트리거 디바운스·노드 join/할당/재할당에 unit/integration, "객체 검색→클립 재생→오버레이" e2e 1개 이상 그린.

---

## 2. 범위 (In-scope / Out-of-scope)

### In-scope
- **AI Detector 워커**(`worker/detector/`): runway_monitor를 일반화 — 멀티카메라 파이프라인(capture→detect→track→report), go2rtc 프레임 취득, 카메라별 FPS/모델/클래스/zone, **플러그블 추론 백엔드**(CUDA/CPU/RemoteNode), CLIP 2차 검증(옵션).
- **추론 백엔드 추상화**: `Detector`(Protocol) + 팩토리(`make_detector`), 헬스·벤치마크(노드 능력 측정), 동적 on/off.
- **detection 메타 모델·적재**: `detections`(+세그먼트/이벤트 링크), 배치 보고 수집 API/큐, 시간정렬(세그먼트 매핑).
- **객체 검색 API + UI**: 클래스/카메라/시간/구역/score 필터, 타임라인 마커, 썸네일, 클립 재생.
- **detection 구역**: `detection_zones`(검출/무시 마스크, 카메라별 다중 폴리곤), 에디터 UI(runway_monitor zones.py·calibrate 페이지 일반화).
- **객체 트리거**: `object_triggers` → P3 `events(type='object')` 발행 → P3 정책으로 녹화/알림. 디바운스/쿨다운/최소 체류·진입.
- **분산 AI**: `ai_nodes`, join/인증(scoped 토큰)·하트비트, `detection_assignments`(카메라→노드), 로드 분배 스케줄러, 장애 재할당.
- **오버레이**: 재생 오버레이 메타 API + 프론트 `DetectionOverlay`, 라이브 오버레이(옵션).
- **AI 설정**: `ai_settings`(전역 GPU 토글·기본 모델·기본 FPS·CLIP on/off·라이브 오버레이 on/off), 카메라별 override.

### Out-of-scope (다른 Phase)
- **이벤트 정규화·구독·정책·스케줄·전후버퍼 회수 엔진**: P3 소유. P4는 `events(type='object')`를 **발행만** 하고 P3 `event_pipeline.handle`/정책/`event_clip.materialize`를 **호출/재사용**(클립 생성 로직 중복 금지).
- **녹화/세그먼트/스토리지/재생 엔진·다운로드**: P2 소유. P4는 `segment_indexer`·`recordings`·playback API를 **호출**만.
- **카메라 온보딩·go2rtc 동기화·streams**: P1 소유. P4는 `cameras`/`streams.go2rtc_name`을 **소비**.
- **규칙엔진·푸시/이메일/웹훅 실제 전송·IP스피커/IO**: P5. P4 detection→events·signals를 P5가 트리거로 소비.
- **LPR(번호판)·얼굴인식·사람/차량 카운팅·혼잡/배회·오디오 분류·연기/화재·시맨틱(텍스트) 검색**: **P6**. (P4는 COCO 일반 객체 detection + 클래스/구역 기반 검색까지. CLIP은 *오탐 억제용 2차 분류*로만 사용하고, 자유텍스트 시맨틱 검색 임베딩 인덱스는 P6.)
- **모니터 클라이언트 페어링**: P5.

> **경계 원칙**: detection은 "센서 결과"(`detections`), event는 "사건"(`events`). 객체 트리거는 detection을 **P3 event로 승격**시키는 어댑터다. detection 자체는 P3를 거치지 않고 검색용으로 항상 저장된다(검색이 핵심 가치이므로). 트리거된 것만 event/녹화가 된다.

---

## 3. 선행 의존성

| 출처 | P4가 사용하는 산출물 | 사용처 |
|---|---|---|
| **P0** | `axp` 패키지/MVC/Blueprint, `BaseDB`(Snowflake·soft delete·audit), `ResponseBuilder`, JWT `@login_required`/`@permission_required`, **scoped 토큰 검증기**(aud=`node`), Celery `celery_use_db()`, Redis, WS 허브, 예외→응답 매핑, i18n, `config`(GO2RTC_URL 등) | 전 영역. **노드 join 인증 = aud=`node` 토큰**(P0 토큰서비스 aud 분기 활용) |
| **P1** | `cameras`(enabled/status/capabilities), `streams`(role main/sub, **`go2rtc_name`**), go2rtc 컨테이너(`rtsp://axp-go2rtc:8554/{go2rtc_name}`), 카메라 CRUD 시그널, 스냅샷 경로 | detector가 카메라 목록·메인스트림 go2rtc_name으로 프레임 취득. 카메라 add/remove→할당 갱신 |
| **P2** | `segments`(camera/disk/rel_path/start_ts/end_ts), `service.segment_indexer`(시각→세그먼트), `recordings`(reason/retention) + 생성/병합 API, `playback`(타임라인/세그먼트/frame/thumb), `task.thumbnail`, `axp-media` 공유 볼륨 | detection ts→세그먼트 매핑(시간정렬), 검색결과 클립 재생, 스냅샷/썸네일, 트리거 녹화 |
| **P3** | `events`(모델·`type='object'`·`region`·`recording_id`), **`event_pipeline.handle()`**(또는 `event_pipeline.ingest_object()` 어댑터), `event_policy_resolver`/`schedule_resolver`, `event_clip.materialize`, `signals.event_created`, `event_outbox` | 객체 트리거가 detection→event로 승격→정책 기반 녹화/알림. P4는 source=`server`(AI)로 발행 |
| **P5(역방향)** | (P4가 **제공**) detection→events(type=object)·`signals.event_created`·detection summary outbox | P5 규칙엔진이 "사람 감지" 등을 트리거로 소비 |
| **P6(역방향)** | (P4가 **제공**) `detections` 모델·crop 스냅샷·track 구조·노드 인프라 | P6 LPR/face/카운팅/시맨틱이 detections에 속성 추가·임베딩 인덱스 확장 |

**P4 착수 전 확인(블로킹):**
1. (P3) `events`에 `type='object'` 추가 가능 여부 + **객체 이벤트 진입점 시그니처**(권장: `event_pipeline.ingest_object(camera_id, normalized: dict)` 또는 기존 `handle(camera, raw, source='server')` 재사용). detection→event 어댑터를 P3가 받는가 P4가 P3 함수를 호출하는가.
2. (P2) `segment_indexer.find(camera_id, start, end)` 시그니처 + `recordings` 생성/병합 API(P3가 이미 사용 중인 것 재사용).
3. (P2) playback 타임라인/세그먼트 응답 스키마(검색결과 오버레이 좌표 스케일 기준 = 세그먼트 width/height).
4. (P0) scoped 토큰(aud=`node`) **발급 경로** — P0는 검증기만, 발급은 누가? → 본 Phase 7.2에서 admin `/ai-nodes/{id}/token` 발급 정의(P0 TokenService 확장 협의).
5. (P1) `streams.go2rtc_name`으로 **메인 스트림**을 식별하는 규칙(role='main'), 서브로 추론할지 옵션.

---

## 4. 데이터 모델

> 컨벤션: PK `id BIGINT`(Snowflake), 모든 시각 컬럼은 **`DATETIME(3)` UTC 저장**(PLAN §12.1; P2 `segments`와 동일 단위로 시간정렬 JOIN 단순화). 레지스트리성 시각(`last_heartbeat_ts`·`claimed_at`·`last_report_ts`)도 `DATETIME(3)`로 통일(전 계층 동일 물리 타입). API 직렬화는 epoch ms·ISO, 표시는 KST. 단, 노드↔서버 JSON 보고의 `ts`/`epoch_map`은 전송 포맷(epoch ms)이므로 유지. 감사 컬럼은 사람이 만드는 테이블(zones/triggers/nodes/settings)만. `detections`는 **초고빈도 append**라 FK 미설정·soft delete 미사용(정리는 보존 배치 DELETE + 파티션 DROP). 스키마 `axp`.

신규 테이블: **`detections`, `detection_zones`, `object_triggers`, `ai_nodes`, `detection_assignments`, `ai_settings`**. 보조: `detector_health`(워커/노드 헬스 미러, Redis 우선·DB 미러 옵션).

### 4.1 `detections` — 추적된 객체 검출(초고빈도, append 중심, 검색의 핵심)

> 한 카메라가 detection 처리 ~5fps에서 객체 1개를 1초 추적하면 5행이 아니라 **트랙 단위로 다운샘플**해 적재(아래 6.7 적재정책: track 생성·종료·N초 간격 샘플만 저장)하여 행 폭증을 억제한다. 그래도 대량이므로 인덱스·파티션이 핵심.

| 컬럼 | 타입 | 설명/인덱스 |
|---|---|---|
| `id` | BIGINT PK | Snowflake(시간순 ≈ 단조) |
| `camera_id` | BIGINT NOT NULL | 논리 FK(cameras.id). idx `(camera_id, ts)` |
| `ts` | DATETIME(3) NOT NULL | 검출 프레임의 **벽시계 시각**(UTC, ms). go2rtc 프레임 수신 시각 기준(6.6 시간정렬). idx |
| `class_id` | SMALLINT NOT NULL | 모델 클래스 id(COCO 등). |
| `label` | VARCHAR(32) NOT NULL | 정규화 라벨(`person`,`car`,`truck`,`bus`,`motorcycle`,`bicycle`,`dog`,`cat`,`bird`,...). 검색 필터 주키. idx `(label, ts)` |
| `confidence` | SMALLINT NOT NULL | 0–100(정수 정규화, float 회피). |
| `track_id` | BIGINT NULL | 카메라+세션 내 ByteTrack id를 전역화한 값(아래 track_key). 같은 객체 묶음. idx `(camera_id, track_id)` |
| `track_key` | CHAR(32) NULL | `md5(node_session:camera:bytetrack_id)` — 워커 재시작/노드 교체에도 트랙 묶음 식별(track_id 충돌 방지) |
| `bbox` | JSON NOT NULL | **정규화 좌표 0–1** `[x1,y1,x2,y2]`(해상도 독립; 오버레이 스케일 단순). 원픽셀은 frame_w/h로 환산해 저장 |
| `frame_w` / `frame_h` | SMALLINT NULL | 추론 프레임 원해상도(정규화 역산·디버깅) |
| `zone_id` | BIGINT NULL | 검출이 속한 detection_zones.id(구역 검색용, bottom-center 기준). idx `(zone_id, ts)` |
| `segment_id` | BIGINT NULL | ts가 포함되는 P2 segments.id(시간정렬 캐시; 비동기 백필 가능). idx |
| `event_id` | BIGINT NULL | 이 detection이 트리거한 P3 events.id(트리거된 경우만). idx |
| `attrs` | JSON NULL | 확장 속성(P6 예약: `{"speed_px":..,"area":..,"clip_verified":true,"crop_path":"..."}`. P4는 speed/area/crop만) |
| `node_id` | BIGINT NULL | 처리한 ai_nodes.id(분산 진단). |
| `created_at` | DATETIME(3) NOT NULL | 적재 시각(파티션 키 후보) |

핵심 인덱스:
- `idx_det_cam_ts (camera_id, ts)` — **검색·타임라인 주조회**(카메라+기간 범위 스캔).
- `idx_det_label_ts (label, ts)` — "사람 나온 클립" 전 카메라 검색.
- `idx_det_cam_label_ts (camera_id, label, ts)` — 카메라+클래스+기간(가장 흔한 검색 조합, 커버링 후보).
- `idx_det_track (camera_id, track_id)` — 트랙 단위 경로 복원.
- `idx_det_zone_ts (zone_id, ts)` — 구역별 검색.
- `idx_det_segment (segment_id)` — 재생 오버레이(세그먼트→detection 조회).
- `idx_det_event (event_id)` — 이벤트↔detection 역참조.
- **파티셔닝(권장)**: `created_at`(또는 `ts`) RANGE 월 파티션 → 보존정리를 파티션 DROP으로 O(1). MVP는 단일 테이블+인덱스, 14절 결정.

> `bbox`를 JSON 대신 4개 `SMALLINT`(x1..y2, 0–10000 고정소수)로 두는 대안 — 인덱스·집계 불필요하므로 JSON으로 단순화하되, 초기 적재량이 매우 크면 컬럼 분리 검토(13절).

### 4.2 `detection_zones` — 검출/무시 구역(카메라별 다중 폴리곤)

> runway_monitor `zones.json`을 DB화·일반화. runway/sky 같은 도메인 특수 타입 대신 범용 `include`(검출 영역)·`ignore`(무시 영역) + 선택적 라벨 필터.

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `id` | BIGINT PK | Snowflake |
| `camera_id` | BIGINT NOT NULL | idx `(camera_id)` |
| `name` | VARCHAR(80) NOT NULL | 표시명("정문","주차장 입구") |
| `kind` | VARCHAR(16) NOT NULL | `include`(이 안만 검출) / `ignore`(이 안은 폐기) |
| `polygon` | JSON NOT NULL | 정규화 좌표 `[[x,y],...]`(0–1). 최소 3점 |
| `label_filter` | JSON NULL | 이 구역에 적용할 클래스 화이트리스트(NULL=전체). 예 `["person","car"]` |
| `color` | VARCHAR(9) NULL | UI 표시색(헥스). 기본 Electric Blue 톤 |
| `enabled` | TINYINT(1) NOT NULL default 1 | |
| `priority` | SMALLINT NOT NULL default 0 | 겹침 시 zone_id 귀속 우선순위(큰 값 우선) |
| 감사 | `created_at/updated_at/deleted_at/created_by_id/last_updated_by_id` | 공통 |

인덱스: `idx_zone_cam (camera_id)`, `idx_zone_deleted (deleted_at)`.
의미: detector는 카메라의 `include` 합집합 안(없으면 전체) + `ignore` 차집합으로 검출 필터(runway_monitor `_filter_by_zone` 일반화). detection 적재 시 bottom-center가 속한 zone을 `zone_id`로 귀속(priority·면적 최소 우선).

### 4.3 `object_triggers` — 객체 검출 → 이벤트/녹화 트리거 규칙

> detection을 P3 event로 승격시키는 규칙. P3 `event_policies`와 **역할 분리**: trigger는 "무엇이 event가 되는가"(센서→사건), policy는 "그 event를 녹화/알림할지"(사건→행동). trigger가 발행한 `events(type='object')`를 P3 정책 엔진이 받는다.

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `id` | BIGINT PK | Snowflake |
| `camera_id` | BIGINT NULL | NULL=전역 기본(모든 카메라). idx `(camera_id)` |
| `name` | VARCHAR(80) NOT NULL | "주차장 사람 감지" |
| `labels` | JSON NOT NULL | 트리거 대상 클래스 `["person"]` 또는 `["car","truck","bus"]` |
| `zone_id` | BIGINT NULL | 특정 구역에서만(NULL=전체 프레임). detection_zones.id |
| `min_confidence` | SMALLINT NOT NULL default 50 | 이 이상만(0–100) |
| `min_dwell_ms` | INT NOT NULL default 0 | 트랙이 이 시간 이상 지속·구역체류해야 발화(순간 오탐 컷) |
| `require_zone_entry` | TINYINT(1) NOT NULL default 0 | 트랙이 구역 **밖→안 진입** 시에만(라인크로스 유사) |
| `min_count` | SMALLINT NOT NULL default 1 | 동시 동일라벨 N개 이상(혼잡 단순판정; 고급은 P6) |
| `cooldown_s` | SMALLINT NOT NULL default 30 | 동일 (camera,trigger) 재발화 억제(디바운스) |
| `debounce_per_track` | TINYINT(1) NOT NULL default 1 | 같은 track_id는 1회만 발화(트랙 단위 디바운스) |
| `event_subtype` | VARCHAR(48) NULL | 발행 event의 subtype(예 `person`,`vehicle`). NULL=label 사용 |
| `action_hint` | VARCHAR(16) NULL | P3 정책 미정의 시 힌트(`record`/`notify_only`). 최종결정은 P3 |
| `notify` | TINYINT(1) NOT NULL default 1 | event에 notify 플래그 전달(P5) |
| `enabled` | TINYINT(1) NOT NULL default 1 | |
| `active_schedule_id` | BIGINT NULL | 활성 시간창(P3 schedules.id 재사용; NULL=항상) |
| 감사 | `created_at/updated_at/deleted_at/created_by_id/last_updated_by_id` | 공통 |

인덱스: `idx_trig_cam (camera_id)`, `idx_trig_deleted (deleted_at)`.
조회 우선순위(해석): `(camera_id 일치)` > `(camera_id NULL 전역)`. detector/서버가 트랙 상태를 보고 트리거 평가(6.8).

### 4.4 `ai_nodes` — 분산 추론 노드 레지스트리

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `id` | BIGINT PK | Snowflake |
| `uuid` | CHAR(32) UNIQUE | 외부 노출/토큰 sub(노드 식별) |
| `name` | VARCHAR(80) NOT NULL | "node-gpu-01"(표시) |
| `kind` | VARCHAR(16) NOT NULL | `builtin`(서버 내장 detector) / `remote`(외부 join 노드) |
| `endpoint` | VARCHAR(255) NULL | remote 노드의 base URL(서버→노드 push 모드 시). pull/보고모드는 NULL |
| `status` | VARCHAR(16) NOT NULL default 'offline' | `online`/`degraded`/`offline`/`draining`/`disabled` |
| `enabled` | TINYINT(1) NOT NULL default 1 | 관리자 on/off(분배 대상 여부) |
| `gpu` | TINYINT(1) NOT NULL default 0 | GPU 보유 여부(자가보고) |
| `gpu_name` | VARCHAR(80) NULL | 예 "NVIDIA RTX 4070" |
| `capacity` | SMALLINT NOT NULL default 0 | 동시 처리 가능 카메라 수(벤치마크/자가보고; 분배 기준) |
| `capabilities` | JSON NULL | `{"models":["yolov8n","yolov8m"],"max_imgsz":1280,"clip":true,"backends":["cuda"]}` |
| `bench` | JSON NULL | 측정치 `{"fps_per_cam_yolov8m_1280":18.2,"vram_mb":8192,"measured_at":...}` |
| `version` | VARCHAR(40) NULL | 워커 버전(호환성) |
| `assigned_count` | SMALLINT NOT NULL default 0 | 현재 할당 카메라 수(분배 캐시; 권위는 detection_assignments) |
| `last_heartbeat_ts` | DATETIME(3) NULL | UTC ms. 장애판정(임계 초과→offline). idx |
| `token_jti` | CHAR(36) NULL | 발급된 노드 토큰 jti(폐기·회전 추적) |
| `last_seen_ip` | VARCHAR(64) NULL | 마지막 접속 IP(감사) |
| `last_error` | VARCHAR(512) NULL | |
| 감사 | `created_at/updated_at/deleted_at/created_by_id/last_updated_by_id` | 공통 |

인덱스: `uq_node_uuid (uuid)`, `idx_node_status (status)`, `idx_node_heartbeat (last_heartbeat_ts)`, `idx_node_deleted (deleted_at)`.
`builtin` 노드는 서버 부팅 시 1행 자동 시드(서버 자신; GPU_ENABLED·실측으로 gpu/capacity 갱신).

### 4.5 `detection_assignments` — 카메라 → 노드 할당(분배 권위)

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `id` | BIGINT PK | Snowflake |
| `camera_id` | BIGINT NOT NULL | idx `uq (camera_id)` UNIQUE(카메라는 동시 1노드; soft-del 미사용) |
| `node_id` | BIGINT NOT NULL | 할당 노드. idx `(node_id)` |
| `state` | VARCHAR(16) NOT NULL default 'pending' | `pending`(노드 픽업 전)/`active`/`reassigning`/`paused` |
| `model` | VARCHAR(40) NULL | 이 카메라에 쓸 모델(override; NULL=ai_settings 기본) |
| `target_fps` | SMALLINT NULL | 처리 FPS(override; NULL=기본) |
| `claimed_at` | DATETIME(3) NULL | 노드가 픽업한 UTC ms |
| `last_report_ts` | DATETIME(3) NULL | 마지막 detection 보고(스톨 판정) |
| `epoch` | INT NOT NULL default 0 | 재할당 세대(stale 보고 거부용; 노드는 epoch 동봉 보고) |
| `created_at` / `updated_at` | DATETIME(3) | |

인덱스: `uq_assign_cam (camera_id)`, `idx_assign_node (node_id)`, `idx_assign_state (state)`.
권위는 이 테이블. 분배 스케줄러가 변경하면 `epoch++`, Redis 채널/노드 폴링으로 노드가 자기 할당셋을 재계산.

### 4.6 `ai_settings` — 전역/카메라 AI 설정(GPU 토글·기본값)

> 단일 행(전역) + 카메라별 override 행. 또는 P0 `settings` 키-값에 통합 가능(아래는 전용 테이블 안; settings 통합 시 14절).
> **전역 GPU on/off 권위는 본 `ai_settings.gpu_enabled`(전역 행)이며, P0 `settings.gpu_enabled`는 부트스트랩 placeholder(P4 도입 시 이관, 중복 회피)**(PLAN §12.1 일치).

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `id` | BIGINT PK | Snowflake |
| `camera_id` | BIGINT NULL | NULL=전역 기본. idx `uq (camera_id)` |
| `detection_enabled` | TINYINT(1) NOT NULL default 1 | (카메라) AI 켜기/끄기 |
| `gpu_enabled` | TINYINT(1) NOT NULL default 0 | **전역 GPU 토글**(전역 행에서만 의미; builtin 노드 CUDA/CPU 선택) |
| `model` | VARCHAR(40) NOT NULL default 'yolov8n' | 기본 모델(전역). 카메라 override 가능 |
| `target_fps` | SMALLINT NOT NULL default 5 | 카메라당 기본 처리 FPS(부하 핵심 손잡이) |
| `imgsz` | SMALLINT NOT NULL default 640 | 추론 해상도(작을수록 빠름) |
| `min_confidence` | SMALLINT NOT NULL default 35 | 적재 최소 conf |
| `labels` | JSON NULL | 검출 대상 클래스 화이트리스트(NULL=기본셋 사람/차량/동물). COCO id 매핑 |
| `clip_enabled` | TINYINT(1) NOT NULL default 0 | CLIP 2차 검증 on/off |
| `live_overlay_enabled` | TINYINT(1) NOT NULL default 0 | 라이브 어노테이트 송출 on/off(비용) |
| `store_crops` | TINYINT(1) NOT NULL default 0 | detection 크롭 스냅샷 저장(검색 썸네일 품질↑, 용량↑) |
| `retention_days` | SMALLINT NOT NULL default 30 | detections 보존일(파티션/배치 정리) |
| `sample_interval_ms` | INT NOT NULL default 1000 | 트랙 지속 중 detection 적재 간격(6.7) |
| 감사 | `created_at/updated_at/last_updated_by_id` | |

인덱스: `uq_aiset_cam (camera_id)`.
해석: 카메라 유효설정 = 전역 ← 카메라 override deep-merge(P0 권한맵 병합 패턴 동일).

### 4.7 마이그레이션 SQL 스케치 (MySQL 8, InnoDB/utf8mb4)

```sql
-- detections ------------------------------------------------------------
CREATE TABLE detections (
  id          BIGINT       NOT NULL PRIMARY KEY,
  camera_id   BIGINT       NOT NULL,
  ts          DATETIME(3)  NOT NULL,
  class_id    SMALLINT     NOT NULL,
  label       VARCHAR(32)  NOT NULL,
  confidence  SMALLINT     NOT NULL,
  track_id    BIGINT       NULL,
  track_key   CHAR(32)     NULL,
  bbox        JSON         NOT NULL,
  frame_w     SMALLINT     NULL,
  frame_h     SMALLINT     NULL,
  zone_id     BIGINT       NULL,
  segment_id  BIGINT       NULL,
  event_id    BIGINT       NULL,
  attrs       JSON         NULL,
  node_id     BIGINT       NULL,
  created_at  DATETIME(3)  NOT NULL,
  INDEX idx_det_cam_ts (camera_id, ts),
  INDEX idx_det_label_ts (label, ts),
  INDEX idx_det_cam_label_ts (camera_id, label, ts),
  INDEX idx_det_track (camera_id, track_id),
  INDEX idx_det_zone_ts (zone_id, ts),
  INDEX idx_det_segment (segment_id),
  INDEX idx_det_event (event_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
-- (대규모) ALTER ... PARTITION BY RANGE (TO_DAYS(created_at)) ( ... ) — 14절

-- detection_zones -------------------------------------------------------
CREATE TABLE detection_zones (
  id                 BIGINT      NOT NULL PRIMARY KEY,
  camera_id          BIGINT      NOT NULL,
  name               VARCHAR(80) NOT NULL,
  kind               VARCHAR(16) NOT NULL,
  polygon            JSON        NOT NULL,
  label_filter       JSON        NULL,
  color              VARCHAR(9)  NULL,
  enabled            TINYINT(1)  NOT NULL DEFAULT 1,
  priority           SMALLINT    NOT NULL DEFAULT 0,
  created_at         DATETIME(3) NOT NULL,
  updated_at         DATETIME(3) NOT NULL,
  deleted_at         DATETIME(3) NULL,
  created_by_id      BIGINT      NULL,
  last_updated_by_id BIGINT      NULL,
  INDEX idx_zone_cam (camera_id),
  INDEX idx_zone_deleted (deleted_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- object_triggers -------------------------------------------------------
CREATE TABLE object_triggers (
  id                 BIGINT      NOT NULL PRIMARY KEY,
  camera_id          BIGINT      NULL,
  name               VARCHAR(80) NOT NULL,
  labels             JSON        NOT NULL,
  zone_id            BIGINT      NULL,
  min_confidence     SMALLINT    NOT NULL DEFAULT 50,
  min_dwell_ms       INT         NOT NULL DEFAULT 0,
  require_zone_entry TINYINT(1)  NOT NULL DEFAULT 0,
  min_count          SMALLINT    NOT NULL DEFAULT 1,
  cooldown_s         SMALLINT    NOT NULL DEFAULT 30,
  debounce_per_track TINYINT(1)  NOT NULL DEFAULT 1,
  event_subtype      VARCHAR(48) NULL,
  action_hint        VARCHAR(16) NULL,
  notify             TINYINT(1)  NOT NULL DEFAULT 1,
  enabled            TINYINT(1)  NOT NULL DEFAULT 1,
  active_schedule_id BIGINT      NULL,
  created_at         DATETIME(3) NOT NULL,
  updated_at         DATETIME(3) NOT NULL,
  deleted_at         DATETIME(3) NULL,
  created_by_id      BIGINT      NULL,
  last_updated_by_id BIGINT      NULL,
  INDEX idx_trig_cam (camera_id),
  INDEX idx_trig_deleted (deleted_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ai_nodes --------------------------------------------------------------
CREATE TABLE ai_nodes (
  id                 BIGINT      NOT NULL PRIMARY KEY,
  uuid               CHAR(32)    NOT NULL,
  name               VARCHAR(80) NOT NULL,
  kind               VARCHAR(16) NOT NULL,
  endpoint           VARCHAR(255) NULL,
  status             VARCHAR(16) NOT NULL DEFAULT 'offline',
  enabled            TINYINT(1)  NOT NULL DEFAULT 1,
  gpu                TINYINT(1)  NOT NULL DEFAULT 0,
  gpu_name           VARCHAR(80) NULL,
  capacity           SMALLINT    NOT NULL DEFAULT 0,
  capabilities       JSON        NULL,
  bench              JSON        NULL,
  version            VARCHAR(40) NULL,
  assigned_count     SMALLINT    NOT NULL DEFAULT 0,
  last_heartbeat_ts  DATETIME(3) NULL,
  token_jti          CHAR(36)    NULL,
  last_seen_ip       VARCHAR(64) NULL,
  last_error         VARCHAR(512) NULL,
  created_at         DATETIME(3) NOT NULL,
  updated_at         DATETIME(3) NOT NULL,
  deleted_at         DATETIME(3) NULL,
  created_by_id      BIGINT      NULL,
  last_updated_by_id BIGINT      NULL,
  UNIQUE KEY uq_node_uuid (uuid),
  INDEX idx_node_status (status),
  INDEX idx_node_heartbeat (last_heartbeat_ts),
  INDEX idx_node_deleted (deleted_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- detection_assignments -------------------------------------------------
CREATE TABLE detection_assignments (
  id             BIGINT      NOT NULL PRIMARY KEY,
  camera_id      BIGINT      NOT NULL,
  node_id        BIGINT      NOT NULL,
  state          VARCHAR(16) NOT NULL DEFAULT 'pending',
  model          VARCHAR(40) NULL,
  target_fps     SMALLINT    NULL,
  claimed_at     DATETIME(3) NULL,
  last_report_ts DATETIME(3) NULL,
  epoch          INT         NOT NULL DEFAULT 0,
  created_at     DATETIME(3) NOT NULL,
  updated_at     DATETIME(3) NOT NULL,
  UNIQUE KEY uq_assign_cam (camera_id),
  INDEX idx_assign_node (node_id),
  INDEX idx_assign_state (state)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ai_settings -----------------------------------------------------------
CREATE TABLE ai_settings (
  id                   BIGINT      NOT NULL PRIMARY KEY,
  camera_id            BIGINT      NULL,
  detection_enabled    TINYINT(1)  NOT NULL DEFAULT 1,
  gpu_enabled          TINYINT(1)  NOT NULL DEFAULT 0,
  model                VARCHAR(40) NOT NULL DEFAULT 'yolov8n',
  target_fps           SMALLINT    NOT NULL DEFAULT 5,
  imgsz                SMALLINT    NOT NULL DEFAULT 640,
  min_confidence       SMALLINT    NOT NULL DEFAULT 35,
  labels               JSON        NULL,
  clip_enabled         TINYINT(1)  NOT NULL DEFAULT 0,
  live_overlay_enabled TINYINT(1)  NOT NULL DEFAULT 0,
  store_crops          TINYINT(1)  NOT NULL DEFAULT 0,
  retention_days       SMALLINT    NOT NULL DEFAULT 30,
  sample_interval_ms   INT         NOT NULL DEFAULT 1000,
  created_at           DATETIME(3) NOT NULL,
  updated_at           DATETIME(3) NOT NULL,
  last_updated_by_id   BIGINT      NULL,
  UNIQUE KEY uq_aiset_cam (camera_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

> **P3 `events` 영향**: `type` 도메인에 `'object'`가, `source`에 `'server'`(AI)가 포함되어야 함(P3가 이미 `object`/`server`를 예약했는지 확인 — phase-3 §6.4·§4.1에 `object`/`server` 언급됨 → 정합). detection→event는 P3 `events.region`에 bbox(정규화)·`raw`에 detection 요약을 넣어 발행. P4는 events에 신규 컬럼 추가 없음.

---

## 5. 백엔드 설계

### 5.1 디렉터리 배치 (PLAN 6장 구조 준수)

```
server/
├─ view/api/
│  ├─ detection.py        # 검색/타임라인/오버레이/단건 조회
│  ├─ detection_zone.py   # 구역 CRUD (카메라 스코프)
│  ├─ object_trigger.py   # 트리거 CRUD + resolve 프리뷰
│  ├─ ai_node.py          # (admin) 노드 레지스트리·토큰·드레인
│  ├─ ai_assignment.py    # (admin) 할당 조회/수동 재배치
│  ├─ ai_settings.py      # 전역/카메라 AI 설정(GPU 토글 등)
│  └─ ai_ingest.py        # ★ 노드→서버 보고 수집(aud=node 토큰 전용)
├─ controller/
│  ├─ detection.py        # 검색쿼리 조립·DTO·세그먼트/이벤트 링크
│  ├─ detection_zone.py
│  ├─ object_trigger.py
│  ├─ ai_node.py
│  ├─ ai_assignment.py
│  └─ ai_settings.py
├─ service/
│  ├─ detection_ingest.py     # 보고 배치 검증·정규화·track_key·zone귀속·적재(bulk insert)
│  ├─ detection_search.py     # 검색 쿼리 빌더(필터→인덱스 친화 SQL)·결과 그룹핑(클립화)
│  ├─ object_trigger_engine.py# detection/track → trigger 평가 → P3 ingest_object 호출
│  ├─ segment_linker.py       # detection.ts → P2 segment_id 매핑(즉시/백필)
│  ├─ ai_node_registry.py     # join/토큰/하트비트/상태전이/벤치 기록
│  ├─ ai_scheduler.py         # 카메라↔노드 분배·재할당 알고리즘
│  └─ ai_config_resolver.py   # 카메라 유효 AI 설정(전역+override) + 노드용 작업스펙 생성
├─ driver/
│  └─ ai_node_client.py       # (push 모드) 서버→remote 노드 제어 호출(옵션)
└─ task/list/
   ├─ ai_supervise.py         # beat: 노드 헬스 스윕·재할당·builtin 벤치 트리거
   ├─ detection_linker.py     # segment_id 백필(미링크 detection)·event 링크 정리
   ├─ detection_retention.py  # detections 보존정리(파티션 DROP/배치 DELETE)·크롭 정리
   └─ ai_crop_thumb.py        # 검색 썸네일/크롭 생성(store_crops 시, P2 frame 재사용)

worker/
└─ detector/                  # ★ AI 워커(별도 컨테이너 axp-detector / 외부 노드 동일 이미지)
   ├─ main.py                 # 엔트리(서버 등록→할당 폴링→파이프라인 기동)
   ├─ config.py              # env(SERVER_API, NODE_TOKEN, GPU_ENABLED, BACKENDS...)
   ├─ node_agent.py          # 서버 join/heartbeat/할당 동기화/보고 전송(httpx)
   ├─ pipeline.py            # 멀티카메라 슈퍼바이저(카메라당 CameraPipeline) — runway_monitor 확장
   ├─ camera_pipeline.py     # capture→detect→track→(zone필터)→sample→report (runway pipeline.py 기반)
   ├─ source.py              # go2rtc 프레임 취득(ffmpeg→MJPEG) — runway_monitor camera.py 기반
   ├─ backends/
   │  ├─ base.py             # Detector Protocol + DetectionResult dataclass
   │  ├─ yolo_cuda.py        # CudaYolo (ultralytics, device=cuda, half)
   │  ├─ yolo_cpu.py         # CpuYolo (device=cpu, imgsz 축소·int8 옵션)
   │  └─ remote_node.py      # RemoteNode (다른 노드/서버 추론 HTTP — builtin이 외부로 오프로드)
   ├─ tracker.py             # ObjectTracker(ByteTrack) — runway_monitor tracker.py 거의 그대로
   ├─ zones.py               # ZoneManager(서버 detection_zones 동기화) — runway_monitor zones.py 일반화
   ├─ clip_filter.py         # CLIPFilter — runway_monitor 그대로(옵션)
   ├─ annotator.py           # 라이브 오버레이용 어노테이트 — runway_monitor annotator.py 축약
   ├─ server.py              # (옵션) FastAPI: /healthz, /benchmark, 라이브 어노 MJPEG, push추론 endpoint
   ├─ requirements.txt       # ultralytics/supervision/opencv-headless/torch/httpx/(transformers)
   └─ Dockerfile             # CPU/GPU 2-스테이지(베이스 이미지 분기)
```

### 5.2 API 표

> 공통: `/api/v1` prefix. 사용자 API는 `Authorization: Bearer`(aud=web) + `@permission_required('<resource>','<action>')`(PLAN §12.2 콜론 카탈로그: `detections`/`zones`/`triggers`/`ai`/`ai_nodes`). **노드 보고 API(`/ai/ingest/*`)는 aud=`node` scoped 토큰 전용**(별도 가드 `@node_token_required`, 사용자 권한맵과 분리). 카메라 스코프 사용자는 응답에서 비인가 카메라 detection 제외(controller 교집합). 페이지네이션 ams 호환(`page, items_per_page, sort, order`).

#### 사용자/관리자 API

| Method | Path | 권한 | 요청 | 응답(`data`) |
|---|---|---|---|---|
| GET | `/detections/search` | `detections:read` | `camera_id[]`, `label[]`, `start`(ms), `end`(ms), `zone_id[]`, `min_confidence`, `group`(`track`/`clip`/`raw`), `page`, `items_per_page` | `{count, items:[DetectionGroupDTO]}`(group=clip이면 클립단위, track이면 트랙단위) |
| GET | `/detections/timeline` | `detections:read` | `camera_id`, `start`, `end`, `bucket`(초), `label[]` | `{markers:[{ts,label,count,top_conf,track_id,thumb_url}], coverage:[{start,end,reason}]}`(coverage=P2 녹화구간) |
| GET | `/detections/{id}` | `detections:read` | — | `DetectionDTO`(bbox/track/segment/event 링크) |
| GET | `/detections/{id}/snapshot` | `detections:read` | — | `image/jpeg`(저장 크롭 or P2 `frame?ts=` 추출+bbox 박싱, `Cache-Control: private`) |
| GET | `/detections/overlay` | `detections:read` | `camera_id`, `start`, `end`(재생 구간), `label[]?` | `{w,h, tracks:[{track_id,label,points:[{ts,bbox,conf}]}]}`(재생 오버레이용; 정규화 bbox) |
| GET | `/cameras/{id}/detections/live` (WS) | `detections:read` + scope | — | 실시간 detection push(라이브 오버레이; bbox 메타 스트림) |
| GET | `/cameras/{id}/detection-zones` | `zones:read` | — | `[DetectionZoneDTO]` |
| POST | `/cameras/{id}/detection-zones` | `zones:update` | `DetectionZoneInput` | 생성. detector에 zone 변경 시그널(Redis) |
| PUT | `/detection-zones/{id}` | `zones:update` | `DetectionZoneInput` | 수정 + 시그널 |
| DELETE | `/detection-zones/{id}` | `zones:update` | — | soft delete + 시그널 |
| GET | `/object-triggers` | `triggers:read` | `camera_id?` | `[ObjectTriggerDTO]`(전역+카메라 병합 뷰) |
| POST | `/object-triggers` | `triggers:update` | `ObjectTriggerInput` | 생성 |
| PUT | `/object-triggers/{id}` | `triggers:update` | `ObjectTriggerInput` | 수정 |
| DELETE | `/object-triggers/{id}` | `triggers:update` | — | soft delete |
| POST | `/object-triggers/test` | `triggers:read` | `{camera_id, label, confidence, zone_id?}` | 매칭 프리뷰 `{matched:bool, trigger_id?, would_action?}` |
| GET | `/ai/settings` | `ai:read` | `camera_id?` | 전역+카메라 유효설정 `AiSettingsDTO` |
| PUT | `/ai/settings` | `ai:update` | 전역 필드(`gpu_enabled` 등) | 갱신 + builtin 노드 재구성 시그널 |
| PUT | `/cameras/{id}/ai-settings` | `ai:update` | 카메라 override 필드 | 갱신 + 해당 카메라 재구성 시그널 |
| GET | `/ai-nodes` | `ai_nodes:manage` | — | `[AiNodeDTO]`(상태/하트비트/부하/벤치) |
| POST | `/ai-nodes` | `ai_nodes:manage` | `{name, kind:'remote'}` | 노드 생성(pre-register) `{node, join_token}`(1회용 등록토큰) |
| POST | `/ai-nodes/{id}/token` | `ai_nodes:manage` | `{ttl_days?}` | scoped 노드 토큰 (재)발급(aud=node, sub=node.uuid). 이전 jti 폐기 |
| PUT | `/ai-nodes/{id}` | `ai_nodes:manage` | `{name,enabled}` | 수정(enabled=false→draining 후 재할당) |
| POST | `/ai-nodes/{id}/drain` | `ai_nodes:manage` | — | 드레인(할당 비우기, 점검) |
| DELETE | `/ai-nodes/{id}` | `ai_nodes:manage` | — | soft delete + 토큰 폐기 + 재할당 |
| GET | `/ai/assignments` | `ai_nodes:manage` | — | `[AssignmentDTO]`(camera→node, state, last_report) |
| POST | `/ai/assignments/rebalance` | `ai_nodes:manage` | — | 분배 재계산 트리거 |
| PUT | `/ai/assignments/{camera_id}` | `ai_nodes:manage` | `{node_id}` | 수동 고정 할당(pin) |

#### 노드 보고/제어 API (aud=`node` 토큰 전용, `@node_token_required`)

| Method | Path | 인증 | 요청 | 응답 |
|---|---|---|---|---|
| POST | `/ai/nodes/join` | join_token(1회) 또는 node 토큰 | `{uuid?, name, gpu, gpu_name, capabilities, version, bench?}` | `{node_id, node_token, heartbeat_interval_s, assignments_etag}`(등록 확정·토큰 교부) |
| POST | `/ai/nodes/heartbeat` | node 토큰 | `{status, load:{cpu,gpu_util,vram_mb}, active_cameras:[id], fps:{cam:fps}, bench?}` | `{ok, assignments_etag, drain:bool}`(etag 변경 시 할당 재조회 지시) |
| GET | `/ai/nodes/assignments` | node 토큰 | `If-None-Match: <etag>` | `200 {etag, items:[CameraJobSpec]}` 또는 `304`(변경없음) |
| POST | `/ai/ingest/detections` | node 토큰 | `{node_id, batch:[DetectionReport], epoch_map:{camera:epoch}}` | `{accepted, rejected:[{idx,reason}]}`(epoch 불일치=stale 거부) |
| POST | `/ai/ingest/tracks` | node 토큰 | `{node_id, track_events:[{camera_id,track_key,label,state:'enter_zone'|'closed',...}]}` | `{ok}`(트리거 평가 입력; 6.8) |
| POST | `/ai/nodes/benchmark` | node 토큰 | `{results:{model_imgsz:fps, vram_mb}}` | `{ok}`(capacity 산정 반영) |

`CameraJobSpec`(서버→노드 작업 지시, `ai_config_resolver`가 생성):
```json
{ "camera_id": 123, "go2rtc_name": "cam_ab12_main", "epoch": 4,
  "model": "yolov8n", "imgsz": 640, "target_fps": 5, "min_confidence": 35,
  "labels": ["person","car","truck","bus","motorcycle","bicycle","dog","cat"],
  "zones": { "include": [[[x,y],...]], "ignore": [[[x,y],...]] },
  "clip_enabled": false, "live_overlay": false, "sample_interval_ms": 1000,
  "rtsp_url": "rtsp://axp-go2rtc:8554/cam_ab12_main" }
```
> `rtsp_url`은 go2rtc 내부 주소(자격증명 없음 — go2rtc가 소스를 들고 있음). **외부 노드**가 go2rtc에 직접 접근 못 하면, 서버가 노드별 go2rtc 노출 경로(내부망 VPN) 또는 **노드 전용 재스트림 토큰 URL**을 제공(7.5 보안).

`DetectionReport`(노드→서버 적재 단위):
```json
{ "camera_id":123, "ts":1733400000123, "epoch":4,
  "label":"person", "class_id":0, "confidence":0.87,
  "bbox":[0.41,0.55,0.48,0.79], "frame_w":1920, "frame_h":1080,
  "track_key":"a1b2...", "bytetrack_id":42,
  "attrs":{"speed_px":3.1,"area":0.012}, "crop_b64":null }
```

권한 키(PLAN §12.2 카탈로그): `detections:read` · `zones:read/update` · `triggers:read/update` · `ai:read/update` · `ai_nodes:manage`(노드/할당, admin 역할은 `{"*":["*"]}` 전권으로 통과). 노드 보고 API는 사용자 권한맵이 아닌 `@node_token_required`(aud=node). (10절 Impact, P0 권한맵 추가.)

### 5.3 controller/service 책임 분리

- **view**: 파라미터 추출·검증(없으면 `bad_request`), 권한·카메라 스코프 교집합, controller 호출, 예외→응답 매핑(`RowNotFound→404` 등). 노드 API는 `@node_token_required`(aud·jti·node.enabled 검증).
- **controller**: 트랜잭션 경계·DTO 조립. 무거운 작업(크롭 썸네일, segment 백필, 재할당)은 Celery `.delay()` 위임. 검색은 `detection_search` 서비스에 위임(쿼리 빌더).
- **service**:
  - `detection_ingest`: 보고 배치 검증(epoch·카메라 권한·범위), label 정규화(클래스맵), `track_key` 산정, zone 귀속(폴리곤 point-in-polygon = runway_monitor `zones.py` 로직 서버 이식), `segment_id` 즉시 매핑 시도(미스 시 NULL→백필), **bulk insert**(`session.bulk_insert_mappings`). 트리거 평가 입력 enqueue.
  - `detection_search`: 필터→인덱스 친화 SQL(주로 `idx_det_cam_label_ts`). `group=clip`이면 detection을 시간근접·트랙 기준으로 **클립 구간으로 병합**(연속 detection을 [min_ts-pre, max_ts+post]로 묶어 P2 playback 구간 생성). 결과 DTO에 대표 썸네일·세그먼트·카메라.
  - `object_trigger_engine`: track 상태(enter_zone/closed/sustained) + detection을 받아 트리거 규칙 평가(우선순위·cooldown·dwell·count·schedule) → 매칭 시 **P3 `event_pipeline.ingest_object(camera_id, normalized)`** 호출(또는 `handle(camera, raw, source='server')`). cooldown/디바운스는 Redis(`axp:trig:{trigger_id}:{camera}:last`·`axp:trig:track:{track_key}`).
  - `segment_linker`: ts→`segment_indexer.find` 단건/배치, detection.segment_id 갱신. 트리거 녹화는 P3 `event_clip.materialize`가 담당(중복 금지).
  - `ai_node_registry`: join(노드 생성/매칭·토큰 발급·jti 기록), heartbeat(상태·부하·last_heartbeat_ts·벤치), 상태전이(online↔degraded↔offline), drain/disable.
  - `ai_scheduler`: 분배 알고리즘(7.3) — 노드 capacity·gpu·현재부하 기준 카메라 배치, `detection_assignments` 갱신·`epoch++`, etag 갱신(Redis).
  - `ai_config_resolver`: 카메라 유효 AI 설정(전역+override) + zones + trigger labels 합집합 → `CameraJobSpec` 생성. builtin 노드용/원격 노드용 동일.

### 5.4 추론 백엔드 추상화 (워커 측 — 핵심)

`worker/detector/backends/base.py`:
```python
from dataclasses import dataclass
import numpy as np

@dataclass
class Detection:
    bbox_xyxy: tuple[float, float, float, float]  # 픽셀(파이프라인 내부), 보고 시 정규화
    confidence: float
    class_id: int
    label: str

class Detector(Protocol):
    name: str
    def warmup(self) -> None: ...                       # 모델 로드·1프레임 더미 추론
    def infer(self, frame: np.ndarray, *, imgsz: int,
              conf: float, classes: list[int] | None) -> list[Detection]: ...
    def benchmark(self, sample: np.ndarray) -> dict: ...# fps/vram 측정(노드 capacity 산정)
    @property
    def healthy(self) -> bool: ...
    @property
    def device(self) -> str: ...                        # 'cuda:0' / 'cpu' / 'remote:<url>'
    def close(self) -> None: ...

def make_detector(spec: dict) -> Detector:
    """ai_settings/노드 능력에 따라 백엔드 선택.
    우선순위: spec.force_backend > (gpu_enabled & cuda available → CudaYolo)
              > offload_to(node) → RemoteNode > CpuYolo(폴백)."""
```

- **CudaYolo**(`yolo_cuda.py`): runway_monitor `detector.py`의 `Detector`를 일반화 — `torch.cuda.is_available()`이며 `gpu_enabled`일 때. `model.to('cuda')`, `half=True`(FP16) 옵션, `imgsz`/`classes`/`conf` 파라미터화(runway는 config 상수 → 인자화). `detect_sky_zones` 같은 도메인 함수는 제거(범용 detection만). 스레드 락 유지(`_lock`).
- **CpuYolo**(`yolo_cpu.py`): `device='cpu'`, 기본 `imgsz` 축소(640/480), 모델 기본 `yolov8n`(경량). ONNX/OpenVINO int8 export 경로 옵션(속도↑). GPU 미탑재/`gpu_enabled=false` 서버 기본.
- **RemoteNode**(`remote_node.py`): 자신이 처리 못/과부하 시 **다른 노드(또는 서버 push-infer)에 프레임 추론 위임**. `infer`가 JPEG 인코딩→`POST {node_endpoint}/infer` (multipart, node 토큰)→Detection 역직렬화. 지연·대역폭 때문에 **프레임 오프로드는 최후수단**; 1차 분배는 "카메라 단위 노드 할당"(노드가 자기 카메라를 직접 처리)이고 RemoteNode는 일시 스파이크·GPU 없는 서버가 GPU 노드에 보낼 때만. (기본 전략은 7.3 카메라 할당.)
- **on/off·핫스왑**: `ai_settings.gpu_enabled` 변경 시 builtin 워커가 `make_detector` 재실행(모델 리로드). 노드는 heartbeat 응답/etag로 재구성.

### 5.5 결과 보고 프로토콜 (REST/WS/큐 — 채택)

세 후보와 선택:
- **(A) REST 배치 POST `/ai/ingest/detections`** — **채택(MVP)**. 노드가 0.5–1s 간격으로 detection을 배치 전송(HTTP keep-alive). 단순·방화벽 친화·재시도 용이. epoch로 stale 거부. 서버는 `detection_ingest`로 bulk insert.
- **(B) Redis Stream 직접 적재** — builtin 노드(서버 내부망)는 `XADD axp:det:stream`로 푸시, 서버 컨슈머가 배치 flush. 외부 노드는 Redis 직접노출 회피 → REST. (옵션: 내부 노드 고성능 경로.)
- **(C) WS 업스트림** — 라이브 오버레이용 **저장 안 하는** 실시간 bbox는 노드→서버 WS 또는 노드 FastAPI에서 직접 프론트로(서버 프록시). 저장 detection은 (A)와 분리.

> **분리 원칙**: ① 저장용 detection = REST 배치(at-least-once, epoch 멱등은 (camera,track_key,ts) 근사 + 중복 무해 검색이라 완화). ② 라이브 오버레이 = WS 메타(저장X, 손실 허용). 둘을 섞지 않음.

보고 백프레셔: 서버 ingest 큐/Redis 길이가 임계 초과 시 heartbeat 응답에 `throttle:{sample_interval_ms↑}` 지시 → 노드가 적재 빈도 감소(검색 정확도-부하 트레이드오프).

### 5.6 detection ↔ P2/P3 시간정렬 결합

- **세그먼트 매핑**: detection.ts(UTC ms) → P2 `segment_indexer.find(camera_id, ts, ts)`로 포함 세그먼트 1건 → `segment_id`. 적재 시점 즉시 매핑 실패(세그먼트 인덱싱 지연)면 NULL 두고 `detection_linker` beat(예: 30s)가 백필. 재생 오버레이는 `segment_id` 또는 (camera, ts 범위)로 조회.
- **재생 오버레이**: 프론트 플레이어가 현재 재생 구간 [t0,t1]에 대해 `GET /detections/overlay?camera_id&start=t0&end=t1` → 트랙별 시계열 bbox. 플레이어 currentTime(절대 UTC로 환산) 기준으로 보간/표시(8.3). bbox는 정규화라 비디오 표시영역에 곱셈만.
- **이벤트 결합**: 트리거가 P3 event를 만들면 그 event의 시각·recording_id가 P3에 생기고, 해당 detection.event_id를 채움 → 이벤트 상세에서 detection(객체/박스) 표시, detection 검색에서 "이벤트화됨" 배지.

---

## 6. AI 워커 (runway_monitor 확장)

> **재사용 매핑(핵심)**: 아래 표대로 runway_monitor 모듈을 그대로/일반화해 가져온다.

| runway_monitor | worker/detector | 변경 |
|---|---|---|
| `camera.py`(ffmpeg→MJPEG 캡처, 재연결/스톨감지) | `source.py` | RTSP URL을 **go2rtc 재스트림**(`rtsp://axp-go2rtc:8554/{go2rtc_name}`)으로. 카메라별 `target_fps`로 `-r` 설정. 거의 그대로 |
| `detector.py`(YOLO 래퍼, 락) | `backends/yolo_cuda.py`·`yolo_cpu.py` | 도메인 함수(sky crop) 제거, `imgsz/conf/classes` 인자화, `Detector` Protocol 구현, CPU/CUDA 분리 |
| `tracker.py`(ByteTrack + TrackedObject) | `tracker.py` | 거의 그대로(궤적/속도/면적). aircraft 전용 속성만 범용화 |
| `zones.py`(폴리곤 ROI, point_in_polygon) | `zones.py` | runway/sky → `include/ignore` 일반화, JSON 파일 → **서버 detection_zones 동기화** |
| `clip_filter.py`(CLIP 2차검증) | `clip_filter.py` | 그대로(REJECT/ACCEPT 라벨을 일반 객체로 확장, 옵션) |
| `pipeline.py`(capture→detect→track→annotate) | `camera_pipeline.py` | annotate를 옵션화(라이브 오버레이만), **sample+report 단계 추가**, state_machine 제거 |
| `small_object_detector.py` | (보류) | 일반 NVR에 불필요. P6 카운팅/원거리 옵션으로 유보 |
| `state_machine.py`(항공기 상태) | (제거) | 도메인 특수. 트리거는 `object_trigger_engine`(서버측)이 담당 |
| `server.py`(FastAPI MJPEG/WS/zone API) | `server.py`(옵션) | zone API 제거(서버 DB가 소유), `/healthz`·`/benchmark`·라이브 어노 MJPEG·push-infer만 |
| `main.py`(uvicorn) | `main.py` | **서버 join→할당 폴링→파이프라인 슈퍼바이저** 기동으로 재작성 |
| `config.py` | `config.py` | 카메라 하드코딩 제거 → 서버에서 `CameraJobSpec` 수신 |

### 6.1 워커 부팅·런타임 시퀀스 (`main.py` + `node_agent.py`)

```
1. env 로드: SERVER_API_URL, NODE_TOKEN(or JOIN_TOKEN), GPU_ENABLED, NODE_NAME, BACKENDS
2. 백엔드 가용성 탐지: torch.cuda.is_available(), 모델 목록 → capabilities
3. (선택) 벤치마크: 더미 프레임으로 후보 모델 fps/vram 측정 → bench
4. node_agent.join(): POST /ai/nodes/join {capabilities, gpu, bench} → node_id, node_token, etag
5. 슈퍼바이저 루프:
   - 주기(heartbeat_interval, 예 5s) POST /ai/nodes/heartbeat {load, active_cameras, fps}
       → 응답 etag 변경 or drain 시 할당 재조회
   - GET /ai/nodes/assignments (If-None-Match: etag) → CameraJobSpec[] (304면 유지)
   - reconcile(specs): 신규 카메라 → CameraPipeline.start(); 제거 → stop(); 변경(model/fps/zone/epoch) → 재구성
6. 각 CameraPipeline: source(go2rtc)→backend.infer→tracker→zone필터→sample→ingest 큐
7. node_agent.reporter: detection 배치(0.5–1s)·track_event를 POST /ai/ingest/* 로 전송(epoch 동봉)
8. 종료(SIGTERM): drain 보고→파이프라인 stop→detector.close
```
- **builtin 노드**(`axp-detector` 컨테이너)는 동일 코드. 단 SERVER_API_URL=내부, NODE_TOKEN=서버가 부팅 시 생성한 builtin 토큰(또는 localhost 신뢰). builtin은 항상 `ai_nodes(kind='builtin')` 1행에 매핑.
- **외부 노드**: 별도 머신에서 같은 이미지(GPU 베이스) + JOIN_TOKEN으로 join.

### 6.2 `camera_pipeline.py` 처리 루프 (runway pipeline.py 기반)

```python
def _process_loop(self):
    while self._running:
        frame, frame_id = self.source.get_frame()         # source.py (go2rtc MJPEG)
        if frame is None or frame_id == self._last: sleep; continue
        ts = source.frame_wallclock_ms()                   # 6.6 시각
        dets = self.backend.infer(frame, imgsz=self.imgsz, # backends/*
                                  conf=self.conf, classes=self.class_ids)
        dets = self.zones.filter(self.camera_id, dets, frame.shape)   # zones.py(include/ignore)
        if self.clip_filter and self.clip_filter.enabled:  # 옵션 2차검증
            dets = [d for d in dets if not self.clip_filter.should_reject(frame, d.bbox_xyxy, d.label)]
        tracked = self.tracker.update(dets)                # tracker.py(ByteTrack)
        # 트랙 상태 이벤트(진입/종료) 산출 → track_event 큐
        self._emit_track_events(tracked)                   # 6.8
        # 적재 다운샘플: 트랙 생성/종료/ sample_interval 경과한 트랙만 detection 보고
        reports = self._sample(tracked, ts)                # 6.7
        if reports: self.report_q.put(reports)
        if self.live_overlay:                              # 옵션
            self.annotated = self.annotator.annotate(frame, tracked)
```
- FPS 제한: `source.py`의 ffmpeg `-r target_fps` + 루프에서 frame_id 변경분만 처리(이중 안전). 추론이 target_fps를 못 따라가면 최신 프레임만(프레임 드롭, 큐 비적재).
- 좌표: 파이프라인 내부는 픽셀, **보고 직전 frame_w/h로 0–1 정규화**(해상도 독립 저장).

### 6.3 GPU on/off · CPU · 외부노드 (성능 한계 대응 — 핵심)

- **GPU off (단일서버 CPU)**: `ai_settings.gpu_enabled=false` → builtin `make_detector`=CpuYolo. 현실적 한계: CPU YOLOv8n@640은 코어수에 따라 **수 fps/카메라**. → `target_fps`를 1–3으로 낮추고, 카메라별 detection_enabled로 **중요 카메라만** AI. UI가 "CPU 모드 — 카메라 N대×Xfps 권장" 경고.
- **GPU on (단일서버 1 GPU)**: CudaYolo. YOLOv8m@1280 한 GPU에 ~수십 fps 총량 → `capacity` = 총 fps / (카메라당 target_fps)로 산정. 초과하면 분배 스케줄러가 **수용 못하는 카메라를 pending**으로 두고 UI 경고("GPU 용량 초과: 외부 노드 추가 또는 fps/모델 하향").
- **외부 노드 오프로드(스케일아웃)**: GPU 노드를 join시키면 `ai_scheduler`가 초과 카메라를 그 노드로 **재할당**(카메라 단위, 노드가 직접 go2rtc에서 취득). 서버 GPU가 없거나 약하면 전부 외부 노드로. **프레임 단위 오프로드(RemoteNode)**는 외부 노드가 go2rtc에 접근 불가한 폐쇄망에서의 폴백(서버가 프레임을 노드에 push). 비용 큼 → 가급적 카메라 단위.
- **혼합 운영**: builtin(서버 GPU) + 외부 노드 N개가 capacity 합으로 카메라를 나눠 가짐. 한 노드 장애 시 그 카메라들이 남은 capacity로 재할당(7.4). capacity 부족분은 pending + 경고.
- **모델 손잡이**: `yolov8n`(빠름/저정확) ↔ `yolov8m`(느림/고정확) ↔ `yolov8s`. imgsz(320–1280)·target_fps·labels 축소가 부하 손잡이. AiSettings UI에서 조절, 실측 capacity 반영.

### 6.4 클래스/라벨 정규화

- COCO 기본 매핑(`label_map.py`): `{0:person,1:bicycle,2:car,3:motorcycle,5:bus,7:truck,14:bird,15:cat,16:dog,...}`. 검색·트리거는 정규화 `label` 사용(모델 교체에도 일관). 비-COCO 모델은 모델별 매핑표 등록.
- 기본 검출 화이트리스트(NVR 보안 관점): person/car/truck/bus/motorcycle/bicycle/dog/cat(+bird 옵션). `ai_settings.labels`로 조정 → `classes` 인자로 추론 시 필터(불필요 클래스 추론 비용↓).

### 6.5 zones (runway_monitor zones.py 일반화)

- 서버 `detection_zones`를 노드가 `CameraJobSpec.zones`로 수신(정규화 폴리곤). 워커 `zones.py`는 runway의 `point_in_polygon`·`bottom_center`·`is_in_ignore_zone` 그대로, runway/sky 특수 분기 제거하고 `include`(합집합 안만)·`ignore`(차집합) 2종으로 필터.
- detection 적재 시 zone 귀속은 **서버 `detection_ingest`**가 수행(노드는 필터만; zone_id는 서버 DB id라 서버가 권위). 노드는 어떤 include zone을 통과했는지 힌트만 동봉 가능.

### 6.6 시각 정렬 정책

- detection.ts = **go2rtc 프레임 수신 벽시계(UTC ms)**. 카메라 RTP 타임스탬프 신뢰 불가·노드 시계 드리프트 가능 → 노드는 `ts`를 자기 monotonic이 아닌 **wallclock**으로 찍되, join/heartbeat 시 서버와 **시계 오프셋**(`server_now - node_now`)을 측정해 보고 ts에 보정(NTP 권장, 보정은 안전망). 서버 ingest가 |ts - server_now| 과대(예 >5s)면 server_now로 클램프(13절).
- P2 세그먼트도 벽시계 정렬(`-segment_atclocktime`) → detection.ts와 동일 기준 → `segment_indexer.find`로 정확 매핑.

### 6.7 detection 적재 다운샘플 정책 (행 폭증 억제)

트랙당 모든 프레임을 저장하지 않고:
1. **트랙 생성**(첫 확정 N프레임) 시 1행.
2. **트랙 종료**(lost) 시 1행(마지막 위치).
3. 지속 트랙은 `sample_interval_ms`(기본 1s)마다 1행.
4. **트리거/이벤트화·구역 진입** 순간은 무조건 1행(검색·증거).
→ 사람 1명 10초 체류 = 약 12행(0/종료/10샘플 근사). 검색·오버레이는 트랙 보간으로 충분. (정밀 오버레이가 필요하면 라이브 WS 또는 store_crops로 보강.)

### 6.8 객체 트리거 평가 (`object_trigger_engine`, 서버측)

- 노드는 **track_event**(`enter_zone`, `closed`, `sustained@dwell`)와 detection을 보고. 서버 `object_trigger_engine`이 카메라의 트리거 규칙을 로드(캐시)해 평가:
```
on track_event/detection:
  trigs = triggers_for(camera)  # (camera) > (global), enabled, schedule active
  for t in trigs:
    if label not in t.labels: continue
    if t.zone_id and not in_zone(det, t.zone_id): continue
    if confidence < t.min_confidence: continue
    if t.require_zone_entry and event != 'enter_zone': continue
    if t.min_dwell_ms and track.dwell < t.min_dwell_ms: continue
    if t.min_count and concurrent_same_label(camera,zone) < t.min_count: continue
    if t.debounce_per_track and seen(track_key, t.id): continue
    if within_cooldown(t.id, camera, t.cooldown_s): continue       # Redis
    # 매칭 → P3로 승격
    normalized = { type:'object', subtype:t.event_subtype or label,
                   source:'server', start_ts:det.ts, score:confidence,
                   region:{w:1,h:1,shapes:[{kind:'box',...bbox}]},
                   raw:{trigger_id:t.id, track_key, label, node_id} }
    P3.event_pipeline.ingest_object(camera_id, normalized)         # 선행의존 #1
    mark_trigger(t.id, camera); mark_track(track_key, t.id)
    # detection.event_id 백필은 P3가 event 생성 후 콜백/조회로 연결
```
- **디바운스/쿨다운**: track 단위(`debounce_per_track`) + 시간 단위(`cooldown_s`). 둘 다 Redis(원자 SET NX EX). P3가 다시 정책 cooldown을 적용하므로 이중 안전.
- **녹화/알림은 P3가 결정**: P4는 event를 만들 뿐, record/notify/discard는 P3 `event_policy_resolver`+`schedule`이 판단(전후버퍼 회수=P3 `event_clip.materialize`). 객체 트리거 전용 녹화를 원하면 P3 `event_policies`에 `type='object'` 정책을 두면 됨(설정으로 일원화).

### 6.9 라이브 오버레이(옵션)

- `ai_settings.live_overlay_enabled` 시: 노드 `annotator.py`가 어노테이트 프레임 MJPEG를 노드 FastAPI(`/overlay/{camera}`)로 송출 → 서버가 프록시(JWT+scope). 또는 **메타만 WS**(`/cameras/{id}/detections/live`)로 보내 프론트가 WebRTC 라이브 위에 SVG 오버레이(저비용, 권장). 기본은 메타 WS.
- 비용 경고: 어노 MJPEG는 인코딩·대역폭 부담 → 기본 off, 메타 WS 우선.

---

## 7. 분산 AI

### 7.1 모델 개요

- **권위 = 서버**(`ai_nodes`/`detection_assignments`/Redis etag). 노드는 stateless 실행체(할당받은 카메라를 직접 go2rtc에서 처리·보고).
- **builtin 노드**(서버 내장 `axp-detector`)와 **remote 노드**(외부 머신)가 동일 프로토콜. 단일 서버만 운영해도 builtin 1노드로 동작(분산은 노드 추가로 자연 확장).
- 통신: 노드→서버 **REST(join/heartbeat/assignments/ingest)**. 서버→노드는 **풀 기반**(노드가 polling, etag) — 방화벽/NAT 친화(외부 노드가 서버로만 아웃바운드). push 제어(`ai_node_client`)는 옵션.

### 7.2 join 프로토콜 (등록·인증·하트비트)

**시퀀스:**
```
[관리자]  POST /ai-nodes {name, kind:'remote'}            → {node_id, join_token(1회용, TTL 30m, aud=node-join)}
[노드설치] 환경변수 JOIN_TOKEN=... SERVER_API_URL=...
[노드]    POST /ai/nodes/join
            Authorization: Bearer <join_token>
            body {name, gpu, gpu_name, capabilities, version, bench}
[서버]    join_token 검증(aud=node-join, 미사용) → ai_node 갱신(uuid 생성/매칭)
          TokenService.issue_node_token(node.uuid, ttl=ai default 30d)  # aud='node', sub=uuid, jti
          node.token_jti=jti; status='online'; last_heartbeat_ts=now
          → 200 {node_id, node_token, heartbeat_interval_s, assignments_etag}
[노드]    이후 모든 호출 Authorization: Bearer <node_token>
          loop: POST /ai/nodes/heartbeat {load, active_cameras, fps}
                 → {ok, assignments_etag, drain}
                GET /ai/nodes/assignments (If-None-Match) → specs or 304
                POST /ai/ingest/detections {batch, epoch_map}
```
- **인증**: `node_token` = P0 TokenService scoped(aud=`node`, sub=node.uuid, jti). 검증기 `@node_token_required`: aud=node·jti=ai_nodes.token_jti(일치)·node.enabled·deleted_at NULL. **토큰 폐기/회전**: admin `/ai-nodes/{id}/token` 재발급 시 이전 jti를 Redis denylist + token_jti 교체(노드는 다음 호출 401→재join 또는 새 토큰 배포). 노드 삭제 시 denylist.
- **join_token**(1회용 부트스트랩): aud=`node-join`, node_id 바인딩, Redis `axp:nodejoin:{jti}` 1회 소비(사용 시 삭제). 유출 영향 최소화(짧은 TTL·1회).
- **하트비트/장애판정**: `last_heartbeat_ts` < now - 3×interval → `ai_supervise` beat가 status=offline 전이 + 그 노드 할당 재배치(7.4). 노드 부하(gpu_util/vram)는 분배·throttle 입력.

### 7.3 카메라 → 노드 분배 (로드 분배)

- **단위**: 카메라(스트림) 단위 할당(프레임 단위 분할 회피 — 트래킹 연속성·구현 단순). 한 카메라는 1노드(`uq_assign_cam`).
- **capacity**: 노드 `capacity` = 벤치(fps_per_cam_model_imgsz)·gpu·vram로 산정한 "동시 카메라 수". heartbeat의 실측 fps로 보정(목표 fps 미달 시 capacity 하향).
- **알고리즘**(`ai_scheduler.rebalance`):
  ```
  cams = detection_enabled 카메라(전역+카메라 설정)
  nodes = enabled & online, weight = capacity (gpu 우선 가중)
  # 1) 기존 active 할당 유지(이동 최소화, 트랙·연결 안정)
  # 2) 미할당/ pending 카메라를 잔여 capacity 큰 노드에 배치(최대여유 우선, bin-packing greedy)
  # 3) 특정 카메라 모델/fps 요구(무거움)는 gpu 노드 우선
  # 4) 수용 초과분 → state='pending'(미처리) + 경고 메트릭
  # 변경된 카메라: assignment.node 갱신, epoch++, etag 재생성(Redis axp:ai:assign:etag)
  ```
- **트리거**: 노드 join/leave/offline, 카메라 add/remove(P1 시그널)/detection_enabled 변경, `ai_settings` 변경, 수동 rebalance, 주기 reconcile(beat).
- **수동 pin**: admin `PUT /ai/assignments/{camera_id}{node_id}` → 해당 카메라 고정(스케줄러 제외 플래그).
- **안정성**: 잦은 재할당(플래핑) 방지 — 노드 offline 판정에 히스테리시스(연속 N회 미스), 재배치는 최소 이동.

### 7.4 장애 복구 (재할당)

- 노드 offline(하트비트 끊김) 또는 admin drain/disable/delete →
  1. `ai_supervise`가 그 노드의 `detection_assignments`를 `reassigning`으로 마킹.
  2. `ai_scheduler.rebalance`가 해당 카메라들을 남은 노드 잔여 capacity로 재배치(없으면 pending + 경고).
  3. epoch++·etag 갱신 → 남은 노드가 다음 폴링에서 새 카메라 픽업, 죽은 노드가 살아 돌아와도 **epoch 불일치로 그 카메라 보고는 거부**(중복 처리 방지).
  4. 죽은 노드 복귀 → join/heartbeat로 online → 다음 rebalance에서 다시 카메라 받음(빈 capacity 한도).
- **builtin 노드 장애**(서버 detector 컨테이너 다운): 외부 노드 있으면 그쪽으로, 없으면 전체 pending(AI 일시 중단) — 라이브/녹화(P1/P2)는 무관하게 계속(AI는 부가). UI 명확 경고.
- **부분 저하**(노드 과부하): heartbeat throttle 지시(sample_interval↑/target_fps↓) 또는 일부 카메라 다른 노드 이동.

### 7.5 분산 보안

- 노드 인증 = aud=node scoped 토큰(jti 폐기 가능). join은 1회용 토큰. 노드 API는 **사용자 권한맵과 완전 분리**(`@node_token_required`만; 사용자 토큰으로 ingest 불가, 노드 토큰으로 사용자 API 불가).
- ingest 데이터 검증: camera_id가 그 노드에 **할당된 카메라인지** 확인(타 카메라 위조 적재 차단), epoch 검증(stale 거부), bbox/conf 범위·크기 제한(과대 페이로드 방지).
- 외부 노드의 go2rtc 접근: 기본은 **내부망/VPN으로 go2rtc RTSP 직접**. 노출 불가 시 서버가 노드별 **단기 재스트림 토큰 URL** 제공(go2rtc 앞 프록시 인증) 또는 프레임 push(RemoteNode). go2rtc를 인터넷에 직접 노출 금지.
- 전송 보안: 외부 노드↔서버는 TLS(리버스프록시). 노드 토큰·detection·크롭은 평문망 금지.
- 감사: 노드 join/토큰발급/삭제/재할당을 `audit_logs`(action=`ai_node_joined`/`ai_node_token_issued`/`ai_node_removed`/`ai_reassigned`).

---

## 8. 프론트엔드 (TS) — DESIGN.md 적용

> React 18 + Vite 7 + TS + Tailwind + Radix/shadcn + TanStack Query/Table + dnd-kit. ams 패턴(페이지별 디렉터리, `@`=`src/`, Axios+JWT 인터셉터, i18n ko/en). 디자인 = **Tesla 미니멀**: 다크 캔버스(`--axp-canvas #171A20`) 위 순백 UI 패널, 그림자·그라데이션·테두리 지양(구분은 spacing·1px `#EEEEEE`), 단일 액센트 **Electric Blue `#3E6AE1`**(주 CTA·활성/선택·오버레이 박스), 4px 라운드(큰 카드 12px), 0.33s 트랜지션, 텍스트 Carbon/Graphite/Pewter. **영상·스냅샷이 주인공** — detection 검색은 크롭/프레임 썸네일을 전면에, UI 크롬 최소.

페이지/컴포넌트 (`frontend/src/pages/ai/`, `.../cameras/detection-zones/`, 공용 `components/`):

### 8.1 `ObjectSearch` (`pages/ai/ObjectSearch.tsx`) — 스마트 서치
- 상단 필터 바(흰 패널): 카메라 멀티선택, **클래스 칩**(person/car/truck/dog/...; 아이콘+라벨, 선택=Electric Blue 텍스트/연한 blue 배경, 4px), 기간 프리셋(1h/24h/7d/커스텀), 구역 선택, min_confidence 슬라이더(Electric Blue 트랙). URL 쿼리 동기화.
- 결과: **썸네일 카드 그리드**(2:1, 12px 라운드, overflow hidden — DESIGN 카드 규칙). 카드 = 대표 크롭/프레임(`/detections/{id}/snapshot` 또는 group 대표) 전면, 좌상단 라벨/시각(흰 텍스트, 그림자 없이 이미지 어둠 의존), 우측 conf%·카메라명·track 길이. `group=clip` 기본(클립 단위 묶음). 무한스크롤(TanStack Query 페이지네이션).
- 카드 클릭 → `DetectionPlayer`(P2 playback 클립 플레이어 재사용) 모달/페이지, `DetectionOverlay` 켬. "타임라인에서 보기" → `DetectionTimeline` 해당 시각.
- 빈 상태/CPU 모드: AI 비활성 카메라·검색 결과 없음·성능 모드 안내(절제된 텍스트).

### 8.2 `DetectionTimeline`
- 가로 시간축. **coverage 바**(P2 녹화 구간) = 얕은 회색(`#EEEEEE`), detection 마커 = 클래스별 절제 색 점/틱(기본 Carbon, 선택 Electric Blue), 밀집 시 `bucket` 묶음 개수 배지. `GET /detections/timeline`.
- 마커 hover = 미니 썸네일 미리보기(사진 우선). 클릭 = 클립 재생. P2/P3 타임라인 컴포넌트와 **레인 공유**(같은 축에 녹화/이벤트/detection 레이어 토글) — 코드 재사용.

### 8.3 `DetectionOverlay` (재생 + 라이브 공용)
- 비디오 위 절대배치 SVG/Canvas. 재생 모드: `GET /detections/overlay?camera&start&end`로 트랙 시계열 bbox 수신, 플레이어 `currentTime`(→절대 UTC ms 환산) 기준 가장 가까운 샘플 보간 표시. bbox는 0–1 정규화 → 비디오 **표시영역**(letterbox 고려)에 곱. `ResizeObserver`로 리사이즈 추종(P3 MotionOverlay와 동일 패턴 재사용).
- 스타일: 박스 = Electric Blue 1.5px 외곽선 + 라벨 칩(라벨/conf, 흰 텍스트/blue 배경, 4px), 트랙 경로 = 얇은 반투명 polyline. 그림자 없음. 클래스별 색은 절제(기본 blue, 다중 클래스 구분 필요 시 톤만 변주).
- 라이브 모드: `/cameras/{id}/detections/live` WS 메타를 WebRTC 라이브뷰(P1) 위에 동일 렌더(저지연). 토글로 on/off.

### 8.4 `ZoneEditor` (`pages/cameras/detection-zones/`)
- runway_monitor `calibrate` 페이지를 **React+TS 컴포넌트로 이식**: 카메라 스냅샷(`/cameras/{id}/snapshot` 또는 P2 `frame`) 배경 + Canvas 오버레이. 폴리곤 클릭으로 점 추가, **드래그 이동**, 우클릭 삭제(런웨이 calibrate UX 계승). 모드 = `include`(검출영역)/`ignore`(무시영역) 토글(활성 = Electric Blue/회색 톤).
- 좌표는 표시→**0–1 정규화** 저장. 다중 구역(이름·색·label_filter). 저장 시 `POST/PUT detection-zones` → detector에 즉시 시그널(Redis). 라벨 필터·enabled 토글.
- 디자인: 영상 위 폴리곤 채움 반투명 + Electric Blue 외곽선, 점은 작은 원, 컨트롤 바는 순백·4px·그림자 없음.

### 8.5 `AiNodes` (`pages/ai/AiNodes.tsx`, admin)
- 노드 카드/테이블(TanStack Table): 이름·kind(builtin/remote)·status(online=Electric Blue 점, degraded=회색, offline=Pewter)·gpu/gpu_name·capacity·**현재부하**(assigned/capacity 막대, Electric Blue)·fps·last_heartbeat·version.
- 액션: 노드 추가(remote) → **join_token + 설치 안내**(docker run 예시, env) 모달(1회용 토큰 복사, 보안 경고). 토큰 재발급, drain, enable/disable, 삭제. 할당 보기(이 노드가 처리 중인 카메라 목록).
- 용량 경고 배너: pending 카메라(수용 초과) 있으면 상단 경고("GPU 용량 초과 N대 미처리 — 노드 추가 또는 모델/fps 하향") + rebalance 버튼.

### 8.6 `AiAssignments` (admin, AiNodes 내 탭 가능)
- 카메라→노드 매핑 테이블(state/last_report/epoch/fps). 수동 pin(드롭다운으로 노드 변경), rebalance 트리거. pending 카메라 강조.

### 8.7 `AiSettings` (`pages/ai/AiSettings.tsx`) — GPU 토글 등
- 전역 카드(흰 패널): **GPU 사용 토글**(Switch, Electric Blue) + 상태 표시("GPU 감지됨: RTX 4070 / GPU 없음 — CPU 모드"), 기본 모델 Select(yolov8n/s/m), 기본 target_fps·imgsz 슬라이더, min_confidence, 기본 검출 클래스 멀티선택, CLIP 토글, 라이브 오버레이 토글, store_crops 토글, retention_days.
- GPU off→on 토글 시: 즉시 builtin 재구성(로딩 인디케이터), capacity 재측정. **성능 가이드 인라인**: 현재 카메라 수·설정으로 예상 부하/수용 가능 여부(서버 capacity 응답 반영) 안내.
- 카메라별 override 서브패널(카메라 선택 → detection_enabled/model/fps/zone 요약). DESIGN: 토글·슬라이더 단색·4px, 그림자 없음.

### 8.8 `ObjectTriggers` (`pages/ai/ObjectTriggers.tsx`)
- 트리거 목록/CRUD(TanStack Table/폼): 이름·카메라(전역/특정)·labels(칩)·zone·min_confidence·dwell·zone_entry·count·cooldown·schedule·notify·enabled. "테스트"(`/object-triggers/test`)로 매칭 프리뷰. P3 정책과의 관계 안내(녹화/알림은 이벤트 정책에서 결정) 툴팁.

### 8.9 실시간/접근성/i18n
- P0 WS 허브: detection 라이브(scope), 노드 상태 변경 토스트(sonner, 절제 단색·0.33s 페이드). 라이브뷰 타일에 객체 감지 시 작은 배지(클래스 점).
- ko/en 전 라벨(클래스명·상태·액션). 시각 KST 표시(UTC ms→포맷). 터치 타깃 ≥44px, 키보드 내비, 칩/슬라이더 ARIA.

---

## 9. 작업 분해 (순서 있는 체크리스트)

1. **선행 계약 확정(블로킹, 3절)**: P3 객체 event 진입점 시그니처(`ingest_object` vs `handle`), `events.type='object'`/`source='server'`; P2 `segment_indexer.find`·recordings 생성/병합·playback 스키마; P0 scoped 토큰(aud=node) 발급 확장; P1 main `go2rtc_name` 규칙. (미확정 시 14절·AskUserQuestion.)
2. **모델/마이그레이션**: `detections/detection_zones/object_triggers/ai_nodes/detection_assignments/ai_settings`(+옵션 detector_health) SQL·SQLAlchemy 모델·`to_dict`. P0 권한맵에 `detections:read`·`zones:read/update`·`triggers:read/update`·`ai:read/update`·`ai_nodes:manage` 추가(PLAN §12.2). 전역 `ai_settings` 1행·builtin `ai_nodes` 시드.
3. **백엔드 추론 추상화(워커)**: `backends/base.py`(Detector Protocol/Detection) → `yolo_cpu.py`(기본) → `yolo_cuda.py`(runway detector.py 일반화) → `make_detector` 팩토리·벤치. unit(가짜 모델로 인터페이스).
4. **워커 코어**: `source.py`(go2rtc MJPEG, runway camera.py 이식) → `tracker.py`(runway 이식) → `zones.py`(include/ignore 일반화) → `camera_pipeline.py`(capture→infer→zone→track→sample→report) → `clip_filter.py`(옵션) → `annotator.py`(옵션).
5. **노드 에이전트·프로토콜**: `node_agent.py`(join/heartbeat/assignments 폴링/etag/reporter) + 서버 `view/api/ai_ingest.py`·`ai_node.py`·`service/ai_node_registry.py`. `@node_token_required` 가드(P0 토큰 aud=node). join 시퀀스 e2e(mock 노드).
6. **detection 수집·적재**: `service/detection_ingest.py`(검증·정규화·track_key·zone 귀속·bulk insert·epoch) + `segment_linker`·`task/detection_linker.py`(segment_id 백필).
7. **분배 스케줄러**: `service/ai_scheduler.py`(rebalance·capacity·bin-packing) + `detection_assignments` + `ai_config_resolver`(CameraJobSpec) + `task/ai_supervise.py`(beat: 헬스 스윕·재할당). 장애 재할당 integration.
8. **객체 트리거 엔진**: `service/object_trigger_engine.py`(평가·디바운스·cooldown·dwell·zone_entry·count) → P3 `ingest_object` 호출. `view/controller object_trigger.py` CRUD·test. unit(결정·디바운스).
9. **검색·타임라인·오버레이 API**: `service/detection_search.py`(쿼리 빌더·clip 그룹핑) + `view/controller detection.py`(search/timeline/overlay/snapshot/{id}). 카메라 스코프 교집합. 썸네일(`task/ai_crop_thumb.py`, P2 frame 재사용).
10. **AI 설정·GPU 토글**: `ai_settings` view/controller + `ai_config_resolver`(유효설정 병합) + 토글 시 builtin/노드 재구성 시그널(Redis etag/`gpu_enabled`).
11. **프론트**: AiSettings(GPU 토글) → ZoneEditor → ObjectSearch+DetectionPlayer+DetectionOverlay → DetectionTimeline → ObjectTriggers → AiNodes/AiAssignments → 라이브 오버레이/배지. i18n.
12. **컨테이너**: `worker/detector/Dockerfile`(CPU/GPU 2-스테이지), docker-compose `axp-detector`(builtin) GPU `deploy.resources` 분기, 외부 노드 배포 문서.
13. **보존**: `task/detection_retention.py`(파티션 DROP/배치 DELETE·크롭 정리), retention_days.
14. **테스트 전수**(12절) + 회귀(P1 라이브/P2 녹화·재생/P3 이벤트가 P4 도입 후 정상).
15. **문서 갱신**: 14절 해소분 PLAN·본 문서 반영, 10절 Impact 확정.

---

## 10. 다른 기능/Phase에 미치는 영향 (Cross-feature Impact) ★

| 대상 | 영향 | 조치 |
|---|---|---|
| **P3 `events`** | `type='object'`·`source='server'` 발행. detection→event 어댑터(`ingest_object` 또는 `handle`) 필요. event.region에 bbox(정규화), recording_id 연결 | P3와 진입점 시그니처 합의(권장 `ingest_object`). P3가 이미 object/server 예약(phase-3 §4.1·§6.4) → 정합 확인. **녹화/알림 결정은 P3 정책**(중복 구현 금지) |
| **P3 `event_pipeline`/`event_clip`** | 객체 트리거 녹화 = P3 정책+전후버퍼 회수 재사용 | P4는 event만 발행, materialize는 P3 호출. `event_policies`에 `type=object` 정책 설정으로 일원화 |
| **P3 `event_policies`/`schedules`** | 객체 이벤트도 정책·스케줄 윈도 적용. `object_triggers.active_schedule_id`가 P3 `schedules` 재사용 | schedules 테이블 공유(녹화 스케줄=AI 활성창 겸용 가능) 합의 |
| **P2 `segments`/`segment_indexer`** | detection.ts→segment 매핑(시간정렬), 검색 클립 재생, frame 추출(썸네일) | `segment_indexer.find` 시그니처 사용. 매핑 지연→백필 |
| **P2 `recordings`** | 트리거 녹화는 P3 경유 P2 생성(reason='event'). detection 자체는 recordings 불요 | P3가 이미 사용하는 경로 재사용 |
| **P2 playback** | 검색결과·오버레이 재생에 playback 클립/타임라인/frame 재사용. 타임라인에 detection 레이어 추가 | playback 컴포넌트·API 공유, 타임라인 레인 확장 |
| **P1 `cameras`/`streams`** | detector가 카메라 목록·`go2rtc_name`(main) 소비. add/remove/enable→할당 갱신 | P1 카메라 CRUD 시그널 구독(ai_scheduler 재배치). main 스트림 식별 규칙 |
| **P1 go2rtc** | detector·외부노드가 go2rtc RTSP에서 프레임 취득(카메라당 소스 1연결 공유 — 부하 무관) | 외부 노드의 go2rtc 접근 경로/보안(7.5). go2rtc 소스 connection 수 모니터 |
| **P0 권한맵** | `detections:read`·`zones:read/update`·`triggers:read/update`·`ai:read/update`·`ai_nodes:manage` 신설(PLAN §12.2), admin 전권 | P0 권한 카탈로그·UI 권한편집에 키 추가 |
| **P0 토큰서비스** | aud=`node` scoped 토큰 **발급**(현재 검증기만) + `node-join` 1회용 토큰 | P0 TokenService에 `issue_node_token`/`issue_join_token` 추가(P0 §5.2 aud 분기 확장) |
| **P0 WS 허브** | `detections`(라이브 오버레이, scope)·`ai_nodes`(상태) 채널 | 허브에 채널·스코프 필터 등록 |
| **P0 Celery/큐** | detection ingest 후처리·재할당·보존·썸네일 큐(녹화/구독 큐와 분리) | `ai` 전용 큐 또는 기존 후처리 큐. detection ingest는 가능하면 Redis Stream 컨슈머 |
| **P0 docker-compose** | `axp-detector`(builtin) GPU 분기(`deploy.resources.reservations.devices`), 외부 노드 이미지 | compose GPU 프로파일, 외부 노드 배포 문서 |
| **P5 자동화/알림** | detection→events(object)·signals를 트리거로 소비("사람 감지 시 스피커") | P4는 발행만, P5가 규칙 평가·전송 |
| **P6 고급 AI** | `detections.attrs`·crop·track·노드 인프라 위에 LPR/face/카운팅/시맨틱 확장. 시맨틱은 임베딩 인덱스 추가 | attrs JSON·crop 저장 자리 예약. 노드 capabilities에 모델군 추가 |
| **보존/스토리지** | `detections` 대량 증가(고빈도). 크롭 스냅샷 용량 | 다운샘플(6.7)+파티션+retention_days+store_crops 기본 off |

---

## 11. 리스크 & 완화

| 리스크 | 영향 | 완화 |
|---|---|---|
| 단일서버 GPU/CPU 용량 부족(카메라 다수) | detection 누락·지연 | capacity 산정·pending 경고·외부 노드 오프로드(7), target_fps/모델/labels 손잡이, 중요 카메라만 AI |
| CPU 모드 성능 한계(저fps) | 빠른 객체 놓침 | UI 명시·target_fps 권장치·yolov8n·imgsz 축소, GPU/노드 권유. detection은 보조(녹화/이벤트는 P2/P3 독립) |
| `detections` 행 폭증 | 쿼리·스토리지 부담 | 트랙 다운샘플(6.7)·인덱스·월 파티션·retention_days·bbox JSON 경량 |
| 노드 시계 드리프트 → 시간정렬 오차 | 검색/오버레이/세그먼트 매핑 어긋남 | NTP 권장 + join/heartbeat 오프셋 보정 + ingest 클램프(6.6) |
| 외부 노드 join 토큰 유출 | 무단 노드·위조 적재 | 1회용 join 토큰(짧은 TTL)·scoped node 토큰(jti 폐기)·할당 카메라만 적재 허용·TLS |
| 재할당 플래핑(노드 불안정) | 트랙 끊김·재연결 폭주 | 히스테리시스 offline 판정·최소 이동 재배치·epoch로 stale 거부 |
| 프레임 단위 오프로드(RemoteNode) 지연·대역폭 | 처리율 저하 | 기본은 카메라 단위 할당, RemoteNode는 폐쇄망 폴백만. JPEG 품질/해상도 축소 |
| go2rtc 인터넷 노출(외부 노드) | 미디어 무단접근 | 내부망/VPN 우선·프록시 인증 재스트림 토큰·직접 노출 금지(7.5) |
| 모델 오탐(그림자·반사·유사물) | 검색/트리거 노이즈 | min_confidence·CLIP 2차검증(옵션)·ignore zone·dwell/count 트리거 조건 |
| YOLO 라이선스(ultralytics AGPL) | 배포 제약 | 오픈소스 AGPL 준수 또는 상용 라이선스·대체 모델(YOLOX 등) 경로 문서화(14절) |
| ingest at-least-once 중복 | 중복 detection 행 | 검색 무해(그룹핑)·근사 dedup(camera,track_key,ts 버킷)·epoch |
| GPU 토글 핫스왑 중 추론 공백 | 짧은 detection 중단 | 재구성 중 라이브/녹화 무관 지속, UI 로딩 표시, 빠른 모델 리로드 |

---

## 12. 테스트 계획 (unit/integration/e2e)

**Unit**
- `backends`: 가짜 모델 주입으로 `Detector` 계약(infer 좌표/라벨/conf), `make_detector` 선택 로직(gpu_enabled·cuda 가용·offload 분기), 정규화 좌표 변환 경계.
- `zones.filter`: include/ignore 합·차집합, point_in_polygon 경계(runway 로직 재사용 검증), label_filter.
- `detection_ingest`: label 정규화(클래스맵), track_key 산정, zone 귀속(우선순위/면적), epoch 거부, bulk insert 매핑.
- `detection_search`: 필터→SQL(인덱스 사용), clip 그룹핑(시간근접·트랙 병합 경계, pre/post).
- `object_trigger_engine`: 우선순위(카메라>전역)·min_confidence·dwell·zone_entry·min_count·cooldown·debounce_per_track 전 케이스(시각 모킹).
- `ai_scheduler.rebalance`: capacity bin-packing, 기존 할당 유지, 초과→pending, 노드 offline 재배치, pin.
- `ai_config_resolver`: 전역+카메라 override 병합, CameraJobSpec 생성(zones/labels 합집합).
- 시계 오프셋 보정·클램프.

**Integration (DB + Celery eager + mock 노드/모델)**
- join→heartbeat→assignments(etag/304)→ingest 배치→`detections` 적재→`segment_linker` 매핑(P2 segment mock) 전 경로.
- 트리거 매칭→P3 `ingest_object` 호출(P3 mock/실제)→`events(type=object)` 생성→(정책 record면)`recordings` 생성 확인. 디바운스로 중복 억제.
- 분배: 노드 2개 join, 카메라 N 분배 → 노드1 offline → 카메라 재할당(epoch++, 죽은 노드 stale 보고 거부) → 복귀 재배치.
- GPU 토글: `ai_settings.gpu_enabled` 변경 → CameraJobSpec/etag 변경 → 노드 재구성 반영.
- 검색 API: 적재 데이터로 label/camera/zone/기간/conf 필터·clip 그룹·페이지네이션·카메라 스코프 권한.
- 보존: retention_days 경과 detection 정리(파티션/배치).

**e2e (프론트+백엔드, Playwright; mock 노드가 결정적 detection 주입)**
- ObjectSearch에서 "person" + 카메라 + 기간 검색 → 썸네일 카드 → 클립 재생 → `DetectionOverlay` bbox가 비디오 표시영역에 정확히 스케일(좌표 검증) 1 시나리오 그린.
- ZoneEditor 폴리곤 그리기/드래그/저장 → detector 시그널(mock 확인) → 구역 밖 detection 필터.
- AiSettings GPU 토글 → 상태/예상부하 갱신. AiNodes 노드 추가(join_token)→상태 online→할당 표시.
- ObjectTriggers 생성→test 프리뷰→트리거 발화로 이벤트 배지.

**회귀**: P1 카메라/라이브(go2rtc 소스 연결수), P2 녹화/재생/타임라인, P3 이벤트/정책/전후버퍼가 P4 도입(트리거 발행·타임라인 레이어·세그먼트 조회) 후 정상.

---

## 13. 성능·보안 체크포인트

**성능**
- **부하 최소화 원칙(PLAN §4)**: AI는 go2rtc 재스트림 공유(카메라당 소스 1연결, 시청자/소비자 수 무관). 추론은 카메라당 `target_fps`로만(전 프레임 X), 최신 프레임 우선 드롭.
- detection 적재 **다운샘플**(6.7) + **bulk insert**(`bulk_insert_mappings`) + 가능하면 Redis Stream 버퍼링 후 배치 flush(DB write 폭주 회피).
- 검색은 `idx_det_cam_label_ts`/`idx_det_label_ts` 사용, **기간 상한·페이지네이션 강제**, clip 그룹핑은 DB 정렬+앱 병합. 타임라인은 bucket 집계. N+1 회피(selectinload).
- 파티션(월)으로 보존정리·대범위 스캔 부담 완화. 크롭 저장 기본 off(용량).
- 추론 백엔드: CUDA half(FP16)·적정 imgsz·classes 필터로 비용↓. CPU는 ONNX/OpenVINO 옵션. 노드 capacity 실측 기반 분배로 과부하 방지(throttle).
- 큐 격리: AI ingest/후처리/재할당을 녹화·구독 큐와 분리(상호 영향 차단).

**보안**
- 모든 사용자 API `@login_required`+세부 권한(`detections:read`/`zones:*`/`triggers:*`/`ai:*`/`ai_nodes:manage`), **카메라 스코프 교집합**으로 비인가 카메라 detection/스냅샷/오버레이 차단.
- 노드 API는 **aud=node 토큰 전용**(`@node_token_required`), 사용자 권한과 분리. join=1회용 토큰. 토큰 jti 폐기/회전. ingest는 **할당 카메라만** 허용·epoch 검증·페이로드 크기/범위 제한(위조·과대 방지).
- 외부 노드 통신 TLS, go2rtc 직접 노출 금지(내부망/VPN/프록시 인증 재스트림).
- 스냅샷/크롭은 권한 확인 후 서버 프록시 제공(직접 경로 노출 금지). detection raw/crop에 자격증명·내부 URL 비포함.
- 입력 검증(기간·페이지·enum·label 화이트리스트·bbox 0–1 범위). 모델 파일 출처 검증(임의 가중치 로드 경로 차단).
- 감사: 노드 join/토큰/삭제/재할당, 트리거·구역·설정 변경(`created_by/last_updated_by`+audit_logs). GPU 토글 변경 감사.
- 패키지 최신 stable(ultralytics/supervision/torch/opencv-headless). **ultralytics AGPL** 라이선스 컴플라이언스 확인(14절).

---

## 14. 미해결 질문 / 결정 필요 사항

- **Q1. detection→event 진입점**: P3가 `event_pipeline.ingest_object(camera_id, normalized)` 어댑터를 제공할지, P4가 `handle(camera, raw, source='server')`를 직접 호출할지. (권장: 전용 `ingest_object` — 결합 명확.)
- **Q2. 객체 트리거 녹화 일원화**: 트리거 녹화를 전적으로 P3 `event_policies`(type=object)로 둘지, `object_triggers.action_hint`로 P4가 일부 결정할지. (권장: P3 정책 일원화, hint는 폴백.)
- **Q3. scoped node 토큰 발급 주체**: P0 TokenService에 `issue_node_token`/`issue_join_token` 추가(권장) vs P4 자체 발급. aud=node-join TTL·node 토큰 TTL 기본값.
- **Q4. detection 보고 채널**: 외부 노드는 REST 확정. 내부 builtin은 Redis Stream 직적재(고성능) 도입 시점.
- **Q5. detections 파티셔닝/보존**: 월 RANGE 파티션 도입 시점, retention_days 기본(30?), crop 저장 기본 off 유지 여부, bbox JSON vs 컬럼 분리 임계.
- **Q6. 외부 노드 go2rtc 접근 방식**: 내부망/VPN 직접 RTSP vs 서버 발급 단기 재스트림 토큰 URL vs 프레임 push(RemoteNode). 1차 타깃 배포 형태.
- **Q7. 모델 라이선스**: ultralytics(AGPL) 배포 정책 — 오픈소스 준수 vs 상용 라이선스 vs 대체(YOLOX/RT-DETR 등) 기본 모델.
- **Q8. 분배 단위**: 카메라 단위 고정(권장) 유지 vs 초대형 카메라(고해상·고fps)를 위한 서브 분할/프레임 오프로드 허용 임계.
- **Q9. CLIP·라이브 오버레이 기본값**: CLIP 2차검증·라이브 어노 기본 off(비용) 확정, 메타 WS 오버레이를 기본 라이브 경로로 둘지.
- **Q10. `ai_settings` 위치**: 전용 테이블 vs P0 `settings` 키-값 통합.
- **Q11. 서브/메인 스트림 선택**: AI 추론은 메인(고화질·정확) 기본 vs 부하 위해 서브 허용(카메라별 옵션).

> 확정 시 본 문서 해당 절 + `../PLAN.md`(필요 시 §7 데이터 모델·§10 매핑)에 반영.

### 14.1 구현 시 채택한 결정 (2026-06-05, P4 구현)
- **Q1. detection→event 진입점**: **P3가 `event_pipeline.ingest_object(camera_id, normalized)` 어댑터 제공**(권장안 채택). `handle`을 `normalize→_process`로 리팩터, `ingest_object`가 NormalizedEvent를 만들어 동일 `_process`(정책·스케줄·combine·materialize·outbox) 재사용. 중복 클립 로직 없음.
- **Q2. 트리거 녹화 일원화**: **P3 `event_policies(type='object')`가 record/notify/discard 결정**. `object_triggers.action_hint`·`notify`는 event `raw`로 전달되는 폴백 힌트(최종 결정은 P3). 트리거는 "무엇이 event인가", 정책은 "그 event를 어떻게".
- **Q3. scoped node 토큰**: **P0 `TokenService.issue_node_token`(aud=node, sub=uuid, jti, TTL 30d) + `issue_join_token`(aud=node-join, 1회용, Redis `axp:nodejoin:{jti}`로 소비, TTL 30m) 추가**. `@node_token_required`(aud·jti=ai_nodes.token_jti·enabled·deleted 검증)로 사용자 권한맵과 완전 분리. 재발급 시 이전 jti denylist.
- **Q4. 보고 채널**: 외부·builtin 노드 모두 **REST 배치 `/ai/ingest/detections`**(epoch 멱등·at-least-once). 내부 Redis Stream 직적재는 후속(고빈도 최적화).
- **Q5. detections 파티셔닝/보존**: MVP **단일 테이블 + 복합 인덱스**(`idx_det_cam_label_ts` 등), `retention_days` 기본 **30**, crop 저장 기본 **off**(온디맨드 `/detections/{id}/snapshot`), bbox **JSON**. 월 RANGE 파티션 DROP은 임계 도달 시(`detection_retention` 배치 DELETE가 가교).
- **Q6. 외부 노드 go2rtc 접근**: 기본 **내부망 직접 RTSP**(CameraJobSpec.rtsp_url = go2rtc 내부 주소, 자격증명 없음). 단기 재스트림 토큰 URL·프레임 push(RemoteNode)는 폐쇄망 폴백(후속).
- **Q7. 모델 라이선스**: ultralytics(AGPL) 문서화, 기본 `yolov8n`. **무거운 추론 deps(torch/ultralytics/opencv)는 `requirements-inference.txt`로 분리** — 기본 이미지는 경량(node 인프라만), 추론은 빌드 프로파일. 테스트·CI는 `FakeDetector`(deps 0)로 계약 검증.
- **Q8. 분배 단위**: **카메라 단위**(`uq_assign_cam` UNIQUE, 한 카메라=1노드). 프레임 오프로드(RemoteNode)는 폐쇄망 폴백만.
- **Q9. CLIP·라이브 오버레이 기본값**: 둘 다 **기본 off**. 라이브 오버레이는 메타 WS 경로(후속); **재생 오버레이는 `/detections/overlay`(트랙 시계열 bbox) 구현**, 프론트 `DetectionOverlay`가 playhead 보간 렌더.
- **Q10. ai_settings 위치**: **전용 `ai_settings` 테이블**(전역 행 = `gpu_enabled` 권위, 카메라 override는 전역 시드 복사 후 패치 = coherent override). P0 `settings.gpu_enabled`는 부트스트랩 placeholder.
- **Q11. 메인/서브 스트림**: AI 추론은 **메인 스트림 기본**(`streams.role='main'`의 go2rtc_name). 서브 허용은 카메라 override(후속).
- **워커 graceful degrade**: ultralytics/torch 부재 → `make_detector`가 `FakeDetector` 폴백(노드 join/heartbeat/poll 인프라는 동작), 노드 자격증명(JOIN_TOKEN/NODE_TOKEN) 부재 → idle + health만. 컨테이너는 `worker.detector.app:app`(FastAPI /healthz + 부팅 시 NodeAgent 슈퍼바이저 스레드).
- **권한키**: P0 카탈로그에 이미 예약된 `detections:read`·`zones:read/update`·`triggers:read/update`·`ai:read/update`·`ai_nodes:manage` 사용. 카메라 스코프 교집합 default-deny(superuser/`*` 우회).
- **시각 정렬**: detection.ts = 노드 프레임 벽시계(UTC ms), ingest가 `|ts-now|>60s`면 server_now로 클램프(§6.6). `Segment.get_at(camera_id, ts)`로 segment_id 즉시 매핑, 미스 시 `detection_linker` beat(30s) 백필.

### 14.2 검증 메모
실카메라/GPU 부재 → 추론 백엔드·zones·tracker·sampler·reconcile는 **dependency-free unit 테스트**(`FakeDetector`/IoU tracker/down-sample/`NodeAgent.reconcile`). 서버측(분배 bin-packing·재할당·node join/token·ingest epoch/zone 귀속/track_key·검색 clip 그룹핑·트리거 디바운스/쿨다운·config 병합)은 **integration**(SQLite+fakeredis). 분산 전 경로는 **mock 노드 e2e**(`tests/_p4_detection_check.py`, **17 checks green**): 합성 녹화 → pre-register→join→heartbeat→assignments(etag/304) → ingest(person/car, stale-epoch 거부) → 스마트서치(person clip + segment 링크) → overlay 트랙 → 타임라인 → **객체 트리거→P3 object 이벤트→recording** → 2노드 rebalance. 워커 컨테이너는 경량 이미지로 빌드·healthy(FakeDetector idle). **backend pytest 182 passed**, 프론트 `tsc --noEmit`/`vite build` 무에러.
