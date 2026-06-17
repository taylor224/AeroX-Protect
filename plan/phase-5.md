# Phase 5 — 자동화 + 모니터 + 알림

> 마스터 플랜: [`../PLAN.md`](../PLAN.md) · 디자인: [`../DESIGN.md`](../DESIGN.md) · 선행: [`phase-0.md`](phase-0.md)(JWT scoped 토큰·RBAC·Base 모델·WS 허브·Celery), [`phase-1.md`](phase-1.md)(cameras/dashboards/capabilities·WS 게이트웨이), [`phase-3.md`](phase-3.md)(events·event_outbox·`signals.event_created`), [`phase-4.md`](phase-4.md)(detections·object 트리거).
> **구현 전 본 문서 + PLAN.md를 읽고, "10. Cross-feature Impact" 절을 반드시 확인·갱신**한다. 네임스페이스 `axp`, Flask MVC(view→controller→service/driver→model), Celery+Redis, 응답은 `ResponseBuilder`. 저장 타임스탬프는 **UTC `DATETIME(3)`**(전 계층 동일, §12.1), API 직렬화는 epoch ms·ISO, 표시·조용시간·스케줄 해석은 **KST**. 인증은 PLAN §8 **JWT 일원화**(모니터=audience `monitor` scoped JWT).

---

## 1. 목표 & 성공 기준(DoD)

P5는 "무슨 일이 일어났을 때(이벤트=P3 / AI 객체=P4 / 스케줄 / 수동) 시스템이 **무엇을 할지(스피커 방송·IO 출력·웹훅·푸시·이메일)** 규칙으로 정의·평가·실행하고, 그 결과를 로그로 남긴다. 동시에 관리자가 발급한 **60초 일회용 숫자코드**로 모니터(로컬 디스플레이/키오스크)를 페어링해 특정 대시보드만 뷰어전용으로 풀스크린 표시하고, 사용자는 웹푸시(PWA)·이메일·웹훅으로 알림을 받으며, 외부 시스템(Home Assistant 등)이 scoped 토큰으로 이벤트/상태를 구독한다"를 완성한다.

**DoD (이 항목들이 단독 시연 가능해야 P5 완료):**

1. **규칙 엔진**: 트리거(event / object / schedule / manual) + 조건(카메라·시간대·이벤트타입·객체클래스·min_score·쿨다운·조용시간) → 액션(speaker / io / webhook / push / email)을 JSON으로 정의한 `rules`가, P3 `event_outbox`/`signals.event_created`·P4 detection·Celery beat(schedule)·수동 트리거로부터 입력을 받아 **순서대로 평가**되고 매칭 시 액션이 실행되며 **`rule_executions`에 결과(성공/실패/지연/스킵사유)가 기록**된다.
2. **디바운스/쿨다운**: 규칙별·트리거 단위 `cooldown_s`·`debounce_s`로 동일 트리거 폭주를 억제하고, Redis 기반 멱등(`idempotency_key`)으로 동일 이벤트 중복 실행을 방지한다.
3. **액션 드라이버 실동작**:
   - **speaker**: IP/SIP 스피커에 사전 등록한 오디오 클립/TTS를 재생(우선순위: 벤더 HTTP API > ONVIF audio backchannel > SIP/RTP 발신). 실기기 또는 시뮬레이터 1대 이상에서 방송 성공.
   - **io**: IO 모듈(릴레이/디지털 출력)에 출력 on/off/pulse(ms) 적용(HTTP/ONVIF RelayOutputs/벤더 CGI). 실기기/시뮬레이터 1대 이상.
   - **webhook**: 서명(HMAC-SHA256)·재시도(지수 백오프)·타임아웃을 갖춘 POST 발송, 수신 테스트 엔드포인트로 검증.
   - **email**: SMTP로 이벤트 요약+스냅샷 링크 전송(통합/조용시간 반영).
   - **push**: 웹푸시(VAPID) — 구독한 브라우저/PWA에 알림 도달(클릭 시 해당 이벤트/대시보드로 딥링크).
4. **모니터 페어링(60초 일회용 숫자코드)**: 관리자가 모니터를 생성하고 **6자리 숫자코드**(60초 만료·일회용·재시도 제한)를 발급 → 모니터 기기가 코드 입력 → **audience=`monitor`** scoped JWT(특정 대시보드 한정·뷰어전용·자동 refresh) 발급 → 키오스크 풀스크린으로 지정 대시보드 라이브 표시. 관리자는 모니터 목록·해지(즉시 무효)·대시보드 재지정·코드 재발급 가능.
5. **알림 구독·정책**: 사용자/이벤트별 채널 구독(`notification_subscriptions`), 음소거/통합(batching)·우선순위·조용시간(KST) 옵션이 동작하고, 인앱 알림 센터(WS)와 외부 채널(push/email/webhook)이 정책에 따라 발송된다.
6. **외부 API 토대**: scoped(audience=`api`) 공개 API 토큰으로 이벤트/상태 조회·구독(웹훅 등록 + SSE 스트림), Home Assistant 연동 포인트(이벤트 push·상태 폴링) 문서/엔드포인트 제공.
7. **테스트**: 규칙 평가(조건 매칭·결합·쿨다운·멱등)·각 드라이버(mock 기기)·페어링 코드 발급/검증/만료/재시도제한/토큰교환·모니터 토큰 scope 강제·웹푸시 흐름에 unit/integration, 페어링→키오스크 표시 + 규칙→웹훅 발송 e2e 각 1개 이상 그린.

---

## 2. 범위 (In-scope / Out-of-scope)

### In-scope
- **동작규칙 엔진(Action Rules)**: 규칙 모델(JSON trigger/condition/action), 평가 파이프라인(트리거 수집→조건 평가→액션 디스패치), 디바운스/쿨다운/멱등, 실행 로그(`rule_executions`).
- **트리거 소스 어댑터**: P3 `event_outbox`(폴링) + `signals.event_created`(in-proc) 소비, P4 detection(object) 소비, **스케줄 트리거**(Celery beat + cron 표현), **수동 트리거**(API/버튼/대시보드).
- **액션 드라이버**: `speaker`(IP/SIP/ONVIF backchannel), `io`(릴레이/디지털 출력), `webhook`(서명·재시도·타임아웃), `email`(SMTP), `push`(웹푸시 VAPID). 액션 대상 레지스트리(`action_targets`).
- **모니터 클라이언트**: 모니터 등록/관리(`monitors`), 60초 일회용 숫자코드(`pairing_codes`) 발급·검증·토큰 교환, audience=`monitor` scoped JWT 발급·자동 refresh·해지, 키오스크 풀스크린 뷰어.
- **알림**: 웹푸시(PWA, VAPID)·이메일·웹훅·인앱(WS). 사용자/이벤트별 구독(`notification_subscriptions`), 음소거/통합·우선순위·조용시간, 푸시 구독 엔드포인트(`push_subscriptions`).
- **외부 API + Home Assistant 토대**: 공개 API 토큰(audience=`api`, scoped, `api_tokens`), 이벤트/상태 구독(웹훅 등록 + SSE), HA 연동 가이드/엔드포인트.

### Out-of-scope (다른 Phase)
- **SMS/카카오 발송**(SOLAPI 등), **고급 외부 연동**(다중 NVR 중앙관리·원격 포털·MQTT 브로커 상시 연동), **다중 NVR fan-out** → **P6**. (P5는 webhook/push/email + HA 연동 포인트까지.)
- **이벤트 정규화·구독·전후버퍼 녹화**: **P3 소유**(P5는 결과 소비만).
- **AI detection·스마트서치**: **P4 소유**(P5는 object 트리거 소비만).
- **카메라 양방향 오디오(라이브 인터컴 UI)**: P6(P5는 스피커 액션 = 사전 등록 클립/TTS의 단방향 재생만; 라이브 talk는 P1 backchannel/P6 인터컴).
- **대시보드 편집/레이아웃 에디터**: P1 소유(P5는 모니터가 대시보드를 **표시·바인딩**만).
- **WS 게이트웨이 자체 구현**: P1 도입(P5는 채널 `notifications`·`monitor.<id>` 추가 사용).

---

## 3. 선행 의존성

| 출처 | P5가 사용하는 산출물 | 사용처 |
|---|---|---|
| **P0** | `axp` 골격, MVC/Blueprint, `BaseDB`(Snowflake·soft delete·audit), `ResponseBuilder`, **`TokenService`**(JWT 발급/검증/회전/denylist, `aud` 분기·`scope` 클레임 자리), `@login_required`/`@permission_required`, 권한맵(JSON), Redis, Celery `celery_use_db()`, `util/crypto.py`(Fernet — 액션 대상 자격증명 암호화), i18n, `audit_logs` | 인증·권한·토큰·암호화·로깅 전 영역 |
| **P1** | `cameras`(name/host/capabilities: audio backchannel·relay outputs 여부), `dashboards`(uuid/layout/owner)·`dashboard_acl`, **WS 게이트웨이**(채널 네이밍 `camera.status`/`event.*`, scope 필터), go2rtc 라이브(키오스크 뷰가 재사용), `streams`(main/sub) | 모니터가 대시보드/라이브 표시, 스피커/IO 대상이 카메라 capability 참조 |
| **P3** | **`events`**(정규화 타입·camera_id·start_ts·score·region·snapshot), **`event_outbox`**(status pending/consumed/failed, payload), **`signals.event_created`**(in-proc), WS `events` 채널, `event_policies.notify` 플래그 | 규칙 트리거 = 이벤트, 알림 소스 |
| **P4** | `detections`(camera_id·class·confidence·bbox·track_id·event_id 링크), `object` 정규화 타입, detection 시그널/큐 | 규칙 트리거 = AI 객체(클래스·confidence·zone) |
| **P6(역방향)** | (P5가 **제공**) `rules`·`action_targets`·드라이버 인터페이스·`api_tokens`·웹훅/SSE | P6 SMS·고급 연동·다중 NVR이 액션/구독 확장 |

**P5 착수 전 확인(블로킹):**
1. P3 `event_outbox` payload 스키마(규칙이 추가 join 없이 평가 가능한 필드 — camera_id/type/subtype/score/start_ts/snapshot_path/region 요약)와 소비(consumed 표시) 계약.
2. P3 `signals.event_created` 시그널 시그니처(event_id 전달) + at-least-once 보장(outbox 병행) — P5는 **outbox를 1차 진실원**으로(시그널은 저지연 보조).
3. P4 detection → trigger 발행 방식(detection 시 `events`에 object row 생성 후 outbox로 흐르는지, 아니면 별도 detection 큐/시그널인지). **권장**: P4도 object를 `events`+`event_outbox`로 흘려 P5 단일 소비 경로 유지(§10 Q).
4. P1 WS 게이트웨이의 **모니터 scope 채널**(`monitor.<monitor_id>`) 추가 가능 여부, 인증(쿼리 토큰 vs 헤더).
5. P0 `TokenService`의 `aud`/`scope` 클레임·검증기 분기 자리 확정(monitor/api audience).

---

## 4. 데이터 모델

> 컨벤션: PK `id BIGINT`(Snowflake, app 생성). **모든 시각 컬럼은 전 계층 UTC `DATETIME(3)` 저장**(밀리초; 고빈도·설정성 동일 물리 타입, §12.1) — API 직렬화는 epoch ms·ISO, 표시는 KST. 고빈도/로그성 테이블(`rule_executions`, `notifications`)도 `*_ts`/`created_at`을 `DATETIME(3)`로 두고 인덱스(P3 패턴). 설정성 테이블(`rules`, `action_targets`, `monitors`, `notification_subscriptions`, `push_subscriptions`, `api_tokens`)은 P0 패턴의 `DATETIME(3)`(UTC) `created_at/updated_at/deleted_at` + 감사 컬럼. **`pairing_codes`**는 단명·고보안이라 별도(아래). 대량·고빈도 테이블은 FK 미설정(논리참조+인덱스). 스키마 `axp`(전용 DB, prefix 없음). 자격증명류는 `util.crypto`(Fernet) 암호화 컬럼(`*_enc VARBINARY`).

신규 테이블: **`rules`, `rule_executions`, `action_targets`, `monitors`, `pairing_codes`, `notification_subscriptions`, `push_subscriptions`, `notifications`, `api_tokens`, `webhook_endpoints`.**

### 4.1 `rules` — 동작 규칙 (trigger/condition/action JSON)

| 컬럼 | 타입 | 설명/인덱스 |
|---|---|---|
| `id` | BIGINT PK | Snowflake |
| `uuid` | CHAR(32) | UNIQUE, 외부 노출 |
| `name` | VARCHAR(120) NOT NULL | 규칙명 |
| `description` | VARCHAR(500) NULL | |
| `enabled` | TINYINT(1) NOT NULL DEFAULT 1 | idx `(enabled, priority)` |
| `priority` | SMALLINT NOT NULL DEFAULT 0 | 평가 순서(큰 값 우선). `stop_on_match`와 결합 |
| `stop_on_match` | TINYINT(1) NOT NULL DEFAULT 0 | true면 매칭 시 이후 규칙 평가 중단(룰체인) |
| `trigger_type` | VARCHAR(16) NOT NULL | `event` / `object` / `schedule` / `manual`. idx `(trigger_type, enabled)` |
| `trigger` | JSON NOT NULL | 트리거 상세(아래 6.1). event: `{event_types:[...], subtypes:[...]}`; object: `{classes:["person","car"], min_confidence:60, zones:[...]}`; schedule: `{cron:"0 9 * * 1-5", tz:"Asia/Seoul"}`; manual: `{}` |
| `condition` | JSON NOT NULL DEFAULT (`{}`) | 조건(AND 그룹, 아래 6.2): `{camera_ids:[...], time_ranges:[{dow:[1,2],start:"08:00",end:"18:00"}], min_score:50, quiet_respect:true, all_of:[...], any_of:[...]}` |
| `actions` | JSON NOT NULL | 액션 목록(순서/지연/조건부): `[{target_id, type:"speaker", params:{clip_id}, delay_ms:0, continue_on_error:true}, ...]` |
| `cooldown_s` | SMALLINT NOT NULL DEFAULT 30 | 규칙 매칭 후 재발화 억제(같은 dedup 스코프) |
| `debounce_s` | SMALLINT NOT NULL DEFAULT 0 | 연속 트리거를 마지막 1건으로 합치는 지연(0=즉시) |
| `dedup_scope` | VARCHAR(16) NOT NULL DEFAULT 'camera' | 쿨다운/멱등 키 스코프: `rule`(규칙 전체) / `camera`(규칙×카메라) / `target`(규칙×카메라×트리거키) |
| `max_per_hour` | SMALLINT NULL | 시간당 실행 상한(토큰버킷, NULL=무제한) |
| `last_triggered_ts` | DATETIME(3) NULL | 최근 발화(UTC, 관측용) |
| 감사 | `created_at/updated_at/deleted_at/created_by_id/last_updated_by_id` DATETIME(3)/BIGINT | 공통 |

인덱스: `uq_rules_uuid(uuid)`, `idx_rules_enabled_pri(enabled, priority)`, `idx_rules_trigger(trigger_type, enabled)`, `idx_rules_deleted(deleted_at)`.

> **설계 노트**: 트리거 타입을 컬럼으로 둬 인덱스로 빠르게 후보 규칙을 좁히고(event/object 트리거 도착 시 `WHERE trigger_type IN ('event','object') AND enabled=1`), 세부 매칭은 `trigger`/`condition` JSON을 메모리에서 평가. 규칙 수는 보통 수십~수백 → 활성 규칙을 Redis/프로세스 캐시(변경 시 무효화)로 들고 평가.

### 4.2 `rule_executions` — 규칙 실행 로그 (고빈도, append 중심)

| 컬럼 | 타입 | 설명/인덱스 |
|---|---|---|
| `id` | BIGINT PK | Snowflake |
| `rule_id` | BIGINT NOT NULL | 논리 FK. idx `(rule_id, created_at)` |
| `trigger_type` | VARCHAR(16) NOT NULL | 발화 트리거 |
| `event_id` | BIGINT NULL | 트리거가 event/object면 events.id. idx |
| `camera_id` | BIGINT NULL | 관련 카메라. idx `(camera_id, created_at)` |
| `matched` | TINYINT(1) NOT NULL | 조건 통과 여부(false=후보였으나 조건 불일치/스킵) |
| `skip_reason` | VARCHAR(32) NULL | `cooldown` / `debounced` / `rate_limited` / `quiet_hours` / `condition_false` / `disabled` / `duplicate` |
| `idempotency_key` | VARCHAR(120) NULL | 멱등 키(중복 방지). idx |
| `action_results` | JSON NULL | `[{target_id, type, status:"success|failed|skipped|timeout", latency_ms, attempts, error}]` |
| `status` | VARCHAR(16) NOT NULL | 종합: `success`(전 액션 성공) / `partial`(일부 실패) / `failed` / `skipped` |
| `started_ts` | DATETIME(3) NULL | 액션 디스패치 시작(UTC) |
| `finished_ts` | DATETIME(3) NULL | 완료 |
| `duration_ms` | INT NULL | 파생 |
| `celery_task_id` | VARCHAR(64) NULL | 추적 |
| `created_at` | DATETIME(3) NOT NULL | 수신·삽입(UTC). idx |
| `deleted_at` | DATETIME(3) NULL | 보존정리(soft). idx |

인덱스: `idx_re_rule_ts(rule_id, created_at)`, `idx_re_cam_ts(camera_id, created_at)`, `idx_re_event(event_id)`, `idx_re_idem(idempotency_key)`, `idx_re_status(status, created_at)`, `idx_re_deleted(deleted_at)`. 보존: Celery `rule_execution_retention`(기본 90일, settings로 조정), raw/대형 `action_results`는 조기 정리.

### 4.3 `action_targets` — 액션 대상 레지스트리 (speaker/io/webhook 등)

> 스피커·IO 모듈·웹훅 엔드포인트 등 "어디에 액션을 보낼지"를 통합 관리. 자격증명은 Fernet 암호화. 웹훅은 별도 `webhook_endpoints`로 분리(서명키·재시도 정책 등 전용 필드)하되, 규칙 액션에서는 둘 다 `target_id`로 참조(타입으로 라우팅).

| 컬럼 | 타입 | 설명/인덱스 |
|---|---|---|
| `id` | BIGINT PK | Snowflake |
| `uuid` | CHAR(32) | UNIQUE |
| `type` | VARCHAR(16) NOT NULL | `speaker` / `io` / `email`(SMTP 프로필) — webhook/push는 별도 표 참조. idx `(type, enabled)` |
| `name` | VARCHAR(120) NOT NULL | |
| `vendor` | VARCHAR(40) NULL | speaker: `axis`/`2n`/`onvif`/`sip`; io: `advantech`/`onvif`/`hikvision`/`generic_http` |
| `protocol` | VARCHAR(24) NOT NULL | speaker: `vendor_http`/`onvif_backchannel`/`sip`; io: `onvif_relay`/`vendor_http`/`modbus_tcp`(P6) |
| `host` | VARCHAR(190) NULL | IP/호스트 |
| `port` | INT NULL | |
| `config` | JSON NOT NULL DEFAULT (`{}`) | 타입별 설정(아래 6.3/6.4): speaker `{sip:{uri,realm,from,codec:"PCMU"}, clips:[{id,name,path}], tts:{engine,voice}, channel}`; io `{outputs:[{id,name,relay_index}], default_pulse_ms}`; email `{smtp_host,smtp_port,from,use_tls}` |
| `username_enc` | VARBINARY(512) NULL | Fernet 암호문(SIP/HTTP/SMTP user) |
| `password_enc` | VARBINARY(512) NULL | Fernet 암호문 |
| `cred_key_id` | VARCHAR(16) NULL | 암호화 키 버전(P1 crypto 라우팅) |
| `camera_id` | BIGINT NULL | (선택) 카메라 내장 스피커/IO일 때 연관 카메라. idx |
| `enabled` | TINYINT(1) NOT NULL DEFAULT 1 | |
| `status` | VARCHAR(16) NOT NULL DEFAULT 'unknown' | `online`/`offline`/`error`/`unknown`(헬스체크 결과) |
| `last_checked_at` | DATETIME(3) NULL | 헬스체크 시각 |
| 감사 | `created_at/updated_at/deleted_at/created_by_id/last_updated_by_id` | 공통 |

인덱스: `uq_at_uuid(uuid)`, `idx_at_type(type, enabled)`, `idx_at_camera(camera_id)`, `idx_at_deleted(deleted_at)`.

### 4.4 `webhook_endpoints` — 웹훅 대상(서명·재시도 전용)

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `id` | BIGINT PK | Snowflake |
| `uuid` | CHAR(32) | UNIQUE |
| `name` | VARCHAR(120) NOT NULL | |
| `url` | VARCHAR(1024) NOT NULL | POST 대상(https 권장). **SSRF 가드 대상**(7.5) |
| `secret_enc` | VARBINARY(512) NULL | HMAC 서명 비밀(Fernet 저장, 발송 시 복호화) |
| `cred_key_id` | VARCHAR(16) NULL | |
| `headers` | JSON NULL | 추가 헤더(인증 토큰 등; 민감값은 응답 마스킹) |
| `timeout_ms` | INT NOT NULL DEFAULT 5000 | 요청 타임아웃 |
| `max_retries` | SMALLINT NOT NULL DEFAULT 3 | 지수 백오프 재시도 |
| `verify_tls` | TINYINT(1) NOT NULL DEFAULT 1 | 사설 CA면 false 허용(경고) |
| `purpose` | VARCHAR(16) NOT NULL DEFAULT 'action' | `action`(규칙 액션) / `subscription`(외부 구독, 4.10) |
| `subscription_filter` | JSON NULL | purpose=subscription 시 구독 필터(event_types/camera_ids) |
| `api_token_id` | BIGINT NULL | 외부 구독을 등록한 API 토큰(소유·해지 연동). idx |
| `enabled` | TINYINT(1) NOT NULL DEFAULT 1 | |
| `last_status` | SMALLINT NULL | 최근 HTTP 상태 |
| `last_delivered_at` | DATETIME(3) NULL | |
| `consecutive_failures` | SMALLINT NOT NULL DEFAULT 0 | 임계 초과 시 자동 비활성(서킷브레이커) |
| 감사 | `created_at/updated_at/deleted_at/created_by_id/last_updated_by_id` | |

인덱스: `uq_we_uuid(uuid)`, `idx_we_purpose(purpose, enabled)`, `idx_we_token(api_token_id)`, `idx_we_deleted(deleted_at)`.

### 4.5 `monitors` — 모니터 클라이언트(로컬 디스플레이/키오스크)

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `id` | BIGINT PK | Snowflake |
| `uuid` | CHAR(32) | UNIQUE, 외부 노출(토큰 subject) |
| `name` | VARCHAR(120) NOT NULL | "로비 1층 모니터" |
| `dashboard_id` | BIGINT NOT NULL | 표시할 대시보드(논리 FK dashboards.id). idx |
| `rotation` | JSON NULL | (선택) 다중 대시보드 순환: `[{dashboard_id, dwell_s}]`(P5 기본은 단일 dashboard, rotation은 옵션) |
| `status` | VARCHAR(16) NOT NULL DEFAULT 'unpaired' | `unpaired`(미페어링) / `pending`(코드 발급·대기) / `paired`(활성) / `revoked` |
| `token_version` | INT NOT NULL DEFAULT 0 | **모니터 토큰 일괄 무효화**용(해지·대시보드 변경 시 +1) |
| `paired_at` | DATETIME(3) NULL | 최초 토큰 교환 시각 |
| `last_seen_at` | DATETIME(3) NULL | 마지막 토큰 갱신/heartbeat(UTC) |
| `last_ip` | VARCHAR(64) NULL | 페어링/접속 IP |
| `user_agent` | VARCHAR(255) NULL | 기기 식별(브라우저/키오스크) |
| `device_label` | VARCHAR(120) NULL | 사용자가 단 별칭(해상도/위치 메모) |
| `settings` | JSON NULL | 키오스크 옵션: `{hide_cursor:true, show_clock:true, ratio_mode:"fit", reconnect:true}` |
| `enabled` | TINYINT(1) NOT NULL DEFAULT 1 | |
| 감사 | `created_at/updated_at/deleted_at/created_by_id/last_updated_by_id` | |

인덱스: `uq_monitors_uuid(uuid)`, `idx_monitors_dashboard(dashboard_id)`, `idx_monitors_status(status)`, `idx_monitors_deleted(deleted_at)`.

> **권한 모델(PLAN §8 정합)**: 모니터 토큰은 audience=`monitor`, `scope={"monitor_id":<uuid>, "dashboards":[<dashboard_uuid>], "actions":["read"]}`, role 없음(뷰어전용). `monitors.token_version`로 즉시 무효화. 대시보드 변경 시 token_version++ → 기존 토큰 무효(새 대시보드로 재발급). 상세 시퀀스 7.1.

### 4.6 `pairing_codes` — 60초 일회용 숫자 페어링 코드 (단명·고보안)

> 코드 평문은 **저장하지 않음**(해시 저장). 60초 만료·일회용·검증 재시도 제한. 발급은 모니터당 활성 1개만(새 발급 시 이전 무효).

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `id` | BIGINT PK | Snowflake |
| `monitor_id` | BIGINT NOT NULL | 대상 모니터. idx |
| `code_hash` | CHAR(64) NOT NULL | **SHA-256(code + server pepper)**. 평문 미저장. idx(검증 조회) |
| `code_last4` | CHAR(4) NULL | (선택) 관리 UI 표시용 마스킹("****12"는 의미 약하므로 보통 미사용; 운영상 코드 일부도 비노출 권장 → 기본 NULL) |
| `expires_at` | DATETIME(3) NOT NULL | 발급+60초(UTC). idx |
| `attempts` | SMALLINT NOT NULL DEFAULT 0 | 검증 실패 횟수(상한 5 → 무효) |
| `max_attempts` | SMALLINT NOT NULL DEFAULT 5 | |
| `consumed_at` | DATETIME(3) NULL | 교환 완료(일회성 — NOT NULL이면 재사용 거부) |
| `created_ip` | VARCHAR(64) NULL | 발급 관리자 IP |
| `created_by_id` | BIGINT NULL | 발급 관리자 |
| `created_at` | DATETIME(3) NOT NULL | |

인덱스: `idx_pc_monitor(monitor_id)`, `idx_pc_code(code_hash)`, `idx_pc_expires(expires_at)`. 정리: Celery `pairing_code_cleanup`(매 5분, 만료/소비 코드 삭제). 활성 유일성: 발급 시 동일 monitor의 미소비·미만료 코드를 먼저 만료 처리(앱 트랜잭션 보장).

> **보안 핵심**: ① 코드는 서버 CSPRNG(`secrets.randbelow`)로 6자리 생성, `code_hash`만 저장. ② 검증은 `monitor_id`(또는 코드 자체)로 행을 찾고 해시·만료·소비·시도횟수 점검. ③ **무차별 대입 방지**: 코드만으로 전역 조회 시 6자리=10^6 공간이라 60초·시도제한·전역 rate limit(IP/엔드포인트) 필수. ④ 교환 성공 시 즉시 `consumed_at` 세팅(원자적 UPDATE … WHERE consumed_at IS NULL). 상세 7.1.

### 4.7 `notification_subscriptions` — 사용자/이벤트별 알림 구독·정책

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `id` | BIGINT PK | Snowflake |
| `user_id` | BIGINT NOT NULL | 구독 주체. idx `(user_id)` |
| `channel` | VARCHAR(16) NOT NULL | `push` / `email` / `webhook` / `inapp` |
| `event_types` | JSON NULL | 구독 이벤트 타입(NULL=전체): `["motion","intrusion","object"]` |
| `camera_ids` | JSON NULL | 카메라 스코프(NULL=권한 내 전체). **권한 교집합 강제** |
| `object_classes` | JSON NULL | object 트리거 시 클래스 필터(person/car…) |
| `min_priority` | VARCHAR(8) NOT NULL DEFAULT 'normal' | `low`/`normal`/`high`/`critical` — 이 이상만 |
| `muted` | TINYINT(1) NOT NULL DEFAULT 0 | 전체 음소거 |
| `muted_until` | DATETIME(3) NULL | 임시 음소거 만료(스누즈) |
| `batch_window_s` | SMALLINT NOT NULL DEFAULT 0 | 통합(batching) 창(0=즉시, >0이면 창 동안 묶어 1건). 채널별 |
| `quiet_hours` | JSON NULL | 조용시간(KST): `{tz:"Asia/Seoul", ranges:[{start:"22:00",end:"07:00"}], allow_critical:true}` |
| `webhook_endpoint_id` | BIGINT NULL | channel=webhook 시 대상(webhook_endpoints.id) |
| `enabled` | TINYINT(1) NOT NULL DEFAULT 1 | |
| 감사 | `created_at/updated_at/deleted_at` | (created_by=user 본인) |

인덱스: `idx_ns_user(user_id)`, `idx_ns_channel(channel, enabled)`, `idx_ns_deleted(deleted_at)`. 유니크(앱 보장): `(user_id, channel, 정규화된 스코프)` 중복 방지는 컨트롤러에서.

### 4.8 `push_subscriptions` — 웹푸시(VAPID) 엔드포인트

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `id` | BIGINT PK | Snowflake |
| `user_id` | BIGINT NOT NULL | 소유자. idx |
| `endpoint` | VARCHAR(1024) NOT NULL | 브라우저 푸시 서비스 엔드포인트(FCM/Mozilla/WNS). idx(해시) |
| `endpoint_hash` | CHAR(64) NOT NULL | SHA-256(endpoint) — 중복/조회용 UNIQUE |
| `p256dh` | VARCHAR(255) NOT NULL | 구독 공개키(ECDH) |
| `auth` | VARCHAR(64) NOT NULL | 인증 시크릿(base64url) |
| `ua` | VARCHAR(255) NULL | 등록 기기 |
| `expiration_ts` | DATETIME(3) NULL | 구독 만료(있으면) |
| `enabled` | TINYINT(1) NOT NULL DEFAULT 1 | 410 Gone 수신 시 비활성 |
| `last_success_at` | DATETIME(3) NULL | |
| `created_at`/`updated_at`/`deleted_at` | DATETIME(3) | |

인덱스: `uq_ps_endpoint_hash(endpoint_hash)`, `idx_ps_user(user_id)`, `idx_ps_deleted(deleted_at)`. p256dh/auth는 푸시 서비스에 전달되는 클라이언트 생성값(서버 비밀 아님)이나, 노출 최소화를 위해 응답에 미포함.

### 4.9 `notifications` — 인앱 알림 센터 + 발송 기록(고빈도)

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `id` | BIGINT PK | Snowflake |
| `user_id` | BIGINT NOT NULL | 수신자. idx `(user_id, created_at)` |
| `event_id` | BIGINT NULL | 원천 이벤트. idx |
| `rule_id` | BIGINT NULL | 규칙 발 알림이면 |
| `camera_id` | BIGINT NULL | |
| `type` | VARCHAR(32) NOT NULL | `event`/`rule`/`system` |
| `priority` | VARCHAR(8) NOT NULL DEFAULT 'normal' | low/normal/high/critical |
| `title` | VARCHAR(200) NOT NULL | |
| `body` | VARCHAR(500) NULL | |
| `snapshot_path` | VARCHAR(512) NULL | 썸네일(서명 URL로 제공) |
| `deeplink` | VARCHAR(255) NULL | `/events/{id}` 등 |
| `channels_sent` | JSON NULL | `{"push":"sent","email":"sent","inapp":"sent"}`(채널별 결과) |
| `read_at` | DATETIME(3) NULL | 인앱 읽음(UTC). idx 부분 |
| `created_at` | DATETIME(3) NOT NULL | idx |
| `deleted_at` | DATETIME(3) NULL | |

인덱스: `idx_n_user_ts(user_id, created_at)`, `idx_n_unread(user_id, read_at)`, `idx_n_event(event_id)`, `idx_n_deleted(deleted_at)`. 보존: `notification_retention`(기본 60일).

### 4.10 `api_tokens` — 외부 API/HA 연동 scoped 서비스 토큰

> PLAN §8: audience=`api` scoped 서비스 토큰. JWT(무상태)와 **불투명 토큰(opaque, DB 조회)** 중 외부 API는 **장수명·해지 즉시성**이 중요하므로 **불투명 토큰(해시 저장) 권장**(요청마다 DB/Redis 1회 조회로 scope·해지 확인). 짧은 만료가 필요한 케이스는 JWT(aud=api)도 병행 가능하나 기본은 불투명.

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `id` | BIGINT PK | Snowflake |
| `uuid` | CHAR(32) | UNIQUE |
| `name` | VARCHAR(120) NOT NULL | "Home Assistant", "Grafana" |
| `token_prefix` | CHAR(8) NOT NULL | 토큰 앞 8자(식별·로그용, 비밀 아님). idx |
| `token_hash` | CHAR(64) NOT NULL | SHA-256(token + pepper). **평문 미저장**. UNIQUE |
| `scopes` | JSON NOT NULL | 권한 scope: `{"events":["read"], "cameras":["read"], "state":["read"], "snapshots":["read"]}` (RBAC resource:action 부분집합) |
| `camera_ids` | JSON NULL | 접근 가능 카메라(NULL=전체). 응답 교집합 강제 |
| `expires_at` | DATETIME(3) NULL | 만료(NULL=무기한, 권장 회전) |
| `last_used_at` | DATETIME(3) NULL | |
| `last_ip` | VARCHAR(64) NULL | |
| `revoked_at` | DATETIME(3) NULL | 해지(즉시 무효). idx |
| `rate_limit_per_min` | SMALLINT NOT NULL DEFAULT 120 | 토큰별 rate limit |
| 감사 | `created_at/updated_at/created_by_id/last_updated_by_id` | (soft delete 대신 revoked_at) |

인덱스: `uq_api_uuid(uuid)`, `uq_api_hash(token_hash)`, `idx_api_prefix(token_prefix)`, `idx_api_revoked(revoked_at)`.

### 4.11 마이그레이션 SQL 스케치 (MySQL 8, InnoDB/utf8mb4)

```sql
-- rules ------------------------------------------------------------------
CREATE TABLE rules (
  id                 BIGINT       NOT NULL PRIMARY KEY,
  uuid               CHAR(32)     NOT NULL,
  name               VARCHAR(120) NOT NULL,
  description        VARCHAR(500) NULL,
  enabled            TINYINT(1)   NOT NULL DEFAULT 1,
  priority           SMALLINT     NOT NULL DEFAULT 0,
  stop_on_match      TINYINT(1)   NOT NULL DEFAULT 0,
  trigger_type       VARCHAR(16)  NOT NULL,
  `trigger`          JSON         NOT NULL,
  `condition`        JSON         NOT NULL,
  actions            JSON         NOT NULL,
  cooldown_s         SMALLINT     NOT NULL DEFAULT 30,
  debounce_s         SMALLINT     NOT NULL DEFAULT 0,
  dedup_scope        VARCHAR(16)  NOT NULL DEFAULT 'camera',
  max_per_hour       SMALLINT     NULL,
  last_triggered_ts  DATETIME(3)  NULL,
  created_at         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  deleted_at         DATETIME(3)  NULL,
  created_by_id      BIGINT       NULL,
  last_updated_by_id BIGINT       NULL,
  UNIQUE KEY uq_rules_uuid (uuid),
  KEY idx_rules_enabled_pri (enabled, priority),
  KEY idx_rules_trigger (trigger_type, enabled),
  KEY idx_rules_deleted (deleted_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
-- 주의: trigger/condition 은 MySQL 예약어 → 백틱 필수.

-- rule_executions -------------------------------------------------------
CREATE TABLE rule_executions (
  id              BIGINT       NOT NULL PRIMARY KEY,
  rule_id         BIGINT       NOT NULL,
  trigger_type    VARCHAR(16)  NOT NULL,
  event_id        BIGINT       NULL,
  camera_id       BIGINT       NULL,
  matched         TINYINT(1)   NOT NULL,
  skip_reason     VARCHAR(32)  NULL,
  idempotency_key VARCHAR(120) NULL,
  action_results  JSON         NULL,
  status          VARCHAR(16)  NOT NULL,
  started_ts      DATETIME(3)  NULL,
  finished_ts     DATETIME(3)  NULL,
  duration_ms     INT          NULL,
  celery_task_id  VARCHAR(64)  NULL,
  created_at      DATETIME(3)  NOT NULL,
  deleted_at      DATETIME(3)  NULL,
  KEY idx_re_rule_ts (rule_id, created_at),
  KEY idx_re_cam_ts (camera_id, created_at),
  KEY idx_re_event (event_id),
  KEY idx_re_idem (idempotency_key),
  KEY idx_re_status (status, created_at),
  KEY idx_re_deleted (deleted_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- action_targets --------------------------------------------------------
CREATE TABLE action_targets (
  id                 BIGINT       NOT NULL PRIMARY KEY,
  uuid               CHAR(32)     NOT NULL,
  type               VARCHAR(16)  NOT NULL,
  name               VARCHAR(120) NOT NULL,
  vendor             VARCHAR(40)  NULL,
  protocol           VARCHAR(24)  NOT NULL,
  host               VARCHAR(190) NULL,
  port               INT          NULL,
  config             JSON         NOT NULL,
  username_enc       VARBINARY(512) NULL,
  password_enc       VARBINARY(512) NULL,
  cred_key_id        VARCHAR(16)  NULL,
  camera_id          BIGINT       NULL,
  enabled            TINYINT(1)   NOT NULL DEFAULT 1,
  status             VARCHAR(16)  NOT NULL DEFAULT 'unknown',
  last_checked_at    DATETIME(3)  NULL,
  created_at         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  deleted_at         DATETIME(3)  NULL,
  created_by_id      BIGINT       NULL,
  last_updated_by_id BIGINT       NULL,
  UNIQUE KEY uq_at_uuid (uuid),
  KEY idx_at_type (type, enabled),
  KEY idx_at_camera (camera_id),
  KEY idx_at_deleted (deleted_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- webhook_endpoints -----------------------------------------------------
CREATE TABLE webhook_endpoints (
  id                   BIGINT        NOT NULL PRIMARY KEY,
  uuid                 CHAR(32)      NOT NULL,
  name                 VARCHAR(120)  NOT NULL,
  url                  VARCHAR(1024) NOT NULL,
  secret_enc           VARBINARY(512) NULL,
  cred_key_id          VARCHAR(16)   NULL,
  headers              JSON          NULL,
  timeout_ms           INT           NOT NULL DEFAULT 5000,
  max_retries          SMALLINT      NOT NULL DEFAULT 3,
  verify_tls           TINYINT(1)    NOT NULL DEFAULT 1,
  purpose              VARCHAR(16)   NOT NULL DEFAULT 'action',
  subscription_filter  JSON          NULL,
  api_token_id         BIGINT        NULL,
  enabled              TINYINT(1)    NOT NULL DEFAULT 1,
  last_status          SMALLINT      NULL,
  last_delivered_at    DATETIME(3)   NULL,
  consecutive_failures SMALLINT      NOT NULL DEFAULT 0,
  created_at           DATETIME(3)   NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at           DATETIME(3)   NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  deleted_at           DATETIME(3)   NULL,
  created_by_id        BIGINT        NULL,
  last_updated_by_id   BIGINT        NULL,
  UNIQUE KEY uq_we_uuid (uuid),
  KEY idx_we_purpose (purpose, enabled),
  KEY idx_we_token (api_token_id),
  KEY idx_we_deleted (deleted_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- monitors --------------------------------------------------------------
CREATE TABLE monitors (
  id                 BIGINT       NOT NULL PRIMARY KEY,
  uuid               CHAR(32)     NOT NULL,
  name               VARCHAR(120) NOT NULL,
  dashboard_id       BIGINT       NOT NULL,
  rotation           JSON         NULL,
  status             VARCHAR(16)  NOT NULL DEFAULT 'unpaired',
  token_version      INT          NOT NULL DEFAULT 0,
  paired_at          DATETIME(3)  NULL,
  last_seen_at       DATETIME(3)  NULL,
  last_ip            VARCHAR(64)  NULL,
  user_agent         VARCHAR(255) NULL,
  device_label       VARCHAR(120) NULL,
  settings           JSON         NULL,
  enabled            TINYINT(1)   NOT NULL DEFAULT 1,
  created_at         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  deleted_at         DATETIME(3)  NULL,
  created_by_id      BIGINT       NULL,
  last_updated_by_id BIGINT       NULL,
  UNIQUE KEY uq_monitors_uuid (uuid),
  KEY idx_monitors_dashboard (dashboard_id),
  KEY idx_monitors_status (status),
  KEY idx_monitors_deleted (deleted_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- pairing_codes ---------------------------------------------------------
CREATE TABLE pairing_codes (
  id            BIGINT      NOT NULL PRIMARY KEY,
  monitor_id    BIGINT      NOT NULL,
  code_hash     CHAR(64)    NOT NULL,
  code_last4    CHAR(4)     NULL,
  expires_at    DATETIME(3) NOT NULL,
  attempts      SMALLINT    NOT NULL DEFAULT 0,
  max_attempts  SMALLINT    NOT NULL DEFAULT 5,
  consumed_at   DATETIME(3) NULL,
  created_ip    VARCHAR(64) NULL,
  created_by_id BIGINT      NULL,
  created_at    DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  KEY idx_pc_monitor (monitor_id),
  KEY idx_pc_code (code_hash),
  KEY idx_pc_expires (expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- notification_subscriptions -------------------------------------------
CREATE TABLE notification_subscriptions (
  id                  BIGINT      NOT NULL PRIMARY KEY,
  user_id             BIGINT      NOT NULL,
  channel             VARCHAR(16) NOT NULL,
  event_types         JSON        NULL,
  camera_ids          JSON        NULL,
  object_classes      JSON        NULL,
  min_priority        VARCHAR(8)  NOT NULL DEFAULT 'normal',
  muted               TINYINT(1)  NOT NULL DEFAULT 0,
  muted_until         DATETIME(3) NULL,
  batch_window_s      SMALLINT    NOT NULL DEFAULT 0,
  quiet_hours         JSON        NULL,
  webhook_endpoint_id BIGINT      NULL,
  enabled             TINYINT(1)  NOT NULL DEFAULT 1,
  created_at          DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at          DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  deleted_at          DATETIME(3) NULL,
  KEY idx_ns_user (user_id),
  KEY idx_ns_channel (channel, enabled),
  KEY idx_ns_deleted (deleted_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- push_subscriptions ----------------------------------------------------
CREATE TABLE push_subscriptions (
  id              BIGINT        NOT NULL PRIMARY KEY,
  user_id         BIGINT        NOT NULL,
  endpoint        VARCHAR(1024) NOT NULL,
  endpoint_hash   CHAR(64)      NOT NULL,
  p256dh          VARCHAR(255)  NOT NULL,
  auth            VARCHAR(64)   NOT NULL,
  ua              VARCHAR(255)  NULL,
  expiration_ts   DATETIME(3)   NULL,
  enabled         TINYINT(1)    NOT NULL DEFAULT 1,
  last_success_at DATETIME(3)   NULL,
  created_at      DATETIME(3)   NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at      DATETIME(3)   NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  deleted_at      DATETIME(3)   NULL,
  UNIQUE KEY uq_ps_endpoint_hash (endpoint_hash),
  KEY idx_ps_user (user_id),
  KEY idx_ps_deleted (deleted_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- notifications ---------------------------------------------------------
CREATE TABLE notifications (
  id            BIGINT       NOT NULL PRIMARY KEY,
  user_id       BIGINT       NOT NULL,
  event_id      BIGINT       NULL,
  rule_id       BIGINT       NULL,
  camera_id     BIGINT       NULL,
  type          VARCHAR(32)  NOT NULL,
  priority      VARCHAR(8)   NOT NULL DEFAULT 'normal',
  title         VARCHAR(200) NOT NULL,
  body          VARCHAR(500) NULL,
  snapshot_path VARCHAR(512) NULL,
  deeplink      VARCHAR(255) NULL,
  channels_sent JSON         NULL,
  read_at       DATETIME(3)  NULL,
  created_at    DATETIME(3)  NOT NULL,
  deleted_at    DATETIME(3)  NULL,
  KEY idx_n_user_ts (user_id, created_at),
  KEY idx_n_unread (user_id, read_at),
  KEY idx_n_event (event_id),
  KEY idx_n_deleted (deleted_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- api_tokens ------------------------------------------------------------
CREATE TABLE api_tokens (
  id                 BIGINT       NOT NULL PRIMARY KEY,
  uuid               CHAR(32)     NOT NULL,
  name               VARCHAR(120) NOT NULL,
  token_prefix       CHAR(8)      NOT NULL,
  token_hash         CHAR(64)     NOT NULL,
  scopes             JSON         NOT NULL,
  camera_ids         JSON         NULL,
  expires_at         DATETIME(3)  NULL,
  last_used_at       DATETIME(3)  NULL,
  last_ip            VARCHAR(64)  NULL,
  revoked_at         DATETIME(3)  NULL,
  rate_limit_per_min SMALLINT     NOT NULL DEFAULT 120,
  created_at         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  created_by_id      BIGINT       NULL,
  last_updated_by_id BIGINT       NULL,
  UNIQUE KEY uq_api_uuid (uuid),
  UNIQUE KEY uq_api_hash (token_hash),
  KEY idx_api_prefix (token_prefix),
  KEY idx_api_revoked (revoked_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

> **P3 영향 없음(읽기만)**: P5는 `event_outbox.status`를 `pending→consumed`로 갱신(컨슈머)하는 것 외 P3 스키마를 변경하지 않는다. 단 P4가 object를 outbox로 흘리지 않으면(별도 큐), P5에 detection 컨슈머 추가 필요(§10 Q1).

### 4.12 권한맵(RBAC) 확장 — P5 신규 권한키

P0 권한 카탈로그(`permissions`)에 append, `admin`은 전권. 표기는 PLAN §12.2 canonical(`resource:action` 콜론):

| resource:action | 적용 범위 | 설명 |
|---|---|---|
| `rules:read` / `rules:create` / `rules:update` / `rules:delete` | 규칙 | 규칙 CRUD. 수동 트리거(`/rules/{uuid}/trigger`)·테스트 발사(`/rules/{uuid}/test`)·활성토글은 `rules:update`에 포함 |
| `targets:read` / `targets:manage` | 액션 대상(`action_targets`) + 웹훅(`webhook_endpoints`) | read=조회, manage=생성/수정/삭제/테스트(스피커·IO·이메일 방송, 웹훅 발송). 웹훅 엔드포인트도 동일 `targets` 자원 |
| `monitors:read` / `monitors:manage` | 모니터 | read=목록, manage=생성/수정/삭제·페어링 코드 발급·해지·대시보드 재지정 |
| `notifications:read` / `notifications:update` | 알림 | read=본인 알림 센터·구독 조회, update=본인 구독설정·읽음·푸시 구독 관리 |
| `api_tokens:manage` | 외부 API 토큰 | 발급/해지/조회(admin) |

> `targets`(웹훅 포함)·`monitors`·`api_tokens` 관리는 기본 **admin** 권장(보안 표면). 일반 user는 `notifications`(본인)·`rules:read`·`targets:read` 정도. 페어링 코드 발급·해지(`monitors:manage`)는 admin 전용 기본.

---

## 5. 백엔드 설계

### 5.1 디렉터리 배치 (PLAN §6 구조 준수)

```
server/
├─ view/api/
│  ├─ rule.py              # 규칙 CRUD / 수동 트리거 / 테스트 발사 / 실행로그
│  ├─ action_target.py     # speaker/io/email 대상 CRUD / 헬스체크 / 테스트(방송·출력)
│  ├─ webhook.py           # 웹훅 엔드포인트 CRUD / 테스트 발송
│  ├─ monitor.py           # 모니터 CRUD / 페어링 코드 발급·재발급 / 해지 / 대시보드 재지정
│  ├─ pairing.py           # (공개) 코드 검증·토큰 교환 / 모니터 토큰 refresh / heartbeat
│  ├─ notification.py      # 알림 센터(목록/읽음) + 구독(notification_subscriptions) CRUD
│  ├─ push.py              # 웹푸시 구독 등록/해지 / VAPID public key 조회 / 테스트 푸시
│  └─ external/            # 외부 API(audience=api)
│     ├─ events.py         # GET 이벤트 조회(scoped)
│     ├─ state.py          # 시스템/카메라 상태(HA 폴링)
│     ├─ subscriptions.py  # 웹훅 구독 등록/해지 (purpose=subscription)
│     └─ stream.py         # SSE 이벤트 스트림
├─ controller/
│  ├─ rule.py              # CRUD + 검증(JSON 스키마) + 수동 트리거 enqueue
│  ├─ rule_engine.py       # (얇은) 트리거 수신 → 평가 위임(서비스 호출)
│  ├─ action_target.py
│  ├─ webhook.py
│  ├─ monitor.py           # 모니터 lifecycle, token_version 관리
│  ├─ pairing.py           # 코드 생성/검증/교환 (보안 핵심)
│  ├─ notification.py
│  └─ api_token.py         # 외부 토큰 발급/해지/검증
├─ service/
│  ├─ rule_evaluator.py    # 활성 규칙 캐시·조건 매칭·결합·쿨다운/멱등 (핵심, 순수성 높임)
│  ├─ rule_dispatcher.py   # 매칭 규칙 → 액션 Celery 디스패치 + rule_executions 기록
│  ├─ trigger_router.py    # outbox/시그널/detection/schedule/manual → 정규화 TriggerEvent
│  ├─ action_runner.py     # 액션 type → 드라이버 호출 오케스트레이션(재시도/타임아웃)
│  ├─ monitor_token.py     # monitor scoped JWT 발급/검증/갱신/해지 (TokenService 위임)
│  ├─ pairing_code.py      # 코드 생성(CSPRNG)·해시·검증·rate limit
│  ├─ notification_router.py # 이벤트/규칙 → 구독 매칭 → 채널별 발송(batch/quiet/priority)
│  ├─ webpush.py           # VAPID 서명·페이로드 암호화 위임(pywebpush)
│  └─ api_token.py         # 불투명 토큰 검증·scope 체크·rate limit
├─ driver/
│  ├─ speaker.py           # IP/SIP 스피커 (vendor_http / onvif_backchannel / sip)
│  ├─ io.py                # IO 모듈 (onvif_relay / vendor_http)
│  ├─ webhook.py           # 서명·재시도·타임아웃 HTTP POST
│  ├─ email.py             # SMTP (ams email.py 패턴 이식)
│  └─ push.py              # pywebpush 래퍼 (VAPID)
└─ task/list/
   ├─ outbox_consumer.py   # event_outbox 폴링 → trigger_router → rule_evaluator (beat 또는 상시)
   ├─ rule_action.py       # 액션 실행 Celery 태스크(드라이버 호출, 재시도)
   ├─ schedule_trigger.py  # schedule 트리거 규칙 → cron 평가 → 발화 (beat */1m)
   ├─ notification_dispatch.py # 알림 채널 발송(push/email/webhook) + batch flush
   ├─ webhook_delivery.py  # 웹훅 발송(재시도 큐, 서킷브레이커)
   ├─ target_healthcheck.py# action_targets 헬스체크 (beat */5m)
   ├─ pairing_code_cleanup.py # 만료/소비 코드 정리 (beat */5m)
   └─ p5_retention.py      # rule_executions/notifications 보존 정리 (beat 03:30 UTC)
```

### 5.2 API 표 (내부 — 관리/사용자)

> 공통: `/api/v1` prefix, `Authorization: Bearer`(audience=`web`). 권한 `@login_required` + `@permission_required('<resource>','<action>')`. 카메라 스코프 권한 사용자는 응답·구독에서 비인가 카메라 제외(교집합). 페이지네이션 ams 호환(`page, items_per_page, sort, order, q`).

| Method | Path | 권한 | 요청 | 응답(`data`) |
|---|---|---|---|---|
| GET | `/rules` | rules:read | paging, `trigger_type?`, `enabled?` | `{count, items:[RuleDTO]}` |
| POST | `/rules` | rules:create | `RuleInput`(name/trigger_type/trigger/condition/actions/…) | `RuleDTO` |
| GET | `/rules/{uuid}` | rules:read | — | `RuleDTO`(actions의 target 요약 포함) |
| PUT | `/rules/{uuid}` | rules:update | `RuleInput` | `RuleDTO`(캐시 무효화) |
| DELETE | `/rules/{uuid}` | rules:delete | — | soft delete |
| POST | `/rules/{uuid}/enable` | rules:update | `{enabled:bool}` | `RuleDTO` |
| POST | `/rules/{uuid}/trigger` | rules:update | `{camera_id?, context?}` | 수동 발화 → `{execution_id}` |
| POST | `/rules/{uuid}/test` | rules:update | `{dry_run:true}` | 액션 미실행 평가 결과(매칭/스킵사유) 또는 실제 1회 발사 |
| GET | `/rules/{uuid}/executions` | rules:read | paging, `status?`, `from/to` | `{count, items:[RuleExecutionDTO]}` |
| GET | `/rule-executions` | rules:read | paging, `rule_id?`, `camera_id?`, `status?` | 전체 실행 로그 |
| GET | `/action-targets` | targets:read | `type?` | `[ActionTargetDTO]`(자격증명 미포함) |
| POST | `/action-targets` | targets:manage | `ActionTargetInput`(자격증명 평문→암호화) | `ActionTargetDTO` |
| PUT | `/action-targets/{uuid}` | targets:manage | `ActionTargetInput` | `ActionTargetDTO` |
| DELETE | `/action-targets/{uuid}` | targets:manage | — | soft delete(참조 규칙 경고) |
| POST | `/action-targets/{uuid}/test` | targets:manage | speaker `{clip_id|tts_text}`, io `{output_id, action:"on|off|pulse", pulse_ms?}` | `{result, latency_ms}` |
| POST | `/action-targets/{uuid}/healthcheck` | targets:read | — | `{status, detail}` |
| GET | `/webhooks` | targets:read | `purpose?` | `[WebhookDTO]`(secret 미포함, `has_secret:true`) |
| POST | `/webhooks` | targets:manage | `WebhookInput` | `WebhookDTO` |
| PUT | `/webhooks/{uuid}` | targets:manage | `WebhookInput`(secret 재설정 시만 평문) | `WebhookDTO` |
| DELETE | `/webhooks/{uuid}` | targets:manage | — | soft delete |
| POST | `/webhooks/{uuid}/test` | targets:manage | `{sample_event?}` | `{http_status, latency_ms, signature_sent}` |
| GET | `/monitors` | monitors:read | paging | `[MonitorDTO]`(status/last_seen/dashboard) |
| POST | `/monitors` | monitors:manage | `{name, dashboard_uuid, settings?, device_label?}` | `MonitorDTO`(status=unpaired) |
| PUT | `/monitors/{uuid}` | monitors:manage | `{name?, dashboard_uuid?, settings?, rotation?}` | `MonitorDTO`(대시보드 변경 시 token_version++) |
| DELETE | `/monitors/{uuid}` | monitors:manage | — | soft delete + token_version++(토큰 무효) |
| POST | `/monitors/{uuid}/pair-code` | monitors:manage | — | `{code, expires_in:60, expires_at}` (코드 평문은 **응답 1회만**, 저장 안 함) |
| POST | `/monitors/{uuid}/revoke` | monitors:manage | — | token_version++ → 즉시 무효. `MonitorDTO`(status=revoked) |
| GET | `/notifications` | notifications:read | paging, `unread?` | `{count, unread, items:[NotificationDTO]}` |
| POST | `/notifications/{id}/read` | notifications:update | — | `{}` |
| POST | `/notifications/read-all` | notifications:update | — | `{updated}` |
| GET | `/notification-subscriptions` | notifications:read | — | `[SubscriptionDTO]`(본인) |
| POST | `/notification-subscriptions` | notifications:update | `SubscriptionInput` | `SubscriptionDTO`(본인 user_id 강제) |
| PUT | `/notification-subscriptions/{id}` | notifications:update | `SubscriptionInput` | 본인 것만 |
| DELETE | `/notification-subscriptions/{id}` | notifications:update | — | soft delete |
| GET | `/push/vapid-public-key` | auth | — | `{public_key}`(VAPID 공개키, base64url) |
| POST | `/push/subscriptions` | notifications:update | `{endpoint, keys:{p256dh, auth}, ua?}` | `{id}`(중복 endpoint upsert) |
| DELETE | `/push/subscriptions` | notifications:update | `{endpoint}` | 해지(soft) |
| POST | `/push/test` | notifications:update | — | 본인 구독 전체에 테스트 푸시 |
| GET | `/api-tokens` | api_tokens:manage | — | `[ApiTokenDTO]`(prefix만, 평문 없음) |
| POST | `/api-tokens` | api_tokens:manage | `{name, scopes, camera_ids?, expires_at?}` | `{token}`(평문 **1회만**) + `ApiTokenDTO` |
| POST | `/api-tokens/{uuid}/revoke` | api_tokens:manage | — | `revoked_at` 세팅 |

### 5.3 API 표 (모니터 페어링 — 일부 공개) & (외부 API — audience=api)

**모니터(페어링·뷰어전용)** — `/api/v1/pairing/*`, `/api/v1/monitor/*`:

| Method | Path | 인증 | 요청 | 응답 |
|---|---|---|---|---|
| POST | `/pairing/claim` | **public**(rate-limited) | `{code}`(6자리) | 성공: `{monitor:{uuid,name,dashboard_uuid}, access_token, token_type:"Bearer", expires_in, refresh_token}` (audience=monitor). 실패: 400 `invalid_or_expired` |
| POST | `/monitor/refresh` | monitor refresh | `{refresh_token}` | 새 monitor access(+회전 refresh). token_version 불일치/해지면 401 → 키오스크는 재페어링 화면 |
| GET | `/monitor/me` | monitor access | — | `{monitor:{uuid,name,settings}, dashboard:{uuid,layout}, cameras:[{uuid,name,streams}]}` (뷰어전용 — 자격증명/관리정보 제외) |
| POST | `/monitor/heartbeat` | monitor access | `{}` | `last_seen_at` 갱신. `{server_time, dashboard_version}`(레이아웃 변경 감지) |
| GET | `/monitor/live/{camera_uuid}/webrtc` | monitor access(scope: 해당 dashboard의 카메라만) | WS | P1 라이브 시그널링 재사용(scope 검증 후 go2rtc 릴레이) |

> 모니터 access는 P1 라이브(WebRTC/MSE) 엔드포인트를 **scope 제한**으로 재사용: 토큰의 `scope.dashboards`에 속한 대시보드의 카메라 uuid 집합에 한해 시그널링 허용. PTZ·다운로드·이벤트 쓰기 등은 전부 거부(뷰어전용).

**외부 API(audience=api / 불투명 토큰)** — `/api/v1/ext/*`. 인증: `Authorization: Bearer <opaque>` 또는 `X-API-Key`. `@api_token_required(scope)` 데코레이터(아래 5.6):

| Method | Path | scope | 요청 | 응답 |
|---|---|---|---|---|
| GET | `/ext/events` | events:read | `camera_id[]?`, `type[]?`, `from/to`, paging | 이벤트 목록(토큰 camera_ids 교집합) |
| GET | `/ext/events/{id}` | events:read | — | 이벤트 상세(raw 제외) |
| GET | `/ext/events/{id}/snapshot` | snapshots:read | — | `image/jpeg`(서명·캐시 private) |
| GET | `/ext/cameras` | cameras:read | — | 카메라 목록(상태·이름만, 자격증명·host 제외) |
| GET | `/ext/state` | state:read | — | `{cameras:[{uuid,name,online,recording}], storage:{...}, system:{version,uptime}}` (HA 폴링용) |
| POST | `/ext/subscriptions` | events:read | `{url, secret?, event_types?, camera_ids?}` | 웹훅 구독 등록(webhook_endpoints purpose=subscription, api_token_id=현재 토큰) |
| DELETE | `/ext/subscriptions/{uuid}` | events:read | — | 구독 해지(소유 토큰만) |
| GET | `/ext/stream` | events:read | SSE | `text/event-stream` — 이벤트 실시간(필터·camera 교집합, heartbeat 주석) |

### 5.4 controller/service 책임 분리

- **view**: 파라미터 검증(`bad_request`), 권한·스코프 교집합, controller 호출, 예외→응답 매핑(ams 패턴). 페어링/외부 API view는 별도 인증(공개+rate limit / api_token).
- **controller**: 트랜잭션 경계·DTO 조립·JSON 스키마 검증. 무거운 작업(액션 실행·알림 발송·웹훅)은 Celery `.delay()` 위임. 자격증명 평문→`util.crypto` 암호화, 응답 마스킹.
- **service**:
  - `rule_evaluator`: 활성 규칙 캐시(Redis `axp:rules:active` 또는 프로세스+버전), `TriggerEvent` 입력 → 후보 규칙 필터(trigger_type) → 조건 매칭(6.2) → 쿨다운/멱등/rate-limit 판정 → 매칭 규칙 목록 반환. **I/O는 Redis(쿨다운/멱등)만**, 나머지 순수 로직(테스트 용이).
  - `rule_dispatcher`: 매칭 규칙별 `rule_executions` 생성 → 액션을 `rule_action.delay()`로 디스패치 → 결과 집계 갱신.
  - `trigger_router`: 입력원(outbox row / detection / cron / manual)을 단일 `TriggerEvent` dataclass로 정규화(camera_id, type, subtype, score, classes, ts, snapshot, event_id, raw_ref).
  - `action_runner`: 액션 1건 실행(type→드라이버), 타임아웃·재시도·결과 dict 반환. webhook/push/email은 자체 재시도 큐로 위임 가능.
  - `monitor_token`: `TokenService`로 audience=monitor JWT 발급(아래 7.1 클레임), 검증(scope·token_version), 회전.
  - `pairing_code`: 코드 생성(CSPRNG 6자리)·해시·검증·소비(원자적)·rate limit.
  - `notification_router`: 이벤트/규칙 발생 → 구독자 매칭(channel·event_type·camera·class·priority·mute·quiet) → 채널별 발송(즉시 or batch 큐).
  - `webpush`/`api_token`: 각 7.3/7.6.

### 5.5 규칙 평가 엔진 의사코드 (`rule_evaluator` + `rule_dispatcher`)

트리거 진입점(트리거 소스 무관 공통):

```
def on_trigger(trig: TriggerEvent):           # trigger_router가 생성
    rules = rule_cache.active_for(trig.trigger_type)   # trigger_type 인덱스 + enabled
    rules.sort(key=lambda r: -r.priority)
    for r in rules:
        res = evaluate(r, trig)
        log = RuleExecution(rule_id=r.id, trigger_type=trig.trigger_type,
                            event_id=trig.event_id, camera_id=trig.camera_id)
        if not res.matched:
            log.matched = False; log.status = 'skipped'; log.skip_reason = res.reason
            db.add(log); db.commit()
            if res.reason in ('cooldown','rate_limited','debounced'):  # 트리거키 억제
                continue
            continue
        # 매칭 → 멱등 점검(동일 이벤트·규칙 중복 디스패치 방지)
        idem = idem_key(r, trig)                # f"{r.id}:{scope_key(r,trig)}:{trig.event_id or trig.bucket}"
        if not redis.set(f"axp:rule:idem:{idem}", 1, nx=True, ex=r.cooldown_s or 60):
            log.matched=True; log.status='skipped'; log.skip_reason='duplicate'
            db.add(log); db.commit(); continue
        log.matched = True; log.idempotency_key = idem; log.status='queued'
        db.add(log); db.commit()
        # 쿨다운 시작(매칭 시점)
        mark_cooldown(r, trig)                  # redis last_trigger_ts per dedup_scope
        # 디바운스: debounce_s>0이면 지연 후 마지막 1건만 실행(아래 노트)
        delay = r.debounce_s
        rule_action.dispatch.apply_async(args=[log.id, r.id, trig.serialize()], countdown=delay)
        r.last_triggered_ts = utc_ms()
        if r.stop_on_match:
            break
```

조건 매칭(`evaluate`):

```
def evaluate(r, trig) -> Result:
    if not r.enabled: return Result(False, 'disabled')

    # 1) 트리거 세부 매칭
    t = r.trigger
    if r.trigger_type == 'event':
        if t.get('event_types') and trig.type not in t['event_types']: return Result(False,'condition_false')
        if t.get('subtypes') and trig.subtype not in t['subtypes']:    return Result(False,'condition_false')
    elif r.trigger_type == 'object':
        if trig.type != 'object': return Result(False,'condition_false')
        if t.get('classes') and not (set(trig.classes) & set(t['classes'])): return Result(False,'condition_false')
        if t.get('min_confidence') and (trig.score or 0) < t['min_confidence']: return Result(False,'condition_false')
        if t.get('zones') and not zone_hit(trig.bbox, t['zones']):    return Result(False,'condition_false')
    # schedule/manual: 트리거 자체가 발화 → 트리거 매칭 통과

    # 2) 조건(condition) — AND 그룹
    c = r.condition
    if c.get('camera_ids') and trig.camera_id not in c['camera_ids']:  return Result(False,'condition_false')
    if c.get('min_score') and (trig.score or 0) < c['min_score']:      return Result(False,'condition_false')
    if c.get('time_ranges') and not in_time_ranges(trig.ts, c['time_ranges']):  # KST 변환
        return Result(False,'condition_false')
    if c.get('quiet_respect') and in_quiet_window(trig.ts):            return Result(False,'quiet_hours')
    if c.get('all_of') and not all(match_clause(cl, trig) for cl in c['all_of']):
        return Result(False,'condition_false')
    if c.get('any_of') and not any(match_clause(cl, trig) for cl in c['any_of']):
        return Result(False,'condition_false')

    # 3) 쿨다운 / rate limit (Redis)
    if within_cooldown(r, trig):     return Result(False, 'cooldown')
    if r.max_per_hour and over_rate(r, trig, r.max_per_hour):  return Result(False,'rate_limited')

    return Result(True, None)
```

> **디바운스 노트**: `debounce_s>0`이면 `countdown=debounce_s`로 지연 디스패치하되, 같은 dedup 스코프에 대해 Redis에 "대기 중 실행 id"를 기록하고, 디바운스 창 내 후속 트리거는 기존 대기 실행의 컨텍스트만 갱신(최신값)하고 새 디스패치는 생략(trailing-edge). 액션 태스크 진입 시 "내가 최신 대기 id인가" 확인 후 실행.

액션 디스패치 태스크(`rule_action.dispatch`):

```
@celery_use_db()
def dispatch(execution_id, rule_id, trig_serialized):
    log = RuleExecution.get(execution_id); r = Rule.get(rule_id); trig = TriggerEvent.load(trig_serialized)
    log.started_ts = utc_ms(); log.status='running'; db.commit()
    results = []
    for a in r.actions:                      # 순서 보장, delay_ms 지원
        if a.get('delay_ms'): sleep_or_reschedule(a['delay_ms'])
        try:
            res = action_runner.run(a, trig, timeout=a.get('timeout_ms', default_for(a['type'])))
            results.append({**res, 'target_id': a.get('target_id'), 'type': a['type']})
        except Exception as e:
            results.append({'target_id': a.get('target_id'), 'type': a['type'],
                            'status':'failed', 'error': str(e)[:200]})
            sentry_sdk.capture_exception(e)
            if not a.get('continue_on_error', True): break
    log.action_results = results
    log.status = summarize(results)          # success/partial/failed
    log.finished_ts = utc_ms(); log.duration_ms = log.finished_ts - log.started_ts
    db.commit()
    # 규칙 발화도 알림 대상이면 notification_router로 (push/email)는 별개 경로
```

### 5.6 데코레이터 — 외부 API 토큰 (`@api_token_required`)

```python
# server/decorator.py 확장 (P0 데코레이터 옆)
def api_token_required(*required_scopes):
    def deco(f):
        @wraps(f)
        def wrapper(*a, **kw):
            raw = extract_bearer_or_apikey(request)            # Authorization: Bearer / X-API-Key
            tok = ApiTokenService.verify(raw)                  # 해시 조회 + revoked/expires + rate limit
            if not tok: return ResponseBuilder.forbidden('invalid_token')
            if not ApiTokenService.has_scopes(tok, required_scopes):
                return ResponseBuilder.forbidden('insufficient_scope')
            g.api_token = tok                                  # camera_ids 교집합에 사용
            return f(*a, **kw)
        return wrapper
    return deco
```

- `ApiTokenService.verify`: `token_hash = sha256(raw+pepper)` → `api_tokens` 조회(인덱스 UNIQUE) → `revoked_at IS NULL` && (`expires_at` 미래) → Redis 토큰버킷 rate limit(`axp:apitok:{id}:rl`) → `last_used_at/last_ip` 비동기 갱신. 결과 짧게 캐시(예 30s) 가능(해지 즉시성과 트레이드오프 — 기본 무캐시 또는 5s).

---

## 6. 자동화 규칙 & 액션 드라이버 (프로토콜 구체)

### 6.1 트리거(trigger) 소스 & 수집

| trigger_type | 소스 | 수집 방식 | 비고 |
|---|---|---|---|
| `event` | P3 `event_outbox` + `signals.event_created` | **outbox_consumer**(beat 또는 상시 워커)가 `status='pending'` 행을 배치 조회 → `trigger_router` → `on_trigger` → 성공 시 `status='consumed'`. 시그널은 저지연 보조(중복은 멱등으로 흡수) | at-least-once. outbox가 1차 진실원 |
| `object` | P4 detection | **권장**: P4가 object를 `events`+`event_outbox`로 흘림(단일 경로). 대안: detection 전용 큐/시그널 → `trigger_router`가 동일 `TriggerEvent`로 정규화 | classes/confidence/bbox/zone 포함 |
| `schedule` | Celery beat | **schedule_trigger**(beat `*/1m`): trigger_type='schedule' 규칙 로드 → 각 `trigger.cron`을 현재 분(KST)과 매칭(`croniter`) → 매칭 규칙 발화(camera_id 없음/규칙 condition.camera_ids로 대상 지정) | 분 해상도 |
| `manual` | API/UI | `POST /rules/{uuid}/trigger` 또는 대시보드 버튼·외부 호출 → 즉시 `on_trigger`(context 전달) | 운영자 수동 방송/출력 |

`TriggerEvent`(정규화 dataclass): `{trigger_type, camera_id, type, subtype, score, classes, bbox, zone, ts(UTC ms), event_id, snapshot_path, region, raw_ref, context}`.

### 6.2 조건(condition) 모델

- **AND 기본**: 최상위 키들은 모두 충족(camera_ids ∧ time_ranges ∧ min_score ∧ …).
- **time_ranges**(KST): `[{dow:[1..7], start:"08:00", end:"18:00"}]`, 자정 넘김 분할. `trig.ts`(UTC ms)를 KST로 변환 후 요일·분 비교(P3 `schedule_resolver`와 동일 변환 유틸 재사용 권장).
- **quiet_respect**: 조건 레벨에서 조용시간이면 스킵(알림 채널과 별개; 규칙 액션 자체를 조용시간에 막고 싶을 때). 알림 조용시간은 `notification_subscriptions.quiet_hours`가 별도 처리.
- **all_of/any_of**: 절(clause) 배열로 확장 조건(예: `{field:"score", op:">=", value:70}`, `{field:"object_class", op:"in", value:["person"]}`). `match_clause`가 화이트리스트 op만 평가(SSTI/eval 금지).

### 6.3 액션 드라이버 — speaker (IP/SIP 스피커)

공통 인터페이스:

```python
# driver/speaker.py
class SpeakerDriver(Protocol):
    def play_clip(self, target: ActionTarget, clip_id: str) -> dict: ...   # 사전 업로드 클립 재생
    def play_tts(self, target: ActionTarget, text: str, lang="ko") -> dict: ...
    def stop(self, target: ActionTarget) -> dict: ...
    def healthcheck(self, target: ActionTarget) -> dict: ...

def make_speaker(target) -> SpeakerDriver:   # protocol로 분기
    return {'vendor_http': VendorHttpSpeaker, 'onvif_backchannel': OnvifBackchannelSpeaker,
            'sip': SipSpeaker}[target.protocol]()
```

프로토콜별 구체:

1. **vendor_http(권장 1순위)** — 네트워크 스피커 대부분 HTTP/VAPIX·API 제공:
   - 예) Axis 네트워크 스피커: `POST http://{host}/axis-cgi/playclip.cgi?clip={n}` 또는 미디어 클립 API(HTTP Digest 인증). 볼륨/스톱 별 CGI.
   - 예) 2N/일반: 벤더별 REST(`/api/audio/play`). `config.clips`에 `{id, name, path/clip_no}` 매핑.
   - TTS: 벤더 TTS 지원 시 텍스트 전달, 미지원 시 서버에서 TTS 합성(P5 기본은 사전 업로드 클립; TTS 엔진은 옵션/§14) → 합성 wav를 스피커에 푸시(HTTP upload+play).
2. **onvif_backchannel** — ONVIF Profile T audio backchannel(카메라 내장 스피커 등):
   - go2rtc/ffmpeg로 RTSP **backchannel**(`Require: www.onvif.org/ver20/backchannel`)에 G.711(PCMU/PCMA) 오디오를 송출. P1이 go2rtc로 카메라를 이미 등록 → backchannel 송출은 go2rtc API 또는 ffmpeg(`-f rtsp -rtsp_transport tcp`)로 PCM을 인코딩해 push.
   - 클립을 G.711 8kHz로 사전 변환(ffmpeg) 후 송출. 동시 1세션 제약 주의.
3. **sip** — SIP/RTP 인터컴/스피커(SIP 등록 또는 P2P INVITE):
   - 라이브러리: `pjsua2`(PJSIP) 또는 경량 `aiortc`/`sipsimple` 중 택1(§14). 흐름: REGISTER(선택) → INVITE(target SIP URI, SDP: PCMU/8000) → 200 OK → ACK → **RTP로 오디오 페이로드 송출**(클립 wav→PCMU 프레임 20ms) → BYE.
   - `config.sip = {uri:"sip:speaker@host", from:"sip:axp@host", realm, codec:"PCMU", proxy?}`, 자격증명 Fernet. 다중 스피커는 SIP paging group(멀티유니캐스트) 또는 순차 INVITE.
   - 짧은 방송이므로 **태스크 내 임시 UA**로 INVITE→재생→BYE(상시 등록 불필요). 동시 호출 수 제한(드라이버 세마포어).

결과 dict: `{status:"success|failed|timeout", latency_ms, detail, protocol}`. 모든 호출 timeout(기본 8s) + `sentry_sdk.capture_exception`.

### 6.4 액션 드라이버 — io (IO 모듈 / 릴레이·디지털 출력)

```python
# driver/io.py
class IoDriver(Protocol):
    def set_output(self, target, output_id, action, pulse_ms=None) -> dict: ...  # on/off/pulse
    def get_state(self, target) -> dict: ...
    def healthcheck(self, target) -> dict: ...
```

프로토콜별:

1. **onvif_relay** — ONVIF Device IO `SetRelayOutputState`:
   - `GetRelayOutputs` → 릴레이 토큰 목록(`config.outputs[].relay_index`↔token 매핑). `SetRelayOutputState(RelayOutputToken, LogicalState: active/inactive)`.
   - pulse: ONVIF `RelayOutputSettings.Mode=Monostable`(DelayTime ISO8601, 예 `PT2S`)면 한 번 active로 자동복귀, 그 외 Bistable이면 on→sleep(pulse_ms)→off를 서버가 수행. 카메라 내장 알람출력에 유용(`action_targets.camera_id`로 연관).
2. **vendor_http** — IO 컨트롤러/카메라 CGI:
   - Hikvision ISAPI: `PUT /ISAPI/System/IO/outputs/{id}/trigger`(XML `<IOPortData><outputState>high|low</outputState></IOPortData>`, Digest).
   - Hanwha SUNAPI: `GET /stw-cgi/io.cgi?msubmenu=alarmoutput&action=control&AlarmOutput.<n>.State=On`.
   - Advantech/일반 IO(ADAM 등): 벤더 REST 또는 HTTP. 펄스는 서버 타이머 또는 모듈 펄스 모드.
   - (Modbus TCP는 P6 — 산업용 IO 확장 자리만.)

펄스 구현: `action="pulse"`면 on → (pulse_ms 또는 target.config.default_pulse_ms) 후 off. 짧은 펄스(<2s)는 태스크 내 sleep, 긴 펄스는 off를 `apply_async(countdown=...)`로 분리(워커 점유 회피). 결과 dict 동일 포맷.

### 6.5 액션 드라이버 — webhook (서명·재시도·타임아웃)

```python
# driver/webhook.py
def deliver(endpoint: WebhookEndpoint, payload: dict) -> dict:
    body = json.dumps(payload, separators=(',',':')).encode()
    ts = str(int(time.time()))
    sig = hmac.new(secret, f"{ts}.".encode()+body, hashlib.sha256).hexdigest()  # secret=복호화
    headers = {
        'Content-Type': 'application/json',
        'User-Agent': 'AeroXProtect/axp',
        'X-Axp-Event': payload.get('type','event'),
        'X-Axp-Delivery': delivery_uuid,
        'X-Axp-Timestamp': ts,
        'X-Axp-Signature': f'sha256={sig}',     # 수신자는 ts.body로 재계산 검증(±5m 허용)
        **(endpoint.headers or {}),
    }
    resp = httpx.post(endpoint.url, content=body, headers=headers,
                      timeout=endpoint.timeout_ms/1000, verify=endpoint.verify_tls)
    return {'status': 'success' if resp.status_code<300 else 'failed',
            'http_status': resp.status_code, 'latency_ms': ...}
```

- **재시도**(`webhook_delivery` 태스크): 실패(네트워크/5xx/타임아웃) 시 지수 백오프(예 0→5s→30s→2m, `max_retries`). 4xx(서명/검증 거부 등)는 재시도 안 함(영구 실패). `consecutive_failures` 임계(예 10) 초과 시 endpoint 자동 비활성(서킷브레이커) + audit.
- **서명 검증 가이드**(수신측): `HMAC_SHA256(secret, "{X-Axp-Timestamp}." + raw_body)` == `X-Axp-Signature` 의 hex, 타임스탬프 신선도 검증(리플레이 방지).
- **SSRF 가드**(7.5): URL 스킴 https/http만, 사설/링크로컬/메타데이터 IP 차단(또는 명시 허용목록), 리다이렉트 비허용, DNS rebinding 방지(resolve 후 IP 검증).

### 6.6 액션 드라이버 — email (SMTP)

- ams `driver/email.py` 패턴 이식(SMTP STARTTLS, `MIMEMultipart`, 실패 시 `sentry_sdk.capture_exception`). 단 **대상 SMTP 프로필을 `action_targets(type='email')` 또는 전역 settings**에서 로드(멀티 프로필). 자격증명 Fernet.
- 내용: 이벤트/규칙 요약(카메라·타입·시각 KST) + 스냅샷 **서명 URL**(직접 경로 노출 금지, 짧은 만료 토큰) 또는 인라인 CID 첨부(옵션). i18n 템플릿(ko/en).
- 발송은 `notification_dispatch`/`rule_action` 태스크에서 비동기. rate limit(수신자별·전역)로 폭주 방지.

### 6.7 액션 드라이버 — push (웹푸시 VAPID)

- 7.3 참조(알림 절). 규칙 액션 type='push'는 "규칙 발화 시 지정 사용자/구독자에게 푸시" → 내부적으로 `notification_router`/`webpush` 재사용.

---

## 7. 모니터 클라이언트 & 알림 & 외부 API

### 7.1 모니터: 60초 페어링 → audience=monitor scoped JWT

**모니터 토큰 클레임**(PLAN §8 정합, `TokenService.issue_pair(aud='monitor', ...)`):
```json
// access (수명 ~15m, 자동 refresh)
{ "sub": "<monitor_uuid>", "aud": "monitor", "typ": "access",
  "mv": <monitors.token_version>,
  "scope": { "monitor_id": "<monitor_uuid>", "dashboards": ["<dashboard_uuid>"], "actions": ["read"] },
  "iat": ..., "exp": ..., "jti": "<uuid4>" }
// refresh (수명 ~30d, 회전)
{ "sub": "<monitor_uuid>", "aud": "monitor", "typ": "refresh",
  "mv": <token_version>, "fid": "<family_id>", "iat":..., "exp":..., "jti":"..." }
```
- **role 없음**(뷰어전용). 검증기는 `aud=='monitor'`면 RBAC 권한맵을 적용하지 않고 **scope 기반 인가**만 수행: 요청 리소스가 `scope.dashboards`/그 카메라 집합에 속하고 action이 `read`일 때만 허용.
- **무효화**: `mv != monitors.token_version` 이면 무효(해지·대시보드 변경 시 token_version++). 추가로 P0 denylist(`axp:denylist:<jti>`) 병행(개별 jti 무효).
- refresh 회전·재사용 탐지는 P0 메커니즘 재사용(family). 단 모니터 refresh는 DB `refresh_tokens`에 audience=monitor로 적재하거나 Redis-only(키오스크는 항상 살아있어 회전 잦음 — Redis 권장, §14).

**시퀀스(발급·검증·교환):**
```
[관리자]                         [백엔드]                              [모니터 기기(키오스크)]
POST /monitors {name,dashboard}  → monitors(status=unpaired) 생성
POST /monitors/{uuid}/pair-code  → 1) 기존 활성 코드 만료처리
                                   2) code = CSPRNG 6자리(secrets.randbelow(1e6) → zfill)
                                   3) pairing_codes(code_hash=sha256(code+pepper),
                                      expires_at=now+60s, attempts=0) 저장
                                   4) monitors.status='pending'
                                 ← {code, expires_in:60}  (평문은 응답 1회만, 저장X)
   화면/안내로 코드 전달 ----------------------------------------------→ 키오스크에 코드 입력
                                                                        POST /pairing/claim {code}
   [백엔드 /pairing/claim]
     - 전역 rate limit(IP+엔드포인트: 예 분당 10회) 초과 시 429
     - row = pairing_codes WHERE code_hash=sha256(code+pepper)
              AND consumed_at IS NULL AND expires_at>now
              (없으면 → 동시에 monitor_id 알 수 없으니 일반 실패; attempts는 코드 행 있을 때만 증가)
     - if not row: 400 invalid_or_expired
     - if row.attempts >= max_attempts: 400 (코드 무효화)
     - 원자적 소비: UPDATE pairing_codes SET consumed_at=now
                    WHERE id=row.id AND consumed_at IS NULL  (영향행 0 → 이미 사용됨, 거부)
     - monitor = row.monitor; monitor.status='paired'; paired_at; last_ip; ua
     - issue monitor access+refresh (scope=dashboards:[dashboard_uuid])
   ← {monitor, access_token, refresh_token, expires_in}
   키오스크: 토큰 저장(localStorage) → GET /monitor/me → 대시보드 렌더 → 라이브 시작
   (이후) access 만료 → POST /monitor/refresh {refresh_token} → 회전
   (실패: mv 불일치/해지 401) → 키오스크 재페어링 화면(코드 입력)
```

**보안 요점:**
- 코드 6자리 = 10^6. **60초 + 행당 시도 5회 + 전역 rate limit**으로 무차별 대입 차단. 코드만으로 전역 조회하므로(monitor 미지정 claim) 전역 IP rate limit이 핵심.
- 코드 평문 미저장(해시+pepper). 응답 1회만 노출. 재사용 불가(consumed_at 원자적).
- 페어링 화면은 **공개**지만 코드 없이는 무의미. claim 성공 audit(`monitor_paired`), 실패 누적 audit(`pairing_failed`).
- 모니터 토큰 탈취 대비: 짧은 access + token_version 즉시 무효 + scope 최소(read·특정 대시보드). 키오스크는 신뢰 네트워크 가정이나 토큰 유출 시 해지로 차단.

### 7.2 키오스크 표시
- `GET /monitor/me` → 대시보드 layout + 카메라(uuid/name/stream go2rtc_name) **뷰어 정보만**(자격증명·host·관리 메타 제외).
- 라이브: P1 WebRTC/MSE 시그널링을 monitor access로 호출(scope 검증). 풀스크린 그리드, 자동 재연결, (옵션) rotation으로 다중 대시보드 순환.
- 레이아웃 변경 감지: `heartbeat` 응답 `dashboard_version`(또는 WS `monitor.<id>` push) → 변경 시 키오스크가 `/monitor/me` 재요청해 무중단 갱신. 해지/대시보드 변경 시 next refresh 401 → 재페어링.

### 7.3 알림: 웹푸시(VAPID) 흐름

**서버 키**: VAPID 키쌍(`VAPID_PUBLIC_KEY`/`VAPID_PRIVATE_KEY` env, P256). 라이브러리 `pywebpush`.

**구독(브라우저/PWA):**
```
프론트: navigator.serviceWorker.register('/sw.js')
        → reg.pushManager.subscribe({userVisibleOnly:true,
              applicationServerKey: urlBase64ToUint8Array(VAPID_PUBLIC_KEY)})  // GET /push/vapid-public-key
        → POST /push/subscriptions {endpoint, keys:{p256dh, auth}}
서버: push_subscriptions upsert(endpoint_hash UNIQUE, user_id=현재 사용자)
```

**발송(`webpush` 서비스 / `notification_dispatch` 태스크):**
```
for sub in active_subscriptions(user):
    try:
        pywebpush.webpush(
            subscription_info={'endpoint': sub.endpoint,
                               'keys': {'p256dh': sub.p256dh, 'auth': sub.auth}},
            data=json.dumps({'title','body','deeplink','tag','snapshot_url','priority'}),
            vapid_private_key=VAPID_PRIVATE_KEY,
            vapid_claims={'sub':'mailto:admin@<domain>'},
            ttl=ttl_for(priority))
        sub.last_success_at = now
    except WebPushException as e:
        if e.response.status_code in (404,410):   # Gone → 구독 폐기
            sub.enabled = 0
        else: sentry_sdk.capture_exception(e)
```
- 페이로드는 짧게(스냅샷은 서명 URL). `tag`로 통합(같은 카메라 연속 알림 교체). service worker `push` 이벤트 → `showNotification`, `notificationclick` → 딥링크(`/events/{id}`)로 focus/open.
- iOS PWA: 16.4+ 홈화면 추가 시 웹푸시 지원(설치 안내 UX 필요).

### 7.4 알림 라우팅·정책 (`notification_router`)

```
def route(notif_src):     # 이벤트(P3) 또는 규칙 발화에서 호출
    targets = subscriptions_matching(notif_src)   # channel·event_type·camera(권한교집합)·class·priority
    for sub in targets:
        if sub.muted or (sub.muted_until and now<sub.muted_until): continue
        if sub.min_priority rank > notif_src.priority rank: continue
        if in_quiet_hours(sub.quiet_hours, now_kst) and not (critical and allow_critical): 
            if sub.batch_window_s==0: continue   # 조용시간 즉시 채널은 보류/요약로
        if sub.batch_window_s>0:
            batch_buffer.add(sub, notif_src)      # Redis ZSET, flush 태스크가 창 만료 시 1건으로
        else:
            notification_dispatch.delay(sub.id, notif_src.id)   # 즉시
    # 인앱은 항상 notifications row + WS push (mute는 배지/소리만 억제 옵션)
    Notification.create(user, notif_src); ws_hub.publish(f'notifications', dto, scope=user.id)
```
- **우선순위**: low/normal/high/critical. critical(예 intrusion+person)은 조용시간/통합 무시 옵션(`allow_critical`).
- **통합(batch)**: `batch_window_s` 동안 같은 채널·사용자 알림을 모아 "N건의 이벤트" 1건으로(Redis ZSET 버퍼 + flush). 폭주·푸시 스팸 방지.
- **조용시간**: KST 범위. 해당 시간엔 push/email 보류(또는 요약으로 익일), 인앱은 적재만.
- **채널 발송**은 `notification_dispatch`(push/email)·`webhook_delivery`(webhook)로 위임. 결과 `notifications.channels_sent` 기록.

### 7.5 웹훅 보안 (SSRF·서명) — 액션·구독 공통
- URL 검증: 스킴 화이트리스트(https 권장), 호스트 resolve 후 **사설/링크로컬/루프백/클라우드 메타데이터(169.254.169.254)** 차단(허용목록 운영 옵션), 포트 제한, 리다이렉트 follow 비활성, 타임아웃·바디 크기 상한.
- 서명: HMAC-SHA256(secret, `ts.body`), 헤더 `X-Axp-Signature`/`X-Axp-Timestamp`. 외부 구독 등록 시 secret 자동 생성(응답 1회 노출) 또는 사용자 제공.
- 외부 구독(`/ext/subscriptions`)은 발급 토큰(api_token) 소유로 관리·해지. 토큰 해지 시 해당 구독 비활성.

### 7.6 외부 API & Home Assistant 연동
- **인증**: 불투명 토큰(`api_tokens`, 4.10) + `@api_token_required(scope)`. scope·camera_ids 교집합으로 응답 제한. rate limit per token.
- **HA 연동 패턴**:
  - **상태 폴링**: HA RESTful sensor가 `GET /ext/state`(또는 `/ext/cameras`) 주기 폴링 → 카메라 online/recording·스토리지·시스템 상태.
  - **이벤트 push**: `/ext/subscriptions`로 HA webhook(자동화 트리거 URL) 등록 → 이벤트 발생 시 서명 POST. 또는 `/ext/stream`(SSE) 구독.
  - **카메라 스트림**: HA generic_camera/go2rtc 통합이 RTSP/WebRTC를 직접(P1 go2rtc) 사용. P5는 토큰·상태·이벤트만 제공.
  - **액션 역방향**(HA→AXP, 예 HA가 AXP 스피커 울리기): `POST /rules/{uuid}/trigger`를 api_token으로 허용(scope `rules:update` 추가 시) — 기본 off, 명시 활성.
- **SSE**(`/ext/stream`): `text/event-stream`, 이벤트마다 `data: {json}`, 주기 `: heartbeat`. 필터·camera 교집합. uWSGI/gevent에서 long-lived 응답(또는 Redis pub/sub 브리지).

---

## 8. 프론트엔드 (TS) — DESIGN.md 적용

> React 18 + Vite 7 + TS + Tailwind + Radix/shadcn + TanStack Query/Table + dnd-kit. ams 패턴(페이지별 디렉터리, `@`=`src/`, Axios+JWT 인터셉터, i18n ko/en). 디자인 **Tesla 미니멀**: 흰 캔버스 UI·다크 영상 캔버스, 단일 액센트 **Electric Blue `#3E6AE1`**(주 CTA·활성/매칭 상태), 4px 라운드, 0.33s 트랜지션, 그림자·테두리·그라데이션 지양(구분은 spacing/border 최소), 텍스트 Carbon `#171A20`/Graphite `#393C41`/Pewter `#5C5E62`. **키오스크는 영상이 100% 주인공**(크롬 제로).

페이지/컴포넌트(`frontend/src/pages/rules/`, `.../monitors/`, `.../settings/notifications/`, `.../monitor/`(키오스크), 공용 `components/`):

### 8.1 `RuleBuilder` (규칙 빌더)
- 3단 흐름(좌→우 또는 단계 카드): **트리거 → 조건 → 액션**. Tesla식으로 한 화면 한 메시지: 단계별 큰 여백, 흰 카드(border만).
- **트리거 선택**: 4개 타입 카드(event/object/schedule/manual). event→이벤트 타입 멀티칩(motion/intrusion/line/tamper…), object→클래스 칩(person/car…)+confidence 슬라이더+zone(선택), schedule→cron 빌더(요일·시각 피커, KST 표기)+미리보기("다음 실행: …"), manual→설명만.
- **조건**: 카메라 멀티선택(권한 내), 시간대(요일×시각 범위, 다중), min_score 슬라이더, 조용시간 준수 토글, all_of/any_of 절 추가(필드·연산자·값 드롭다운 — 자유입력 금지, 화이트리스트).
- **액션**: 액션 목록(드래그 정렬, dnd-kit). 각 액션 = 타입(speaker/io/webhook/push/email) + 대상(`action_targets`/`webhooks` 드롭다운 + "새로 추가" 링크) + 파라미터(speaker: 클립/TTS, io: 출력·on/off/pulse·ms, webhook: 엔드포인트, push/email: 수신자) + delay_ms + continue_on_error. "테스트 발사" 버튼(`/rules/{uuid}/test`, dry-run 또는 1회 실발사).
- 칩/토글 선택은 배경 톤 전환(선택=연한 blue 배경+Electric Blue 텍스트). 저장 CTA만 `#3E6AE1`. URL/상태 동기화.

### 8.2 `RuleList` & `RuleExecutionLog`
- 규칙 목록 테이블(TanStack Table): 이름·트리거타입·활성토글(스위치)·우선순위·최근 발화·실행 수. 행 클릭 → RuleBuilder(편집).
- 실행 로그: 규칙별/전체 `rule_executions` — 시각(KST)·트리거·카메라·매칭여부·상태(success=Carbon 점, partial/failed=절제된 강조, skipped=Pewter)·액션별 결과 확장(JSON pretty). 필터(상태/기간/카메라).

### 8.3 `ActionTargetManager` (스피커/IO/이메일/웹훅)
- 대상 목록(타입 탭: 스피커·IO·웹훅·이메일). 카드/행에 상태 점(online/offline) + "테스트" 버튼.
- 추가/편집 모달: 타입별 폼(스피커=protocol·host·자격증명·클립 업로드/목록·SIP 설정; IO=protocol·host·출력 매핑·기본 pulse; 웹훅=URL·secret·타임아웃·재시도·TLS검증; 이메일=SMTP). 자격증명·secret은 입력만(응답 마스킹, "변경 시에만 재입력").
- 테스트: 스피커=클립/TTS 즉시 방송, IO=출력 on/off/pulse, 웹훅=샘플 POST(응답 상태·서명 표시).

### 8.4 `MonitorPairing` & `MonitorList`
- **MonitorList**(관리자): 모니터 카드 그리드 — 이름·상태(unpaired/pending/paired/revoked 색 절제)·대시보드·last_seen·기기. 액션: 페어링 코드 발급, 대시보드 재지정, 해지, 삭제.
- **MonitorPairing**(코드 발급 모달): "페어링 코드 발급" → **6자리 숫자 크게 표시**(모노스페이스, Carbon, 큰 사이즈) + 60초 카운트다운 원형/바(Electric Blue) + "모니터 기기에서 입력하세요" 안내 + 만료 시 "재발급" CTA. 코드는 1회 표시(새로고침 시 재발급 필요).
- 대시보드 재지정 시 "기존 모니터 토큰이 무효화됩니다" 경고(token_version++).

### 8.5 `KioskView` (모니터 기기 — 페어링·풀스크린)
- 경로 `/monitor`(앱 셸 없음, 별도 최소 레이아웃). 토큰 없으면 **PairingScreen**: 다크 캔버스 중앙, 큰 6자리 숫자 입력(또는 OTP 스타일 6칸), "AeroXProtect 모니터" 워드마크, 입력 시 `/pairing/claim`. 실패는 인라인("코드가 올바르지 않거나 만료되었습니다").
- 페어링 성공 → **KioskGrid**: 100vw×100vh, 대시보드 layout대로 라이브 그리드(P1 VideoPlayer 재사용, sub 스트림), 크롬 제로(시계/마우스 옵션은 `settings`). 자동 재연결, refresh 자동 갱신, 401(해지/변경) 시 PairingScreen 복귀.
- 사진/영상이 100% 주인공(DESIGN §1·§7) — UI 오버레이는 최소(연결끊김 시에만 절제된 안내).

### 8.6 `NotificationSettings` & `NotificationCenter`
- **NotificationSettings**: 채널별(웹푸시/이메일/웹훅/인앱) 카드. 웹푸시=현재 브라우저 구독 토글(권한 요청→`pushManager.subscribe`→POST), "테스트 푸시". 채널마다 이벤트타입·카메라·객체클래스 필터, 최소 우선순위, 통합 창(슬라이더), 조용시간(시각 범위, KST), 음소거/스누즈.
- **NotificationCenter**(상단바 종 아이콘 드롭다운/시트): 미읽음 배지, 알림 리스트(스냅샷 썸네일 전면·12px 라운드, 타입/시각 KST, 딥링크), 읽음/모두읽음. WS `notifications` 실시간 추가(0.33s 페이드, 점멸 금지).
- 디자인: 흰 패널, 액센트는 미읽음 점·CTA만. 시맨틱 색 최소.

### 8.7 `ApiTokenManager` & 외부 연동 안내
- API 토큰 목록(이름·prefix·scope·마지막 사용·만료·해지). 발급 모달(이름·scope 체크·카메라 스코프·만료) → 평문 토큰 **1회 표시**(복사 버튼, "다시 볼 수 없습니다"). 해지 버튼.
- HA 연동 가이드 패널(엔드포인트·예시 — 폴링/웹훅/SSE), 외부 웹훅 구독 목록.

### 8.8 PWA / Service Worker / i18n
- PWA: P0 manifest 확장 + **service worker push 핸들러**(`push`→showNotification, `notificationclick`→딥링크 focus). 설치 안내(특히 iOS).
- i18n ko/en: 트리거/조건/액션/우선순위/상태 라벨, 시각 KST 표시(저장 UTC). 터치 타깃 ≥44px(키오스크·모바일).

---

## 9. 작업 분해 (순서 있는 체크리스트)

1. **선행 계약 확정(블로킹)**: P3 `event_outbox` payload·consume 계약, `signals.event_created` 시그니처; P4 object 트리거 발행 경로(권장 outbox 단일); P1 WS `monitor.<id>` 채널·라이브 scope 검증; P0 `TokenService` aud/scope 분기. (없으면 §14·AskUserQuestion.)
2. **모델/마이그레이션**: `rules/rule_executions/action_targets/webhook_endpoints/monitors/pairing_codes/notification_subscriptions/push_subscriptions/notifications/api_tokens` + 권한 카탈로그 append. SQL 산출(4.11).
3. **토큰 인프라 확장**: `TokenService`에 audience=`monitor` 발급/검증(scope·mv), `ApiTokenService`(불투명 토큰 발급/해시/검증/rate limit), `@api_token_required` 데코레이터.
4. **페어링 코어(보안)**: `pairing_code` 서비스(CSPRNG·해시·검증·소비 원자성·rate limit) + `monitor_token` + `/monitors/*`·`/pairing/claim`·`/monitor/*` view/controller. unit/integration 우선(만료·재시도·일회성·교환).
5. **규칙 엔진 코어**: `rule_evaluator`(조건 매칭·결합·쿨다운/멱등, 순수성), `rule_dispatcher`, `trigger_router`(TriggerEvent 정규화). unit 먼저(매칭표·쿨다운·디바운스).
6. **트리거 소스 연결**: `outbox_consumer`(P3 outbox 폴링+consume, signals 보조), `schedule_trigger`(beat cron), `manual`(API), P4 object 어댑터.
7. **액션 드라이버**: `webhook.py`(서명·재시도·SSRF) → `email.py`(ams 이식) → `push.py`(pywebpush/VAPID) → `speaker.py`(vendor_http→onvif_backchannel→sip) → `io.py`(onvif_relay→vendor_http). 각 mock/시뮬레이터 테스트. `action_runner`·`rule_action` 태스크.
8. **알림 라우팅**: `notification_router`(구독 매칭·priority·mute·quiet·batch), `notification_dispatch`/`webhook_delivery` 태스크, `push_subscriptions`·`notification_subscriptions` view/controller, 인앱 WS `notifications` 채널.
9. **외부 API**: `/ext/*`(events/state/subscriptions/stream SSE), `api_tokens` view/controller, HA 가이드.
10. **Celery/큐 구성**: `actions`·`notifications`·`webhooks` 큐 분리(상호 영향 차단), beat(`schedule_trigger */1m`, `target_healthcheck */5m`, `pairing_code_cleanup */5m`, `p5_retention 03:30`), gevent(웹훅/푸시 I/O).
11. **프론트**: RuleBuilder→RuleList/ExecutionLog→ActionTargetManager→MonitorList/MonitorPairing→KioskView(PairingScreen+KioskGrid)→NotificationSettings/Center→ApiTokenManager. PWA sw push. i18n.
12. **보존/정리**: rule_executions/notifications retention, pairing/푸시 만료 정리, 웹훅 서킷브레이커.
13. **테스트 전수**: unit/integration/e2e(§12), 회귀(P3 이벤트·P4 detection·P1 라이브/대시보드·P0 인증 영향).
14. **문서 갱신**: §14 해소분 PLAN 반영, §10 Impact 확정.

---

## 10. 다른 기능/Phase에 미치는 영향 (Cross-feature Impact) ★

| 대상 | 영향 | 조치 |
|---|---|---|
| **P0 인증/`TokenService`** | audience=`monitor`(scope·mv) + audience=`api`(불투명 토큰) 발급/검증 추가. denylist·family 재사용 | P0 검증기 aud 분기 자리 사용. monitor는 RBAC 대신 scope 인가. **변경 시 전 인증 회귀 테스트** |
| **P0 권한맵(RBAC)** | `rules`·`targets`(웹훅 포함)·`monitors`·`notifications`·`api_tokens` 권한키 신설(§12.2 콜론 표기) | 권한 카탈로그 시드 append, admin 전권, UI 권한편집 반영 |
| **P0 WS 게이트웨이** | `notifications`(사용자 scope), `monitor.<id>`(레이아웃 갱신) 채널 추가 | P1 허브에 채널·scope 필터 등록. 모니터 WS 인증(monitor 토큰) |
| **P0 Celery/큐** | `actions`·`notifications`·`webhooks` 전용 큐 + beat 다수 추가, gevent I/O | docker-compose worker에 큐/concurrency 추가(또는 별도 워커). 녹화/구독 큐와 격리 |
| **P1 dashboards** | 모니터가 `dashboard_id` 바인딩·뷰어 표시. 대시보드 삭제 시 모니터 처리 | 대시보드 삭제 시 연결 모니터 status='revoked'(또는 차단) + token_version++. dashboard_acl과 별개(모니터는 scope 토큰) |
| **P1 라이브(go2rtc/WebRTC)** | 키오스크가 라이브 시그널링 재사용 — **monitor scope 검증** 필요 | 라이브 시그널링 엔드포인트가 web JWT 외 monitor 토큰 허용 + scope(대시보드 카메라) 검증 추가 |
| **P1 cameras/capabilities** | 스피커(audio backchannel)·IO(relay outputs) 액션이 카메라 capability 참조 | capabilities의 audio.output/relay 여부로 onvif backchannel/relay 가용성 표시 |
| **P3 events/event_outbox** | P5가 outbox 컨슈머(`pending→consumed`). signals 구독 | **outbox 1차 진실원**. P3와 payload·consume 계약 합의(읽기·status 갱신만, 스키마 변경 없음) |
| **P3 event_policies.notify** | 알림 발행 플래그 — P5 notification_router가 소비 | notify=true 이벤트를 구독 매칭. 중복(규칙+정책) 방지(멱등) |
| **P4 detections/object** | object 트리거 소비. detection→trigger 발행 경로 | **권장: P4가 object를 events+outbox로**(단일 경로). 아니면 P5에 detection 컨슈머 추가(§14 Q1) |
| **P6 SMS/고급/다중NVR** | 채널·액션·구독을 P6이 확장(SMS 드라이버, MQTT, fan-out) | 드라이버 인터페이스·`action_targets` type·구독 모델을 확장 가능하게 유지 |
| **보존정책** | `rule_executions`·`notifications` 고빈도 증가 | retention 태스크·인덱스, action_results/raw 조기 정리 |
| **보안 횡단** | 액션 대상 자격증명·웹훅 secret·VAPID·api 토큰 = 민감 | Fernet 암호화(P1 crypto), 응답 마스킹, SSRF 가드, 토큰 해시 저장, pepper |

**회귀 주의**: 모니터 토큰이 P1 라이브 엔드포인트를 재사용하므로 **라이브 인가 로직 변경 = P1·P5 동시 회귀**. outbox 컨슈머가 P3 이벤트 흐름을 건드리면 P3 회귀. 변경 결정은 PLAN §0(3) 사용자 확인.

---

## 11. 리스크 & 완화

| 리스크 | 영향 | 완화 |
|---|---|---|
| 페어링 코드 무차별 대입(6자리) | 모니터 무단 페어링 | 60초 만료 + 행당 5회 + **전역 IP/엔드포인트 rate limit** + 해시+pepper 저장 + 소비 원자성 + claim 실패 audit |
| 모니터 토큰 탈취 | 비인가 라이브 시청 | 짧은 access·scope 최소(read·특정 대시보드)·token_version 즉시 해지·denylist. 신뢰망 가정 + 유출 시 해지 |
| 규칙 폭주(이벤트 다발) | 스피커/IO/웹훅/푸시 스팸·기기 손상 | cooldown·debounce·max_per_hour 토큰버킷·멱등(idempotency_key)·dedup_scope. IO pulse 상한 |
| 웹훅 SSRF/내부망 공격 | 내부 자원 노출 | URL 스킴·사설/메타데이터 IP 차단·리다이렉트 비허용·DNS rebinding 방지·타임아웃 |
| 웹훅/푸시 대상 장애 | 큐 적체·지연 | 지수 백오프·서킷브레이커(consecutive_failures)·전용 큐·타임아웃. 410 Gone 구독 폐기 |
| SIP/RTP 스피커 호환성·NAT | 방송 실패 | vendor_http 우선, SIP는 동시호출 제한·임시 UA·코덱(PCMU) 고정, 실기기 매트릭스 테스트 |
| ONVIF backchannel 동시 1세션 | 라이브 talk와 충돌 | 세마포어·짧은 방송, 라이브 인터컴(P6)과 조정 |
| 알림 누락/중복(at-least-once) | 사용자 신뢰 | outbox 1차 + 멱등 dedup, 인앱은 항상 적재, 채널 결과 기록 |
| VAPID/푸시 브라우저 편차(특히 iOS) | 도달 실패 | 표준 pywebpush, 구독 헬스(410 폐기), iOS PWA 설치 안내, 인앱 폴백 |
| 모니터/외부 토큰 권한 누수 | 비인가 정보 노출 | scope·camera_ids 교집합 강제, 뷰어전용 DTO(자격증명·host 제외), 외부 API 응답 최소화 |
| Celery long-lived SSE/구독 | 워커 점유 | SSE는 gevent/Redis pub-sub 브리지, 구독 워커 분리, 타임아웃·재연결 |
| 자격증명/secret 평문 노출 | 보안 사고 | Fernet 저장·복호화 메모리 한정·로그/응답 마스킹·키 회전(cred_key_id) |

---

## 12. 테스트 계획 (unit/integration/e2e)

**Unit**
- `rule_evaluator`: 트리거 타입별 세부 매칭(event_types/subtypes, object classes/confidence/zone), 조건(camera/time_ranges KST/min_score/quiet/all_of/any_of), 쿨다운·rate limit·디바운스(trailing-edge) 시각 로직, stop_on_match·priority 정렬, 멱등 키 생성.
- `pairing_code`: 코드 생성(자릿수·CSPRNG), 해시+pepper, 검증(만료/시도초과/소비됨/정상), 소비 원자성(동시 claim 중 1건만 성공), rate limit.
- `monitor_token`: 발급 클레임(aud=monitor·scope·mv), scope 인가(허용 대시보드/카메라만·read만), token_version 무효화, refresh 회전.
- `ApiTokenService`: 해시 검증·scope 체크·camera 교집합·rate limit·해지/만료.
- `webhook` 서명(HMAC ts.body), SSRF 가드(사설/메타데이터 차단), 재시도 분류(4xx vs 5xx).
- `notification_router`: 구독 매칭·priority·mute/스누즈·quiet hours(KST 경계)·batch 버퍼.
- 각 드라이버(speaker/io/email/push) 호출 인자·타임아웃·에러 처리(mock 트랜스포트).

**Integration (DB + Celery eager + mock 기기/HTTP)**
- 규칙 파이프라인 e2e(in-proc): mock outbox row → trigger_router → evaluate → dispatch → mock 드라이버 호출 → `rule_executions` 기록(success/partial/skip). 쿨다운·멱등으로 중복 억제 확인.
- 페어링 전체: `/monitors`→`/pair-code`→`/pairing/claim`(정상/만료/오답/재사용/rate limit)→monitor 토큰으로 `/monitor/me`(scope 강제: 타 대시보드 카메라 접근 403)→`/monitor/refresh`→해지 후 401.
- 알림: 이벤트 → 구독 매칭 → push(mock pywebpush)·email(mock SMTP)·webhook(로컬 수신 서버, 서명 검증)·인앱(WS). 통합/조용시간 동작.
- 외부 API: api_token 발급→`/ext/events`(scope·camera 교집합)→`/ext/subscriptions` 등록→이벤트 시 서명 webhook 수신→토큰 해지 후 401.
- 액션 드라이버: webhook 재시도/서킷브레이커, IO pulse(on→off 타이밍), speaker vendor_http(mock CGI).

**e2e (프론트+백엔드, Playwright)**
- RuleBuilder로 규칙 생성(object person→webhook) → 테스트 발사 → 로컬 수신 확인 → ExecutionLog 표시.
- MonitorPairing 코드 발급 → KioskView(별 탭/컨텍스트)에서 코드 입력 → 대시보드 라이브 표시 → 관리자 해지 → 키오스크 재페어링 화면 복귀.
- NotificationSettings 웹푸시 구독(권한 mock) → 테스트 푸시 도달 → 클릭 딥링크.

**회귀**: P0 인증(web 토큰·refresh·denylist) — monitor/api 추가 후 web 흐름 무영향. P1 라이브 — monitor scope 추가 후 web 사용자 라이브 정상. P3 이벤트 흐름 — outbox 소비가 P3 동작 무영향. P4 detection — object 트리거 추가 무영향.

---

## 13. 성능·보안 체크포인트

**성능**
- 규칙 평가: 활성 규칙 **캐시**(Redis/프로세스+버전, 변경 시 무효화), trigger_type 인덱스로 후보 축소, 조건은 메모리 평가(DB 무접근). 쿨다운/멱등/rate limit은 Redis(원자 연산).
- 액션·알림·웹훅은 **전용 큐 + gevent**(I/O 다중화), 녹화/구독 큐와 격리(상호 영향 차단). 긴 IO pulse·재시도는 countdown으로 워커 비점유.
- `rule_executions`·`notifications` 고빈도: 논리참조+인덱스(FK 없음), 짧은 트랜잭션, 보존 정리·인덱스 신중(`(rule_id,created_at)`/`(user_id,created_at)`).
- outbox 컨슈머: 배치 조회(LIMIT)+상태 갱신, 백프레셔(폭주 시 샘플링), N+1 회피(payload로 추가 join 불요).
- SSE/구독: Redis pub/sub 브리지 + gevent, 클라이언트 상한·하트비트.

**보안**
- 모든 내부 API `@login_required`+세부 권한, **카메라/대시보드 스코프 교집합**으로 비인가 노출 차단. 모니터·외부 토큰은 scope 인가(뷰어전용 DTO).
- 페어링: 코드 해시+pepper·일회성·만료·시도제한·전역 rate limit·audit. 평문 코드/토큰은 응답 1회만(저장 금지).
- 토큰: monitor `mv`·api `revoked_at` 즉시 무효, denylist 병행. 강한 비밀(JWT_SECRET/VAPID/api pepper) env.
- 자격증명·secret: Fernet 저장(P1 crypto·cred_key_id 회전), 복호화 메모리 한정, 로그/응답 마스킹(`has_secret` 플래그만).
- 웹훅 SSRF 가드(사설/메타데이터/리다이렉트/rebinding), 서명·타임스탬프(리플레이 방지), TLS 검증 기본 on.
- 외부 API: scope 최소, camera 교집합, rate limit per token, 응답에 host/자격증명/내부경로 미포함. SSE/구독 인증 강제.
- 입력 검증: 규칙 JSON 스키마(trigger/condition/actions 화이트리스트, op enum), cron 검증, 액션 파라미터 범위(pulse_ms 상한). eval/SSTI 금지.
- 감사: 규칙·대상·모니터·토큰 변경 created_by/updated_by + audit_logs(`rule_created`,`monitor_paired`,`monitor_revoked`,`pairing_failed`,`api_token_created/revoked`,`webhook_test` 등).
- 패키지 최신 stable(pywebpush/httpx/croniter/pjsua2 또는 SIP 대체), 알려진 취약점 점검(pip-audit/npm audit).

---

## 14. 미해결 질문 / 결정 필요 사항

- **Q1. object 트리거 발행 경로**: P4 detection을 (a) `events`+`event_outbox`로 흘려 P5가 단일 경로로 소비(권장) vs (b) detection 전용 큐/시그널을 P5가 별도 컨슈머로 소비. → P4 소유자와 합의(단일 경로 권장).
- **Q2. 모니터 refresh 저장**: monitor refresh를 DB `refresh_tokens`(audience=monitor) 적재 vs Redis-only(회전 잦음·키오스크 상주). 재사용 탐지 수준과 트레이드오프. (권장: Redis-only + token_version, 또는 경량 DB.)
- **Q3. 외부 API 토큰 형식**: 불투명 토큰(DB 해시 조회·해지 즉시·권장) vs JWT(aud=api·무상태·짧은 만료). 혼용 정책. (권장: 불투명 기본, 단기 JWT 옵션.)
- **Q4. 스피커 SIP 스택**: `pjsua2`(PJSIP, 기능 풍부·빌드 무거움) vs `aiortc`/순수 RTP(경량·기능 제한) vs vendor_http만으로 충분(SIP 후순위). 타깃 스피커 모델군 확인 필요.
- **Q5. TTS 엔진**: 스피커 TTS 미지원 시 서버 TTS(예 Piper/Coqui 로컬 vs 클라우드) 도입 여부·기본 비활성. (P5 기본: 사전 업로드 클립, TTS는 옵션.)
- **Q6. WS vs SSE 인프라**: 내부 알림은 P1 WS 게이트웨이 재사용, 외부 `/ext/stream`은 SSE — uWSGI/gevent long-lived 응답 방식(Redis pub/sub 브리지) 확정.
- **Q7. 모니터 라이브 인증**: P1 라이브 시그널링이 monitor 토큰을 받도록 확장하는 방식(쿼리 토큰 vs WS 헤더 vs 단명 티켓). 보안·구현 합의.
- **Q8. IO 산업 프로토콜 범위**: Modbus TCP/SNMP 등 산업용 IO를 P5에 포함할지 P6로 미룰지. (P5: ONVIF relay·벤더 HTTP, Modbus는 P6 자리.)
- **Q9. 알림 통합/조용시간 기본값**: 기본 batch_window_s, 기본 조용시간, critical 무시 정책의 디폴트.
- **Q10. HA 역방향 제어**: HA→AXP 액션 트리거(`rules:update` via api_token) 기본 허용 여부(보안). 기본 off 권장.

> 확정 시 본 문서 해당 절 + `../PLAN.md`(필요 시 §7 데이터 모델·§8 인증·§9 로드맵)에 반영(PLAN §0-4).

### 14.1 구현 시 채택한 결정 (2026-06-05, P5 구현)
- **Q1. object 트리거 발행 경로**: **단일 경로 채택** — P4가 이미 object를 P3 `events`+`event_outbox`로 흘림(`ingest_object`→`_process`→`EventOutbox.publish`, 정책 notify 기본 True). P5 `outbox_consumer`(beat 5s)가 pending 행을 소비 → `trigger_router.from_outbox`(object면 trigger_type='object', subtype=class) → rule 엔진 + 알림 + 외부 구독 → `mark_consumed`. detection 전용 큐 불필요.
- **Q2. 모니터 refresh 저장**: **JWT(aud=monitor) + Redis denylist + `monitors.token_version`(mv)** — DB `refresh_tokens` 미적재(키오스크 상주·회전 잦음). `rotate_monitor_refresh`가 옛 jti를 denylist하고 새 pair 발급(같은 family). 해지·대시보드 변경 = `token_version++`로 전 토큰 즉시 무효(`mv` 불일치 → 401).
- **Q3. 외부 API 토큰**: **불투명 토큰 기본**(`api_tokens`, sha256(token+pepper) 저장, 평문 1회 노출, `revoked_at` 즉시 무효). `@api_token_required(*scopes)`(Bearer or X-API-Key) + per-token Redis rate limit + camera 교집합. JWT(aud=api)는 미구현(필요 시 옵션).
- **Q4. 스피커 SIP**: **vendor_http 1순위**(requests + Digest), `onvif_backchannel`/`sip`은 구조화 스텁(하드웨어+무거운 deps → 후속). 드라이버 결과 dict 통일(status/latency/protocol).
- **Q5. TTS**: 기본 **사전 업로드 클립**(vendor TTS는 `config.tts_param` 패스스루). 서버 TTS 엔진(Piper 등)은 후속.
- **Q6. WS vs SSE**: 인앱 알림은 **`notifications` 테이블 + 폴링 알림센터**(전용 WS 허브 미구현 → 후속). 외부 `/ext/stream`은 **bounded SSE**(~10s, 클라이언트 재연결); Redis pub/sub 브리지 long-poll은 후속.
- **Q7. 모니터 라이브 인증**: `/monitor/me`가 대시보드+카메라(뷰어 DTO: 자격증명/host 제외) 제공, 키오스크 그리드는 바인딩된 카메라 표시. **monitor-scope WebRTC 시그널링 재사용은 후속**(§Q7) — 페어링→대시보드 바인딩→키오스크 표시의 코어 DoD는 충족.
- **Q8. IO 프로토콜**: **ONVIF relay(스텁) + 벤더 HTTP(Hikvision ISAPI/Hanwha SUNAPI/generic, pulse on→sleep→off)**. Modbus/SNMP는 P6.
- **Q9. 알림 기본값**: `batch_window_s` 기본 **0(즉시)**, 기본 조용시간 없음, critical은 `allow_critical` 시 조용시간 무시. 우선순위 critical(intrusion/tamper)>high(object/line)>normal.
- **Q10. HA 역방향 제어**: **기본 off** — api_token scope에 `rules:update` 경로 미개방(명시 활성 시에만).
- **보안 구현**: 페어링 코드 = CSPRNG 6자리, sha256(code+pepper) 저장(평문 미저장), 60초 TTL, 원자적 1회 소비(`UPDATE…WHERE consumed_at IS NULL`), per-IP claim rate limit(10/min). 웹훅 = HMAC-SHA256(`ts.body`, `X-Axp-Signature`) + SSRF 가드(스킴·사설/loopback/메타데이터 IP 차단, 비-production은 완화), 재시도 분류(5xx/network=retry, 4xx=permanent), 서킷브레이커(consecutive_failures≥10→disable). 자격증명·웹훅 secret = Fernet(P1 crypto), 응답 마스킹(`has_secret`/`has_credentials`). 규칙 엔진 = trigger_type 인덱스 후보 축소 + 메모리 조건평가 + Redis cooldown/idempotency(SET NX)/rate(INCR EX).
- **권한키**: P0 카탈로그에 이미 예약된 `rules`·`targets`·`monitors`·`notifications`·`api_tokens` 사용(admin 전권).
- **토큰 분리**: web(int sub)·node(aud=node)·monitor(aud=monitor, hex uuid sub)·api(opaque)가 검증기에서 완전 분리 — monitor/node 토큰은 web 검증 통과 불가(sub int 파싱 실패), web 토큰은 monitor 검증 통과 불가(aud 불일치).

### 14.2 검증 메모
실기기(스피커/IO/푸시 브라우저) 부재 → 드라이버는 **mock 트랜스포트**(requests/smtplib/pywebpush monkeypatch)로 계약 검증. 규칙 평가(트리거·조건·clause·time_ranges KST·cooldown·idempotency·rate)·페어링(발급/소비 원자성/만료/재사용)·monitor 토큰(scope·mv 무효화·회전)·ApiTokenService(scope·camera 교집합·해지)·웹훅(HMAC·SSRF·재시도 분류)·notification_router(매칭·mute·quiet·priority)·cron 매처는 **unit/integration**(SQLite+fakeredis). 전 경로는 **live mock 수신서버 e2e**(`tests/_p5_automation_check.py`, **19 checks green**): 웹훅 HMAC 전송 → 카메라+규칙 생성 → **이벤트 시뮬레이트 → P3 outbox → `outbox_consumer` beat → 규칙 발화 → 서명 웹훅 수신 + rule_execution success** → 수동 발사 → **모니터 페어링(코드→claim→/monitor/me scope→재사용 거부→해지 401)** → **외부 API 토큰(scope→/ext/events·/ext/state→해지 401)**. host.docker.internal 수신서버(dev SSRF 완화). **backend pytest 208 passed**, 프론트 `tsc --noEmit`/`vite build` 무에러.
