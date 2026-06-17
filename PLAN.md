# AeroXProtect — 마스터 플랜 (PLAN.md)

> 오픈소스 NVR(Network Video Recorder). 제품명 **AeroXProtect**, 코드 네임스페이스 **axp**.
> **모든 작업은 이 문서를 먼저 읽고 시작**하고, 각 Phase의 상세는 `plan/phase-N.md`를 따른다.

---

## 0. 이 문서 사용 규칙 (필독)

1. 기능을 **구현·수정·삭제하기 전**에 본 문서와 해당 `plan/phase-N.md`를 읽는다.
2. 모든 변경은 **다른 기능·Phase에 미치는 영향**을 먼저 점검한다 → 각 Phase 문서의 *"10. Cross-feature Impact"* 절 참조/갱신.
3. **시스템 전반의 방향이 바뀌는 결정**(스택·인증·저장구조·스트리밍 방식 등)은 진행 전 반드시 사용자에게 `AskUserQuestion`으로 질문한다.
4. 구현 중 발생한 결정 필요 사항은 각 Phase 문서의 *"14. 미해결 질문"* 에 모으고, 확정되면 본 문서와 해당 문서에 반영한다.
5. 한 Phase가 끝나면 산출물이 **단독으로 동작·시연 가능**해야 한다(아래 각 Phase의 DoD).

---

## 1. 개요 & 레퍼런스

- **목표**: UniFi Protect 기능 패리티를 지향하는 온프레미스 NVR. 시스템이 직접 RTSP를 수신·녹화·저장하고, 라이브뷰·이벤트·검색·다운로드를 제공.
- **레퍼런스**: UniFi Protect(기능 목표) · Frigate(코드 참고) · Synology Surveillance Station(기능) · `../ams-front`(프로젝트 구조·스택·패턴 참고).
- **카메라**: ONVIF 지원 기기. 1차 타깃은 **Hanwha(SUNAPI)** · **Hikvision(ISAPI)**. 벤더 API가 ONVIF보다 풍부하므로 벤더 드라이버 우선, ONVIF는 공통 폴백.
- **사용 환경**: 내부망 기본 + 외부망 접속. 멀티캐스트(WS-Discovery)로 카메라 검색, 타 대역 IP 수동 추가도 지원.

---

## 2. 확정 결정사항

| 항목 | 결정 | 비고 |
|---|---|---|
| 미디어 서버 | **go2rtc** | 카메라당 연결 1개 → 라이브/녹화/AI가 공유. WebRTC/MSE/HLS, 양방향오디오, ONVIF. Docker 사이드카 |
| 배포(MVP) | **단일 온프레미스 서버** | Docker Compose, 카메라 ~16–32대. 분산은 설계만, 구현은 후속 |
| AI | **YOLO(ultralytics) 워커** | `worker/runway_monitor` 확장. **NVIDIA GPU 지원하되 on/off 토글** → 백엔드 pluggable(CUDA/CPU/외부노드) |
| 네임스페이스 | **axp** | Python 패키지 `axp`, DB 스키마 `axp`, 도커 서비스 `axp-*`. 테이블은 전용 DB라 prefix 없음. 노출 제품명은 AeroXProtect |
| 프론트엔드 | **TypeScript** | React 18 + Vite 7 + TS + Tailwind + Radix(shadcn) + TanStack + dnd-kit. ams-front(JS) 패턴을 TS로 이식 |
| 인증 | **JWT 일원화** | access+rotating refresh, Redis `jti` denylist 무효화. 모니터/AI노드/외부API는 scoped 토큰 |
| 모바일 | **반응형 웹 우선** | PWA + 웹푸시. 네이티브 앱은 후속 별도 |
| AI 라이선스 | **AGPL 수용(ultralytics)** | 프로젝트를 AGPL-3.0 호환 오픈소스로 공개. Detector는 pluggable(CUDA/CPU/node) 유지 |
| 계정 생성 | **관리자 생성 전용** | 공개 회원가입 없음. 최초 실행 셋업 마법사로 첫 admin 생성, 이후 관리자가 사용자 추가 |

---

## 3. 아키텍처

```
        ┌──────── 카메라 (ONVIF / Hikvision ISAPI / Hanwha SUNAPI) ────────┐
        │ RTSP main+sub · 이벤트(PullPoint/alertStream/event) · PTZ        │
        └───────────────────────────────┬─────────────────────────────────┘
                                         │ 카메라당 소스 연결 1개
                                ┌────────▼────────┐
                                │     go2rtc      │ 재스트리밍 허브 (1 → N)
                                │ RTSP/WebRTC/MSE │
                                └─┬────────┬────┬─┘
        WebRTC/MSE(저지연 라이브) │        │    │ 디코딩 프레임
        ┌────────────────────────┘        │    └────────────┐
   ┌────▼─────┐   /api/v1 (Axios+JWT)  ┌───▼──────┐    ┌─────▼──────┐
   │ React TS │◀── + WebSocket(상태) ─▶│ Flask MVC│    │ AI Detector│ YOLO, GPU 토글
   │ 웹/모니터│                         │  uWSGI   │    │ (worker)   │
   └──────────┘                         └─┬─────┬──┘    └─────┬──────┘
                                          │     │ Celery       │ detection 결과
                              ┌───────────▼┐  ┌─▼──────────┐   │
                              │ MySQL(메타)│  │ ffmpeg     │◀──┘
                              │  + Redis   │  │ Recorder   │ 세그먼트 녹화/변환
                              └────────────┘  └─────┬──────┘
                                                    │
              ┌──────────── 다중 HDD 스토리지 풀 ───┴───────────┐
              │ system / cache(전후버퍼) / record — 위치는 MySQL 인덱싱 │
              └──────────────────────────────────────────────────────┘
```

---

## 4. 핵심 설계 원칙 ("성능 최소화" 요구의 해답)

1. **재스트리밍 1회·N 소비** — go2rtc가 카메라당 1연결만 유지, 라이브/녹화/AI가 공유. 카메라 부하가 시청자 수와 무관.
2. **세그먼트 기반 녹화** — ffmpeg가 항상 짧은 세그먼트(~10s, **copy-codec=무재인코딩**)를 **캐시 디스크**에 롤링 기록. 이 캐시가 곧 **이벤트 전/후 버퍼**(RAM 불필요). 상시·이벤트·전후버퍼가 한 메커니즘으로 통합.
3. **메인/서브 스트림 분리** — 분할 그리드는 **서브 스트림**(무변환), 전체화면·녹화·AI는 **메인 스트림**.
4. **WebRTC 패스스루** — 라이브는 서버 트랜스코딩 없이 전달. 재인코딩은 다운로드 변환·타임랩스·썸네일 등 **온디맨드만**.
5. **다중 HDD DB 인덱싱** — 세그먼트의 디스크·경로를 MySQL에 기록, 쓰기는 정책(least-used/카메라별/RR)으로 분산, 읽기는 여러 스핀들에 분산. 디렉터리는 `/{disk}/{camera}/{YYYY}/{MM}/{DD}/{HH}/seg.mp4`로 샤딩.

---

## 5. 기술 스택

| 영역 | 선택 |
|---|---|
| 백엔드 | Flask 3 + SQLAlchemy 2 + PyMySQL + uWSGI (Python 3.13, Poetry) |
| 비동기/세션 | Celery + Redis |
| 미디어 허브 | go2rtc (Docker 사이드카) |
| 녹화/변환 | ffmpeg (세그먼트, 온디맨드 H.264/타임랩스/썸네일) |
| AI | ultralytics YOLO + supervision (+CLIP), FastAPI 워커, CUDA/CPU 토글 |
| 카메라 | onvif-zeep · WS-Discovery · requests(ISAPI/SUNAPI) |
| DB | MySQL(메타데이터) + 파일시스템(미디어) |
| 프론트 | React 18 + Vite 7 + **TypeScript** + Tailwind + Radix/shadcn + TanStack Query/Table + @dnd-kit |
| 인증 | JWT(access+refresh) + Redis denylist |
| 배포 | Docker Compose → k8s. 서비스: `axp-mysql · axp-redis · axp-go2rtc · axp-backend · axp-worker · axp-detector · axp-frontend` |

---

## 6. 저장소 구조 (ams-front 미러 + NVR 확장)

```
nvr/
├─ PLAN.md                  # 본 문서 (마스터)
├─ plan/                    # Phase별 상세 계획
│  ├─ README.md
│  └─ phase-0.md ... phase-10.md
├─ server/                  # Flask 백엔드 (패키지 axp)
│  ├─ view/api/             # camera, stream, recording, playback, event, storage, dashboard, monitor, rule, ai, auth, admin
│  ├─ controller/  model/  util/
│  ├─ driver/               # onvif, isapi, sunapi, go2rtc, webhook, speaker, io, email, push
│  ├─ service/              # storage_manager, segment_indexer, recorder_supervisor, capability_probe, scheduler, token
│  └─ task/list/            # Celery: retention, disk_scan, thumbnail, transcode, timelapse
├─ worker/
│  ├─ recorder/             # per-camera ffmpeg 세그먼트 레코더 (supervisor)
│  └─ detector/             # YOLO AI 워커 (GPU 토글, runway_monitor 확장)
├─ frontend/                # React + Vite + TypeScript
│  └─ src/pages/            # live, playback, events, cameras, storage, dashboards, monitors, rules, ai, users, settings
├─ go2rtc/                  # 동적 생성 설정
├─ migrations/  docker-compose.yml  DESIGN.md
```

---

## 7. 핵심 데이터 모델 (개요)

`users` · `roles` · `permissions`(JSON 권한맵) · `audit_logs` · `cameras`(vendor, model, driver, **암호화 자격증명**, capabilities JSON, status) · `streams`(role main/sub, codec, res, fps, go2rtc_name) · `disks`(mount, capacity, reserved_free, role system/cache/record, enabled) · `storage_policies` · `segments`(camera, disk, path, start/end_ts, size) · `recordings`(reason continuous/event/manual/schedule, retention_class) · `events`(type, ts, region, source, snapshot, raw) · `detections`(class, conf, bbox, track_id) · `schedules` · `dashboards`(layout JSON + ACL) · `monitors` + `pairing_codes`(60s 만료) · `rules`(trigger/condition/action JSON) · `ai_nodes` · `settings`.

> 상세 컬럼·인덱스·마이그레이션은 각 Phase 문서의 *"4. 데이터 모델"* 에서 정의.

---

## 8. 인증·인가 (JWT 일원화)

- **토큰**: 단기 access(~15m) + 회전 refresh(~14d, 재사용 탐지). 웹은 refresh를 httpOnly 쿠키, API/모바일 클라이언트는 응답 바디로.
- **무효화**: 로그아웃·강제만료 시 Redis `jti` denylist. refresh 회전 시 이전 토큰 폐기.
- **RBAC**: 토큰에는 user_id·role만, 세부 권한은 요청 시 서버에서 권한맵(JSON)으로 해석. `@login_required` + `@permission_required(perm)` 데코레이터(ams 패턴).
- **역할**: `admin`(계정관리 포함 전권) / `user`(관리자가 부여한 세부 권한: 뷰어전용, 특정 카메라 PTZ, 다운로드, 특정 대시보드 등).
- **계정 생성**: 공개 회원가입 없음. 최초 실행 시 셋업 마법사가 첫 `admin`을 생성, 이후 `admin`이 사용자 생성·권한 부여(가입신청/승인 플로우 미사용).
- **모니터 클라이언트**: 60초 일회용 숫자코드 페어링 → audience=`monitor`, 특정 대시보드 한정·뷰어전용 scoped JWT 발급.
- **AI 노드/외부 API**: audience=`node`/`api` scoped 서비스 토큰.
- **CSRF**: API는 `Authorization: Bearer` 헤더 사용으로 위험 최소화. refresh 쿠키 엔드포인트만 CSRF 보호.

---

## 9. Phase 로드맵

| Phase | 이름 | 핵심 DoD(완료 기준) | 상세 |
|---|---|---|---|
| **P0** | 기반(Scaffold) | 저장소·Docker·인증/RBAC·핵심 모델·디자인 셸이 떠서 로그인·권한 동작 | `plan/phase-0.md` |
| **P1** | 카메라 온보딩 + 라이브뷰 | 카메라 추가(검색/수동·자동프로빙) 후 유연한 분할 그리드 라이브 + PTZ | `plan/phase-1.md` |
| **P2** | 녹화 + 스토리지 엔진 | 상시·수동 녹화, 다중HDD 풀·보존정책, 타임라인 재생·클립 다운로드 | `plan/phase-2.md` |
| **P3** | 이벤트 + 스마트/스케줄 녹화 | ONVIF/ISAPI/SUNAPI 이벤트 정규화, 이벤트·스케줄 녹화, 모션 오버레이 | `plan/phase-3.md` |
| **P4** | AI 객체인식 + 검색 | YOLO(GPU 토글) detection 메타 저장, 객체 검색·트리거, 분산 AI join | `plan/phase-4.md` |
| **P5** | 자동화 + 모니터 + 알림 | 규칙엔진(스피커/IO/웹훅), 모니터 페어링, 푸시/이메일/웹훅 | `plan/phase-5.md` |
| **P6** | 라이브/녹화 폴리시 | 양방향오디오·마스킹·디워핑·시퀀스/자동전환·지도·이중/엣지녹화·암호화·공유링크·북마크·일반 고급AI(카운팅/배회/오디오/연기/시맨틱) | `plan/phase-6.md` |
| **P7** | LPR + 얼굴인식 | 번호판 OCR·얼굴 로컬DB(프라이버시) | `plan/phase-7.md` (예정) |
| **P8** | 다중 NVR 중앙관리 | 페더레이션·통합 뷰 | `plan/phase-8.md` (예정) |
| **P9** | 원격접속 포털 | 릴레이/포털(포트포워딩·VPN 불필요) | `plan/phase-9.md` (예정) |
| **P10** | 출입통제·인터컴 | 도어 컨트롤러·도어벨/인터컴 | `plan/phase-10.md` (예정) |

---

## 10. 요청 기능 → Phase 매핑

| 카테고리 | P1 | P2 | P3 | P4 | P5 | P6 |
|---|---|---|---|---|---|---|
| 라이브 | 다중채널·커스텀레이아웃·PTZ·스냅샷 | | | GPU디코딩 | 모니터(로컬디스플레이) | 시퀀스/자동전환·디워핑·마스킹·양방향오디오·객체추적·지도 |
| 녹화/재생 | 다중스트림 | 상시·수동·전후버퍼·타임라인·내보내기·보존·다중HDD | 스케줄·모션·이벤트·타임랩스·북마크 | | | 이중·엣지녹화·암호화·공유링크 |
| AI/분석 | | | 라인크로스·침입·탬퍼(카메라측) | 사람/차량·검출구역·스마트서치·객체트리거 | | LPR·얼굴·카운팅·혼잡·배회·오디오·연기·시맨틱검색 |
| 알림/자동화 | | | 이벤트알림 | | 푸시·이메일·웹훅·규칙엔진·IP스피커·IO | SMS·통합/음소거 |
| 카메라/장치 | ONVIF/ISAPI/SUNAPI·디스커버리·다중스트림 | 배치추가 | | | IP/SIP스피커 | 도어벨·출입통제·LiveCam |
| 관리/확장 | 권한·카메라접근제어 | | 이벤트로그 | 분산AI | 외부API·HA·원격접속 | 다중NVR중앙관리·백업/아카이빙 |

> ※ P6 분할: LPR·얼굴=**P7**, 다중NVR중앙관리=**P8**, 원격접속포털=**P9**, 출입통제·인터컴=**P10**.

---

## 11. 횡단 관심사 (모든 Phase 공통)

- **보안**: 자격증명 암호화 저장(`cryptography`), 모든 API 인가 점검, 응답에 비인가 정보 노출 금지, 입력 검증, 패키지 최신 stable.
- **성능**: 불필요 join/FK 자제, 인덱스 설계, 무재인코딩 우선, 쿼리 N+1 회피.
- **테스트**: 모든 기능에 테스트 작성. 변경 시 회귀 점검(타 기능 영향). unit/integration/e2e.
- **응답 표준**: `ResponseBuilder`(success/bad_request/forbidden/not_found/conflict) — ams 패턴.
- **i18n**: ko/en (react-intl). **시간대**: 저장은 **UTC `DATETIME(3)` 확정**(§12.1), API 직렬화 epoch ms/ISO, 표시 KST.
- **감사/로그**: `audit_logs`(created_by/updated_by), 시스템·이벤트 로그.
- **마이그레이션**: 모델 변경 시 MySQL 기준 SQL 제공.
- **DB 컨벤션**: soft delete(`deleted_at`), 감사 컬럼, Snowflake ID(ams 패턴 참고).

---

## 12. Cross-phase 계약 정합성 (SSOT — 변경 시 영향 점검 필수)

Phase 문서를 독립 작성하며 도출된 **교차 계약**. 구현 시 아래를 단일 진실원으로 따르고, 바꿀 때는 영향 Phase를 모두 점검한다. (2026-06-05 전수 검증으로 확정·정정.)

### 12.1 단일 진실원 계약
- **시간(★정정)**: 전 계층 **`DATETIME(3)` UTC 저장**(밀리초). 저빈도(`users`/`cameras`…)·고빈도(`segments`/`events`/`detections`…) **모든 시각 컬럼 동일 타입**(audit `created_at/updated_at/deleted_at` + 도메인 `start_ts/end_ts/ts`). 이유: `events`↔`recordings`↔`segments`↔`detections`가 시간으로 조인·범위질의되므로 동일 물리 타입 필수 + MySQL 날짜함수·RANGE 파티셔닝(`TO_DAYS`) 활용. **API 직렬화는 epoch ms(또는 ISO), 표시는 KST.** (ams의 KST-naive 저장과 의도적으로 다름.)
- **`recordings.reason` enum**: `continuous | manual | event | schedule` (P2 정의, P3가 `event/schedule` 사용). **`object` 없음** — AI 객체 트리거는 P4가 `events(type='object')`로 승격 → P3 정책이 `recordings(reason='event')` 생성.
- **이벤트 단일 소스(`event_outbox`)**: 카메라 이벤트(P3)·AI 객체(P4) 모두 **P3 `events`+`event_outbox`로 정규화**. 녹화·알림·규칙(P5)은 outbox만 소비. P4 object trigger는 `events(type='object', source='server')`로 승격(중복 구현 금지).
- **스트림 주소 규약**: `streams.go2rtc_name` → `rtsp://axp-go2rtc:8554/{go2rtc_name}` (P2 레코더·P4 디텍터 공통, 메인=녹화/AI·서브=그리드).
- **JWT 토큰 모델(★정정)**: `aud`(소비자 클래스) ∈ {`web`·`monitor`·`node`·`api`·`share`}; `typ`(종류) ∈ {`access`·`refresh`}. web의 access/refresh는 `typ`로 구분(`aud='web'`). monitor/node/share는 scoped JWT(`scope` 클레임). **외부 API(`api`)는 즉시해지·장수명 요구로 불투명 DB 토큰 허용**(P5 `api_tokens`). P0 `TokenService`는 aud·scope 확장형.
- **권한 네이밍(★정정, canonical)**: 표기 **`resource:action`(콜론)**, 데코레이터 `@permission_required('<resource>','<action>')`. 자원·행위는 12.2 카탈로그가 단일 진실원. per-scope 키 `camera_scope`/`dashboard_scope`(P1 정의, 이후 재사용).
- **Python 패키지(★정정)**: 임포트 루트 = **`server/`**(ams 미러, P0 확정). `axp`는 제품/네임스페이스(DB 스키마·도커 서비스 `axp-*`·Celery app·Redis 키 prefix)만. (`axp.util.*` 표기 금지 → `server.util.*`.)
- **감사 컬럼**: `created_by_id` / **`last_updated_by_id`**(고정 명칭).
- **GPU 토글 단일화**: 전역 GPU on/off 권위 = **P4 `ai_settings.gpu_enabled`(전역 행)**. P0 `settings.gpu_enabled` 시드는 부트스트랩 placeholder(P4 도입 시 이관, 중복 회피).
- **공통 모델 규약**: Snowflake BIGINT PK(서비스별 instance 분리), soft delete(`deleted_at`), FK 최소화.
- **클립 표현**: 세그먼트 시간범위 참조(불변), 다운로드 시에만 concat/transcode 산출(P2).

### 12.2 권한 카탈로그 (canonical · `resource:action`)
| Phase | 자원:행위(예) |
|---|---|
| P0 | `users:read/create/update/delete` · `roles:read/update/manage` · `audit:read` · `settings:read/update` |
| P1 | `cameras:read/create/update/delete/discover` · `live:read` · `ptz:control` · `streams:read/update` · `dashboards:read/create/update/delete/share` (+`camera_scope`/`dashboard_scope`) |
| P2 | `recordings:read/control` · `playback:read` · `clips:export` · `storage:read/manage` · `retention:manage` |
| P3 | `events:read/update/delete` · `policies:read/update` · `schedules:read/update` · `timelapse:read/create/cancel` |
| P4 | `detections:read` · `zones:read/update` · `triggers:read/update` · `ai:read/update` · `ai_nodes:manage`(admin) |
| P5 | `rules:read/create/update/delete` · `targets:read/manage` · `monitors:read/manage` · `notifications:read/update` · `api_tokens:manage` |
| P6+ | `masks:read/update` · `share:create/manage` · `bookmarks:read/update` · `archive:read/run` · `audio:talk` · `maps:read/update` · `ptz:autotrack` · `ai:count/semantic_search/audio` |
> `admin` 역할은 `{"*":["*"]}` 전권. 각 Phase 문서가 쓴 분기 표기(`camera.view`·`event:read`·`recording.control` 등)는 본 카탈로그로 통일(12.3).

### 12.3 Phase 문서 정정 사항 (검증 결과 · 구현 시 반영)
| 문서 | 정정 |
|---|---|
| 전체 | 시각 컬럼 **`DATETIME(3)` UTC** 통일 / 권한키 12.2 콜론 표기 통일 |
| P1 | `updated_by_id`→`last_updated_by_id` · `axp.util.idgen`→`server.util.snowflake` · `axp.util.crypto`→`server.util.crypto` · `AXP_CRED_KEY`→`CREDENTIAL_ENC_KEY` · 권한 `camera.*/live.*/ptz.*/dashboard.*`→`cameras:*/live:*/ptz:*/dashboards:*` |
| P2 | 권한 `recording.*/playback.*/clip.*/storage.*/retention.*`→`recordings:*/playback:*/clips:*/storage:*/retention:*` |
| P3 | **시각 `BIGINT epoch ms`→`DATETIME(3)`**(events/policies/schedules/outbox 등 전부) · 권한 `policy:*`→`policies:*` 등 12.2 정렬 |
| P4 | `ai_settings.gpu_enabled`를 전역 GPU 권위로(P0 settings는 placeholder) · 권한 `zones/triggers` 명칭 12.2 정렬 |
| P5 | 고빈도 테이블 시각 `BIGINT`→`DATETIME(3)`(`rule_executions`/`notifications`) · `api_tokens` 불투명 토큰 허용 명문화(상기) |
| P6+ | 신규 시각 컬럼 `DATETIME(3)` · share `aud` 추가 · LPR/얼굴=P7·다중NVR=P8·원격=P9·출입통제=P10 분리 |
| P0 §14 | Q1(가입정책) = **admin-only 확정**(사용자 결정, 해소) |

---

## 13. 다음 단계

P0(Scaffold)부터 착수. 각 Phase 상세는 `plan/phase-N.md` 참조. 방향 변경 결정은 사용자 확인 후 진행.
