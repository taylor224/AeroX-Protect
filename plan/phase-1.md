# Phase 1 — 카메라 온보딩 + 라이브뷰

> 본 문서는 `PLAN.md`(마스터)와 `DESIGN.md`(Tesla 미니멀)를 전제로 한다. 작업 전 두 문서를 읽고, 변경 시 본 문서의 *10. Cross-feature Impact* 절을 갱신한다.
> 전제: P0(Scaffold)가 완료되어 인증(JWT access+refresh, Redis jti denylist)·RBAC(권한맵 JSON)·핵심 모델 스켈레톤(`users`/`roles`/`cameras`/`streams`/`dashboards` 등 빈 골격)·디자인 셸(다크 캔버스 레이아웃, 사이드바, ResponseBuilder, Axios 인터셉터)이 동작한다. P1은 이 스켈레톤을 **확장**한다.

---

## 1. 목표 & 성공 기준(DoD)

### 1.1 목표
ONVIF/Hikvision ISAPI/Hanwha SUNAPI 카메라를 **검색→자동 프로빙→등록**하고, go2rtc 재스트리밍을 통해 **유연한 분할 그리드 라이브뷰**(WebRTC 우선, MSE 폴백)와 **PTZ 제어**, **스냅샷/썸네일**을 제공한다. P1 종료 시점에 "카메라를 추가하면 곧바로 화면이 뜨는" 보이는 MVP가 단독 시연 가능해야 한다.

### 1.2 성공 기준 (Definition of Done)
1. **디스커버리**: WS-Discovery 멀티캐스트로 같은 대역의 ONVIF 카메라가 목록(제조사·모델·IP·ONVIF 서비스 URL)으로 표시된다. 타 대역은 수동 IP(또는 IP 범위) 추가로 프로빙된다.
2. **자동 프로빙**: IP/ID/PW 입력 → 벤더 자동감지(Hikvision/Hanwha/ONVIF-generic) → 모델·펌웨어·코덱·해상도·fps·스트림 채널 수·PTZ 유무·이벤트 지원·오디오·스냅샷 URL 등이 **등록 확정 전 화면에 표시**된다.
3. **CRUD + 암호화**: 카메라 등록/수정/삭제가 동작하고, 자격증명은 `cryptography(Fernet)`로 암호화 저장되며 API 응답·로그에 평문이 절대 노출되지 않는다. 온/오프라인·스트림 상태가 주기적으로 갱신된다(헬스 체크).
4. **go2rtc 연동**: 카메라 등록 시 go2rtc 설정(스트림 항목)이 동적 생성/갱신되고, `axp-go2rtc` 컨테이너가 카메라당 소스 1연결로 재스트리밍을 시작한다.
5. **라이브 그리드**: 단일/4/9/16/32/커스텀 레이아웃에서 다수 카메라가 동시에 표시된다(그리드=서브 스트림 WebRTC, WebRTC 실패 시 MSE 폴백, 전체화면=메인 스트림). dnd-kit 드래그로 셀 재배치, **셀 스패닝**(rowspan/colspan), **비율 모드**(fit/stretch/crop)가 동작한다.
6. **대시보드 저장/공유**: 레이아웃(JSON)이 저장/로드되고, **사용자별 대시보드 ACL**(view/edit)로 접근이 제한된다.
7. **PTZ**: PTZ 카메라에서 pan/tilt/zoom(연속/스텝)·속도·프리셋(목록/이동/저장/삭제)이 ONVIF/ISAPI/SUNAPI 공통 인터페이스로 동작하며, **카메라별 PTZ 권한**이 권한맵으로 강제된다.
8. **스냅샷**: 라이브/관리 화면에서 카메라 현재 프레임 JPEG 스냅샷과 타일 썸네일이 제공된다.
9. **테스트**: 드라이버(파싱·시그니처)·capability_probe·go2rtc 설정 생성·암호화·권한 가드의 unit, 카메라 CRUD/라이브 시그널링 integration, 카메라 추가→라이브 표시→PTZ의 e2e가 통과한다.

### 1.3 비-목표 (DoD에 포함하지 않음)
녹화/세그먼트/스토리지 풀(P2), 이벤트 정규화·모션 오버레이(P3), AI detection(P4), 양방향 오디오·디워핑·마스킹·시퀀스 자동전환(P6). 단, **P2~P6가 끼어들 자리**(스키마·인터페이스·이벤트 훅)는 P1에서 미리 비워둔다(→ 10절).

---

## 2. 범위 (In-scope / Out-of-scope)

### In-scope
- ONVIF WS-Discovery 멀티캐스트 검색 + 수동 IP/IP범위 추가 + 디스커버리 결과 UI.
- 벤더 자동감지 + capability 프로빙(ONVIF GetDeviceInformation/GetProfiles/GetCapabilities/GetServices·ISAPI deviceInfo/Streaming/channels/PTZ·SUNAPI attributes/eventstatus).
- 카메라 CRUD, 자격증명 암호화 저장, 헬스/상태 모니터링(Celery 주기 태스크 + go2rtc 상태 조회).
- streams 정의(main/sub, codec/res/fps/rtsp_url/go2rtc_name).
- go2rtc 드라이버: 설정 동적 생성/갱신(REST API + config 파일 백업 경로), 재스트리밍 시작/중지, WebRTC/MSE 시그널링 경로(백엔드 프록시).
- 라이브 분할뷰: LiveGrid, CameraTile, LayoutEditor, 비율 모드, 셀 스패닝, dnd-kit 배치.
- 대시보드(레이아웃 JSON) CRUD + dashboard_acl.
- PTZ 통합 드라이버 + PtzControls + 카메라별 PTZ 권한.
- 스냅샷/썸네일 API + 갱신 태스크.

### Out-of-scope (다른 Phase)
- 녹화·재생·다운로드·보존정책·다중HDD(P2). 이벤트·스케줄·모션(P3). AI(P4). 규칙엔진·모니터 페어링·푸시(P5). 양방향오디오·디워핑·마스킹·LPR·얼굴·다중NVR(P6).
- 배치(대량) 카메라 추가는 P2(설계만 P1에서 고려).

---

## 3. 선행 의존성

| 의존 | 출처 | P1에서의 사용 |
|---|---|---|
| JWT 인증(access/refresh, Redis jti denylist), `@login_required` | P0 | 모든 API 가드 |
| RBAC 권한맵(JSON) + `@permission_required(perm, action)` 데코레이터 | P0 | 카메라/대시보드/PTZ 권한 |
| `users`/`roles` 모델, `cameras`/`streams`/`dashboards` 스켈레톤 | P0 | P1에서 컬럼 확장(마이그레이션) |
| `ResponseBuilder`, `exception.py`(RowNotFound/InvalidParameter/Conflict) | P0(ams 패턴) | 표준 응답/예외 |
| Snowflake ID 생성기(`server.util.snowflake`, `generate_snowflake_id`), KST/UTC 유틸 | P0 | PK 생성, 타임스탬프 |
| Docker Compose 서비스 `axp-backend/axp-redis/axp-mysql/axp-go2rtc/axp-frontend` | P0 | go2rtc 사이드카, 백엔드 |
| 암호화 키(`CREDENTIAL_ENC_KEY`, Fernet) 환경변수 + `server.util.crypto` | P0(없으면 P1에서 생성) | 자격증명 암호화 |
| 프론트 셸(다크 레이아웃, 사이드바, Axios 인터셉터, TanStack Query Provider, i18n) | P0 | 페이지 마운트 |
| `cryptography`, `onvif-zeep`(WSDiscovery 포함 or `wsdiscovery`), `requests`, `httpx`(비동기 프로빙 선택) | P1 추가 | 드라이버 |

> **결정 필요(→14절)**: P0가 `cameras`/`streams`/`dashboards`를 어디까지 만들었는지에 따라 4절 마이그레이션은 "CREATE" 또는 "ALTER"로 분기. 본 문서는 **풀 정의(CREATE)** 기준으로 작성하고, 이미 존재하는 컬럼은 ALTER로 치환한다.

---

## 4. 데이터 모델 (테이블·컬럼·타입·인덱스 / 마이그레이션 SQL 스케치)

설계 원칙(PLAN 11절): soft delete(`deleted_at`), 감사 컬럼(`created_by_id`/`last_updated_by_id`), Snowflake `BIGINT` PK, **FK 최소화**(성능), 저장 타임스탬프는 UTC(`DATETIME(3)`, 밀리초), 표시만 KST. 전용 DB(`axp`)이므로 테이블 prefix 없음.

### 4.1 `cameras`
| 컬럼 | 타입 | 비고 |
|---|---|---|
| `id` | `BIGINT` PK | Snowflake |
| `uuid` | `CHAR(32)` | 외부 노출 식별자, `UNIQUE` |
| `name` | `VARCHAR(200)` NOT NULL | 표시명 |
| `vendor` | `VARCHAR(32)` NOT NULL | `hikvision`/`hanwha`/`onvif`/`unknown` |
| `model` | `VARCHAR(128)` NULL | 프로빙 결과 |
| `firmware` | `VARCHAR(128)` NULL | |
| `serial` | `VARCHAR(128)` NULL | 중복 등록 감지에 활용 |
| `driver` | `VARCHAR(32)` NOT NULL | 실제 사용할 드라이버(`isapi`/`sunapi`/`onvif`) |
| `protocol_fallback` | `VARCHAR(32)` NULL | 벤더 실패 시 폴백(`onvif`) |
| `host` | `VARCHAR(255)` NOT NULL | IP 또는 호스트 |
| `onvif_port` | `INT` NULL | 기본 80 |
| `http_port` | `INT` NULL | ISAPI/SUNAPI HTTP(S) |
| `rtsp_port` | `INT` NULL | 기본 554 |
| `use_https` | `TINYINT(1)` NOT NULL DEFAULT 0 | |
| `username_enc` | `VARBINARY(512)` NULL | Fernet 암호문 |
| `password_enc` | `VARBINARY(512)` NULL | Fernet 암호문 |
| `cred_key_id` | `VARCHAR(32)` NULL | 키 회전 대비(어떤 키로 암호화했는지) |
| `capabilities` | `JSON` NULL | 프로빙 원본 정규화(아래 4.6) |
| `ptz_supported` | `TINYINT(1)` NOT NULL DEFAULT 0 | 빠른 필터/권한 판단용(capabilities 미러) |
| `audio_supported` | `TINYINT(1)` NOT NULL DEFAULT 0 | |
| `two_way_audio` | `TINYINT(1)` NOT NULL DEFAULT 0 | (P6 사용, P1은 표시만) |
| `channel` | `INT` NOT NULL DEFAULT 1 | 멀티채널 인코더/NVR 채널 번호 |
| `timezone` | `VARCHAR(64)` NULL | 카메라 OSD 시간 동기화(후속) |
| `status` | `VARCHAR(16)` NOT NULL DEFAULT 'unknown' | `online`/`offline`/`unauthorized`/`error`/`unknown` |
| `last_seen_at` | `DATETIME(3)` NULL | 마지막 성공 헬스 |
| `last_error` | `VARCHAR(512)` NULL | 최근 오류 요약 |
| `is_enabled` | `TINYINT(1)` NOT NULL DEFAULT 1 | go2rtc 활성/비활성 |
| `created_by_id` | `BIGINT` NULL | |
| `last_updated_by_id` | `BIGINT` NULL | |
| `created_at` | `DATETIME(3)` NOT NULL DEFAULT CURRENT_TIMESTAMP(3) | UTC |
| `updated_at` | `DATETIME(3)` NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) | |
| `deleted_at` | `DATETIME(3)` NULL | soft delete |

인덱스: `UNIQUE(uuid)`, `INDEX(host, channel)`, `INDEX(vendor)`, `INDEX(status)`, `INDEX(deleted_at)`, `INDEX(serial)`.

### 4.2 `streams`
| 컬럼 | 타입 | 비고 |
|---|---|---|
| `id` | `BIGINT` PK | Snowflake |
| `camera_id` | `BIGINT` NOT NULL | (FK 미설정, 인덱스만) |
| `role` | `VARCHAR(16)` NOT NULL | `main`/`sub`/`third` |
| `codec` | `VARCHAR(16)` NULL | `h264`/`h265`/`mjpeg` |
| `width` | `INT` NULL | |
| `height` | `INT` NULL | |
| `fps` | `INT` NULL | |
| `bitrate_kbps` | `INT` NULL | |
| `audio_codec` | `VARCHAR(16)` NULL | `aac`/`g711`/null |
| `rtsp_path` | `VARCHAR(255)` NULL | 경로만(자격증명 제외) |
| `rtsp_url_template` | `VARCHAR(512)` NULL | `rtsp://{user}:{pass}@{host}:{port}{path}` 자격증명 자리표시자 |
| `go2rtc_name` | `VARCHAR(128)` NOT NULL | go2rtc stream 키(예: `cam_{uuid}_sub`), `UNIQUE` |
| `is_default_live` | `TINYINT(1)` NOT NULL DEFAULT 0 | 그리드 기본 스트림(보통 sub) |
| `is_default_full` | `TINYINT(1)` NOT NULL DEFAULT 0 | 전체화면 기본(보통 main) |
| `enabled` | `TINYINT(1)` NOT NULL DEFAULT 1 | |
| `created_at`/`updated_at`/`deleted_at` | `DATETIME(3)` | 감사/soft delete |

인덱스: `UNIQUE(go2rtc_name)`, `INDEX(camera_id, role)`, `INDEX(deleted_at)`.
**주의**: `rtsp_url_template`에는 평문 자격증명을 넣지 않는다(자리표시자만). 실제 URL은 런타임에 복호화하여 go2rtc 설정에만 주입.

### 4.3 `dashboards`
| 컬럼 | 타입 | 비고 |
|---|---|---|
| `id` | `BIGINT` PK | Snowflake |
| `uuid` | `CHAR(32)` `UNIQUE` | |
| `name` | `VARCHAR(200)` NOT NULL | |
| `description` | `VARCHAR(512)` NULL | |
| `layout` | `JSON` NOT NULL | 레이아웃 정의(아래 4.7) |
| `owner_id` | `BIGINT` NOT NULL | 소유자 user id |
| `is_shared` | `TINYINT(1)` NOT NULL DEFAULT 0 | true면 ACL 행으로 공유 |
| `default_ratio_mode` | `VARCHAR(8)` NOT NULL DEFAULT 'fit' | `fit`/`stretch`/`crop` |
| `created_by_id`/`last_updated_by_id` | `BIGINT` NULL | |
| `created_at`/`updated_at`/`deleted_at` | `DATETIME(3)` | |

인덱스: `UNIQUE(uuid)`, `INDEX(owner_id)`, `INDEX(deleted_at)`.

### 4.4 `dashboard_acl`
| 컬럼 | 타입 | 비고 |
|---|---|---|
| `id` | `BIGINT` PK | Snowflake |
| `dashboard_id` | `BIGINT` NOT NULL | |
| `user_id` | `BIGINT` NOT NULL | |
| `access` | `VARCHAR(8)` NOT NULL DEFAULT 'view' | `view`/`edit` |
| `created_at` | `DATETIME(3)` NOT NULL | |

인덱스: `UNIQUE(dashboard_id, user_id)`, `INDEX(user_id)`.

### 4.5 `ptz_presets` (선택: 카메라에 저장 못하거나 미러링이 필요할 때)
대부분의 PTZ 프리셋은 **카메라 펌웨어에 저장**(ONVIF/ISAPI/SUNAPI가 토큰/번호 제공)되므로 1차는 카메라 측을 신뢰한다. 다만 표시 라벨·정렬·권한 메모를 위해 캐시 테이블을 둔다.
| 컬럼 | 타입 | 비고 |
|---|---|---|
| `id` | `BIGINT` PK | |
| `camera_id` | `BIGINT` NOT NULL | |
| `ptz_token` | `VARCHAR(64)` NULL | ONVIF preset token / ISAPI presetID / SUNAPI preset number |
| `name` | `VARCHAR(128)` NOT NULL | 표시 라벨 |
| `sort_order` | `INT` NOT NULL DEFAULT 0 | |
| `created_at`/`updated_at`/`deleted_at` | `DATETIME(3)` | |

인덱스: `INDEX(camera_id)`.

### 4.6 `cameras.capabilities` JSON 정규화 스키마
```json
{
  "probe_source": "isapi",
  "probed_at": "2026-06-05T01:02:03Z",
  "device": {"vendor": "hikvision", "model": "DS-2CD2386G2", "firmware": "V5.7.3", "serial": "DSxxxx"},
  "ptz": {"supported": true, "absolute": true, "relative": true, "continuous": true, "presets": true, "max_presets": 256, "spaces": {"pan": [-1,1], "tilt": [-1,1], "zoom": [0,1]}},
  "audio": {"input": true, "output": false, "codecs_in": ["g711a"], "two_way": false},
  "events": {"motion": true, "linecross": true, "intrusion": true, "tamper": true, "transport": "isapi_alertstream"},
  "snapshot": {"url": "/ISAPI/Streaming/channels/101/picture"},
  "streams": [
    {"role": "main", "codec": "h265", "width": 3840, "height": 2160, "fps": 20, "rtsp_path": "/Streaming/Channels/101"},
    {"role": "sub",  "codec": "h264", "width": 704,  "height": 480,  "fps": 15, "rtsp_path": "/Streaming/Channels/102"}
  ]
}
```
> `events`/`two_way`는 P1에서 **수집·저장·표시만** 하고 동작 연결은 P3/P6. capabilities는 원본 응답의 정규화 결과만 저장(민감정보 제외).

### 4.7 `dashboards.layout` JSON 스키마
```json
{
  "version": 1,
  "grid": {"cols": 12, "rows": 8, "gap": 4},
  "ratio_mode": "fit",
  "cells": [
    {"i": "c1", "camera_uuid": "ab12...", "stream_role": "sub",
     "x": 0, "y": 0, "w": 6, "h": 4, "ratio_mode": "crop"},
    {"i": "c2", "camera_uuid": "cd34...", "stream_role": "sub",
     "x": 6, "y": 0, "w": 3, "h": 2}
  ]
}
```
- 12열 기반 좌표계(x,y,w,h)로 임의 셀 스패닝/커스텀 레이아웃 표현. 4/9/16/32는 프리셋(예: 4=6x4 두 줄)으로 생성.
- 셀별 `ratio_mode`가 없으면 대시보드 기본값 사용.
- `stream_role`은 그리드에서 보통 `sub`. 전체화면 전환 시 클라이언트가 `main`으로 재협상.

### 4.8 마이그레이션 SQL 스케치 (MySQL 8)
```sql
-- 4.1 cameras (P0 스켈레톤이 있으면 ALTER, 없으면 아래 CREATE)
CREATE TABLE IF NOT EXISTS cameras (
  id BIGINT NOT NULL,
  uuid CHAR(32) NOT NULL,
  name VARCHAR(200) NOT NULL,
  vendor VARCHAR(32) NOT NULL,
  model VARCHAR(128) NULL,
  firmware VARCHAR(128) NULL,
  serial VARCHAR(128) NULL,
  driver VARCHAR(32) NOT NULL,
  protocol_fallback VARCHAR(32) NULL,
  host VARCHAR(255) NOT NULL,
  onvif_port INT NULL,
  http_port INT NULL,
  rtsp_port INT NULL,
  use_https TINYINT(1) NOT NULL DEFAULT 0,
  username_enc VARBINARY(512) NULL,
  password_enc VARBINARY(512) NULL,
  cred_key_id VARCHAR(32) NULL,
  capabilities JSON NULL,
  ptz_supported TINYINT(1) NOT NULL DEFAULT 0,
  audio_supported TINYINT(1) NOT NULL DEFAULT 0,
  two_way_audio TINYINT(1) NOT NULL DEFAULT 0,
  channel INT NOT NULL DEFAULT 1,
  timezone VARCHAR(64) NULL,
  status VARCHAR(16) NOT NULL DEFAULT 'unknown',
  last_seen_at DATETIME(3) NULL,
  last_error VARCHAR(512) NULL,
  is_enabled TINYINT(1) NOT NULL DEFAULT 1,
  created_by_id BIGINT NULL,
  last_updated_by_id BIGINT NULL,
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  deleted_at DATETIME(3) NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_cameras_uuid (uuid),
  KEY ix_cameras_host (host, channel),
  KEY ix_cameras_vendor (vendor),
  KEY ix_cameras_status (status),
  KEY ix_cameras_serial (serial),
  KEY ix_cameras_deleted (deleted_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS streams (
  id BIGINT NOT NULL,
  camera_id BIGINT NOT NULL,
  role VARCHAR(16) NOT NULL,
  codec VARCHAR(16) NULL,
  width INT NULL, height INT NULL, fps INT NULL, bitrate_kbps INT NULL,
  audio_codec VARCHAR(16) NULL,
  rtsp_path VARCHAR(255) NULL,
  rtsp_url_template VARCHAR(512) NULL,
  go2rtc_name VARCHAR(128) NOT NULL,
  is_default_live TINYINT(1) NOT NULL DEFAULT 0,
  is_default_full TINYINT(1) NOT NULL DEFAULT 0,
  enabled TINYINT(1) NOT NULL DEFAULT 1,
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  deleted_at DATETIME(3) NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_streams_go2rtc (go2rtc_name),
  KEY ix_streams_camera_role (camera_id, role),
  KEY ix_streams_deleted (deleted_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS dashboards (
  id BIGINT NOT NULL,
  uuid CHAR(32) NOT NULL,
  name VARCHAR(200) NOT NULL,
  description VARCHAR(512) NULL,
  layout JSON NOT NULL,
  owner_id BIGINT NOT NULL,
  is_shared TINYINT(1) NOT NULL DEFAULT 0,
  default_ratio_mode VARCHAR(8) NOT NULL DEFAULT 'fit',
  created_by_id BIGINT NULL, last_updated_by_id BIGINT NULL,
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  deleted_at DATETIME(3) NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_dashboards_uuid (uuid),
  KEY ix_dashboards_owner (owner_id),
  KEY ix_dashboards_deleted (deleted_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS dashboard_acl (
  id BIGINT NOT NULL,
  dashboard_id BIGINT NOT NULL,
  user_id BIGINT NOT NULL,
  access VARCHAR(8) NOT NULL DEFAULT 'view',
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (id),
  UNIQUE KEY uq_dacl (dashboard_id, user_id),
  KEY ix_dacl_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS ptz_presets (
  id BIGINT NOT NULL,
  camera_id BIGINT NOT NULL,
  ptz_token VARCHAR(64) NULL,
  name VARCHAR(128) NOT NULL,
  sort_order INT NOT NULL DEFAULT 0,
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  deleted_at DATETIME(3) NULL,
  PRIMARY KEY (id),
  KEY ix_ptz_camera (camera_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```
> P0가 일부 테이블을 만들었다면 위 CREATE를 `ALTER TABLE ... ADD COLUMN/INDEX`로 변환. 작업 종료 시 실제 적용 SQL을 최종본으로 첨부(PLAN 11절 규칙).

### 4.9 권한맵(RBAC) 확장 — P1 추가 권한
P0 권한맵(JSON, `users.permissions` 또는 `roles.permissions`)에 P1 도메인 키를 추가한다. 형식은 ams 패턴(`{ "<resource>": ["<action>", ...] }`)을 따르되, **카메라/대시보드별 세분 권한**은 별도 키로 표현한다.
```json
{
  "cameras":    ["read", "create", "update", "delete", "discover"],
  "live":       ["read"],
  "ptz":        ["control"],
  "dashboards": ["read", "create", "update", "delete", "share"],
  "camera_scope": {"*": ["view","ptz"], "ab12...": ["view"]},
  "dashboard_scope": {"*": "view"}
}
```
- `camera_scope`: 카메라별 허용 동작. `"*"`는 기본값, 특정 `camera_uuid` 키로 오버라이드. **PTZ 권한은 `ptz:control`(전역 가능) + `camera_scope[uuid] ⊇ ptz`** 의 교집합으로 최종 결정.
- `dashboard_scope`/`dashboard_acl`: 대시보드 표시·편집은 (소유자) OR (`dashboard_acl` 행) OR (admin)로 판단. `dashboard_scope`는 "공유 대시보드 일괄 view" 같은 광역 정책 표현용.
- admin은 모든 가드를 통과(P0 규칙 동일).

---

## 5. 백엔드 설계 (API 표 / controller·service·driver·task 구성)

### 5.1 디렉터리 (PLAN 6절 구조)
```
server/
├─ view/api/
│  ├─ camera.py        # /api/v1/cameras
│  ├─ discovery.py     # /api/v1/discovery
│  ├─ stream.py        # /api/v1/cameras/<uuid>/streams, /live/*
│  ├─ ptz.py           # /api/v1/cameras/<uuid>/ptz
│  ├─ dashboard.py     # /api/v1/dashboards
│  └─ snapshot.py      # /api/v1/cameras/<uuid>/snapshot, thumbnail
├─ controller/
│  ├─ camera.py  discovery.py  stream.py  ptz.py  dashboard.py  snapshot.py
├─ driver/
│  ├─ base.py          # CameraDriver ABC (공통 인터페이스)
│  ├─ onvif.py         # OnvifDriver
│  ├─ isapi.py         # IsapiDriver (Hikvision)
│  ├─ sunapi.py        # SunapiDriver (Hanwha)
│  ├─ go2rtc.py        # Go2rtcDriver (설정/시그널링)
│  └─ factory.py       # detect_vendor() + build_driver()
├─ service/
│  ├─ capability_probe.py   # 벤더 감지 + 프로빙 오케스트레이션
│  ├─ discovery.py          # WS-Discovery 실행
│  ├─ go2rtc_sync.py        # streams ↔ go2rtc 설정 동기화
│  └─ camera_health.py      # 상태 판정 로직
├─ util/
│  └─ crypto.py             # Fernet 암복호화 (cred_key_id 라우팅)
└─ task/list/
   ├─ camera_health.py      # 주기 헬스체크 (Celery beat)
   ├─ thumbnail.py          # 썸네일 갱신
   └─ discovery_scan.py     # (선택) 비동기 디스커버리
```

### 5.2 API 표
모든 경로 `/api/v1/` 프리픽스. 가드: `@login_required` + 표기된 `@permission_required`. 응답은 `ResponseBuilder`(success/bad_request/forbidden/not_found/conflict). uuid는 외부 식별자.

| Method | Path | 권한 | 설명 |
|---|---|---|---|
| GET | `/discovery/onvif` | `cameras:discover` | WS-Discovery 멀티캐스트 1회 검색(타임아웃 N초). 결과 목록 |
| POST | `/discovery/probe` | `cameras:discover` | 수동 IP(또는 범위)+자격증명으로 벤더감지+capability 프로빙(미저장) |
| GET | `/cameras` | `cameras:read` | 카메라 목록(페이지네이션 `page/items_per_page/q/sort/order`) |
| POST | `/cameras` | `cameras:create` | 카메라 등록(프로빙 결과 확정 → streams 생성 → go2rtc 동기화) |
| GET | `/cameras/<uuid>` | `cameras:read` | 카메라 상세(+streams, +capabilities) |
| POST | `/cameras/<uuid>` | `cameras:update` | 수정(자격증명 미입력 시 기존 유지). 변경 시 go2rtc 재동기화 |
| DELETE | `/cameras/<uuid>` | `cameras:delete` | soft delete + go2rtc 항목 제거 |
| POST | `/cameras/<uuid>/reprobe` | `cameras:update` | capability 재프로빙(모델 변경/펌웨어 업데이트 후) |
| GET | `/cameras/<uuid>/health` | `cameras:read` | 실시간 상태(go2rtc producer/consumer 상태 포함) |
| GET | `/cameras/<uuid>/streams` | `cameras:read` | 스트림 목록 |
| POST | `/cameras/<uuid>/streams` | `cameras:update` | 스트림 추가/수정(role/codec/path 등) → go2rtc 재동기화 |
| GET | `/cameras/<uuid>/snapshot` | `live:read` + scope | 현재 프레임 JPEG(go2rtc/ISAPI/ONVIF 경유) |
| GET | `/cameras/<uuid>/thumbnail` | `live:read` + scope | 캐시 썸네일(없으면 생성) |
| POST | `/cameras/<uuid>/ptz` | `ptz:control` + scope | PTZ 명령(아래 5.5 body) |
| GET | `/cameras/<uuid>/ptz/presets` | `live:read` + scope | 프리셋 목록 |
| POST | `/cameras/<uuid>/ptz/presets` | `ptz:control` + scope | 프리셋 저장(현재 위치) |
| POST | `/cameras/<uuid>/ptz/presets/<token>/goto` | `ptz:control` + scope | 프리셋 이동 |
| DELETE | `/cameras/<uuid>/ptz/presets/<token>` | `ptz:control` + scope | 프리셋 삭제 |
| GET | `/dashboards` | `dashboards:read` | 접근 가능한 대시보드 목록(소유 + ACL) |
| POST | `/dashboards` | `dashboards:create` | 대시보드 생성(layout JSON) |
| GET | `/dashboards/<uuid>` | `dashboards:read` + ACL | 상세(layout) |
| POST | `/dashboards/<uuid>` | `dashboards:update` + ACL(edit) | 레이아웃/이름 수정 |
| DELETE | `/dashboards/<uuid>` | `dashboards:delete` + owner | 삭제 |
| POST | `/dashboards/<uuid>/acl` | `dashboards:share` + owner | ACL 추가/수정(user_id, access) |
| DELETE | `/dashboards/<uuid>/acl/<user_id>` | `dashboards:share` + owner | ACL 제거 |
| GET | `/live/webrtc/<go2rtc_name>` (WS) | `live:read` + scope | WebRTC 시그널링 프록시(WS→go2rtc) |
| POST | `/live/webrtc/<go2rtc_name>` | `live:read` + scope | WebRTC SDP offer/answer(REST 모드) |
| GET | `/live/mse/<go2rtc_name>` (WS) | `live:read` + scope | MSE(fMP4) 프록시 |
| GET | `/live/hls/<go2rtc_name>/*` | `live:read` + scope | HLS 폴백 프록시(저사양/호환) |

#### 요청/응답 예시
**POST `/discovery/probe`** (수동/디스커버리 후 자격증명 검증·프로빙):
```jsonc
// req
{"host": "192.168.1.151", "onvif_port": 80, "http_port": 80, "rtsp_port": 554,
 "username": "admin", "password": "secret", "use_https": false, "channel": 1}
// res (data)
{"vendor": "hanwha", "driver": "sunapi", "model": "XNP-6400R", "firmware": "2.21.06",
 "serial": "ZN7Rxxxx", "ptz_supported": true, "audio_supported": true,
 "snapshot_url": "/stw-cgi/video.cgi?msubmenu=snapshot&action=view&Profile=1",
 "streams": [
   {"role":"main","codec":"h265","width":2560,"height":1440,"fps":30,"rtsp_path":"/profile1/media.smp"},
   {"role":"sub","codec":"h264","width":640,"height":360,"fps":15,"rtsp_path":"/profile2/media.smp"}],
 "capabilities": { /* 4.6 정규화 */ },
 "reachable": {"onvif": true, "vendor_api": true, "rtsp": true}}
```
**POST `/cameras`** (확정 등록):
```jsonc
// req — probe 결과를 그대로 보내되 name/credentials 포함
{"name": "정문 PTZ", "host":"192.168.1.151", "vendor":"hanwha", "driver":"sunapi",
 "onvif_port":80,"http_port":80,"rtsp_port":554,"channel":1,
 "username":"admin","password":"secret","use_https":false,
 "streams":[{"role":"main",...},{"role":"sub",...}],
 "capabilities": { ... }}
// res
{"uuid":"ab12...","name":"정문 PTZ","status":"online","ptz_supported":true,
 "streams":[{"role":"main","go2rtc_name":"cam_ab12_main"},{"role":"sub","go2rtc_name":"cam_ab12_sub"}]}
```
**GET `/cameras/<uuid>/health`**:
```jsonc
{"status":"online","last_seen_at":"2026-06-05T01:10:00Z",
 "go2rtc":{"cam_ab12_main":{"producers":1,"consumers":2,"recv_bytes":12345678},
           "cam_ab12_sub":{"producers":1,"consumers":5}}}
```

### 5.3 Controller 책임
- **CameraController**: 입력 검증(host/port/vendor), 중복 등록 감지(serial 또는 host+channel), 자격증명 암호화 호출, streams 생성, `go2rtc_sync.sync_camera()` 트리거, `to_dict`(자격증명 절대 제외). 응답 직렬화 시 `username/password` 평문은 **반환하지 않음**(존재 여부 `has_credentials: true`만).
- **DiscoveryController**: `service.discovery.ws_discovery()` 호출 + 결과 정규화. `probe`는 `capability_probe.probe()` 위임(미저장).
- **StreamController**: 스트림 CRUD + go2rtc 재동기화.
- **PtzController**: scope 가드 확인 → 드라이버 PTZ 호출. 좌표/속도 범위 검증.
- **DashboardController**: layout JSON 검증(스키마 4.7, 셀 좌표 경계/카메라 uuid 존재), ACL 권한 판단(owner/ACL/admin).
- **SnapshotController**: go2rtc `/api/frame.jpeg?src=` 우선, 실패 시 벤더 스냅샷 URL 폴백.

### 5.4 Driver 공통 인터페이스 (`driver/base.py`)
```python
class CameraDriver(ABC):
    def __init__(self, host, *, http_port, rtsp_port, onvif_port,
                 username, password, use_https=False, channel=1): ...

    # --- 식별/프로빙 ---
    @abstractmethod
    def get_device_info(self) -> DeviceInfo: ...           # vendor/model/firmware/serial
    @abstractmethod
    def get_stream_profiles(self) -> list[StreamProfile]: ...# role/codec/res/fps/rtsp_path
    @abstractmethod
    def get_capabilities(self) -> Capabilities: ...        # ptz/audio/events/snapshot (4.6)

    # --- 미디어 보조 ---
    @abstractmethod
    def get_rtsp_url(self, role: str) -> str: ...          # 자격증명 포함(go2rtc 주입 전용)
    @abstractmethod
    def get_snapshot(self) -> bytes | None: ...

    # --- PTZ (미지원 시 PtzUnsupported) ---
    @abstractmethod
    def ptz_continuous(self, pan: float, tilt: float, zoom: float, speed: float|None): ...
    @abstractmethod
    def ptz_stop(self): ...
    @abstractmethod
    def ptz_relative(self, pan: float, tilt: float, zoom: float): ...
    @abstractmethod
    def ptz_absolute(self, pan: float, tilt: float, zoom: float): ...
    @abstractmethod
    def ptz_list_presets(self) -> list[Preset]: ...
    @abstractmethod
    def ptz_goto_preset(self, token: str, speed: float|None=None): ...
    @abstractmethod
    def ptz_set_preset(self, name: str, token: str|None=None) -> Preset: ...
    @abstractmethod
    def ptz_remove_preset(self, token: str): ...

    # --- 연결 점검 ---
    @abstractmethod
    def healthcheck(self) -> HealthStatus: ...             # reachable + auth ok
```
`factory.detect_vendor(host, ports, creds)`:
1. ONVIF GetDeviceInformation의 `Manufacturer` 우선(zeep). 실패하면
2. ISAPI `GET /ISAPI/System/deviceInfo`(Digest) 200 → Hikvision.
3. SUNAPI `GET /stw-cgi/system.cgi?msubmenu=deviceinfo&action=view`(Digest) 200 → Hanwha.
4. 모두 실패 → `unknown`(수동 RTSP 경로 입력 모드로 폴백).
`build_driver(vendor)`는 벤더 드라이버 + `OnvifDriver`를 폴백 체인으로 래핑(`CompositeDriver`): 벤더 메서드 우선, `NotSupported`면 ONVIF로 위임.

### 5.5 PTZ 요청 body (POST `/cameras/<uuid>/ptz`)
```jsonc
// 연속(누르고 있는 동안) — pan/tilt/zoom: -1.0..1.0
{"action":"continuous","pan":0.5,"tilt":0.0,"zoom":0.0,"speed":0.7}
{"action":"stop"}
{"action":"relative","pan":0.1,"tilt":-0.1,"zoom":0.0}
{"action":"absolute","pan":0.0,"tilt":0.0,"zoom":0.5}
{"action":"goto_preset","token":"3","speed":0.8}
```
검증: 값 [-1,1], speed [0,1]. `ptz:control` + `camera_scope[uuid] ⊇ ptz` 동시 충족 필수.

### 5.6 Service: go2rtc 동기화 (`go2rtc_sync.py`)
- `sync_camera(camera)`: 카메라의 활성 streams마다 go2rtc 스트림 항목 생성/갱신. 우선순위: **go2rtc REST API**(`PUT /api/streams?name=...&src=...`) 사용, 실패 시 `go2rtc.yaml` 머지 후 reload. 소스 URL은 자격증명을 런타임 복호화하여 주입(DB엔 자리표시자만).
- `remove_camera(camera)`: 스트림 항목 삭제(`DELETE /api/streams?src=name`).
- go2rtc 소스에 `#video=copy#audio=copy`(무재인코딩) 우선. sub가 H.265라 WebRTC 비호환 시에만 온디맨드 트랜스코딩 옵션(`#video=h264`) 표시(성능 경고와 함께).

### 5.7 Task (Celery beat)
| 태스크 | 스케줄 | 동작 |
|---|---|---|
| `camera_health_check` | 30s | 활성 카메라별 go2rtc producer 상태 + 벤더/ONVIF healthcheck → `status`/`last_seen_at`/`last_error` 갱신. 변경 시 WS로 프론트 푸시 |
| `thumbnail_refresh` | 60s | 활성 카메라 sub 스냅샷 → 썸네일 캐시(파일 or Redis) 갱신 |
| `discovery_scan`(옵션) | on-demand | 무거운 WS-Discovery를 비동기로(결과 캐시) |

---

## 6. 미디어·스트리밍 (go2rtc·WebRTC/MSE·ffmpeg·메인/서브 스트림)

### 6.1 원칙 (PLAN 4절 재확인)
- **카메라당 소스 1연결**: go2rtc가 RTSP를 1회만 끌어와 라이브(P1)·녹화(P2)·AI(P4)가 공유.
- **그리드=서브, 전체화면=메인**: 다채널 동시표시는 sub(저해상)로 부하 최소화, 전체화면/녹화/AI는 main.
- **WebRTC 패스스루**: 서버 트랜스코딩 없음. 재인코딩은 온디맨드(P2 다운로드/썸네일)만.

### 6.2 go2rtc 설정 예시 (`go2rtc/go2rtc.yaml` — 동적 생성분 + 정적 기본)
```yaml
api:
  listen: ":1984"          # 내부 전용. 외부 노출은 axp-backend 프록시로만
rtsp:
  listen: ":8554"
webrtc:
  listen: ":8555"          # UDP/TCP. 단일 온프레미스는 호스트 네트워크 권장
  candidates:
    - "stun:stun.l.google.com:19302"   # 내부망이면 호스트 IP 직접 후보로
streams:
  cam_ab12_main:
    - "rtsp://admin:secret@192.168.1.151:554/profile1/media.smp#video=copy#audio=copy"
  cam_ab12_sub:
    - "rtsp://admin:secret@192.168.1.151:554/profile2/media.smp#video=copy#audio=copy"
  cam_cd34_sub:
    - "rtsp://admin:secret@192.168.1.189:554/Streaming/Channels/102#video=copy"
```
> 자격증명 평문이 go2rtc.yaml/메모리에 존재하므로 파일 권한(600)·컨테이너 격리·내부망 전용을 강제. REST API 동기화를 1차로 하고 yaml은 부팅 시드/백업으로만 사용 권장.

### 6.3 시그널링 경로 (브라우저 → 백엔드 프록시 → go2rtc)
- 브라우저는 go2rtc를 직접 보지 못한다(보안·인증). 모든 라이브 트래픽은 `axp-backend`가 프록시하며 **JWT + scope**를 검증.
- **WebRTC(WS)**: `wss://<host>/api/v1/live/webrtc/<go2rtc_name>` → 백엔드가 토큰/scope 검증 후 go2rtc `/api/ws?src=<name>`로 WS 양방향 릴레이(SDP/ICE 교환). 미디어(SRTP/ICE)는 go2rtc↔브라우저 직접(단일 온프레미스: 호스트 네트워크 모드면 NAT 단순). 외부망은 백엔드/리버스프록시가 ICE 후보를 공인 IP로 광고하거나 TURN 사용.
- **WebRTC(REST 대안)**: `POST /api/v1/live/webrtc/<name>`에 SDP offer → go2rtc `/api/webrtc?src=<name>`로 중계 → answer 반환(WS 불가 환경).
- **MSE 폴백(WS)**: `wss://.../api/v1/live/mse/<name>` → go2rtc `/api/ws?src=<name>`(MSE 모드). H.264/AAC fMP4를 MediaSource로 재생.
- **HLS 폴백**: `GET /api/v1/live/hls/<name>/index.m3u8` 프록시(저지연 불요·호환 최우선/iOS Safari 일부).
- 프론트는 **VideoRTC 류 로직**(WebRTC 우선 → 실패/타임아웃 시 MSE → HLS) 자체 컴포넌트로 구현(아래 8.4).

### 6.4 메인/서브 선택 로직
- LiveGrid 셀: `stream_role=sub` 기본 → `cam_{uuid}_sub`.
- 전체화면/단일뷰: `main` 재협상 → `cam_{uuid}_main`.
- sub가 H.265라 WebRTC 비호환이면: (a) MSE로 폴백(H.265 MSE는 브라우저 한정) 또는 (b) 카메라 sub를 H.264로 설정하도록 등록 마법사에서 권고. 최후엔 온디맨드 트랜스코딩(성능 경고).

### 6.5 ffmpeg의 위치
- P1에서 ffmpeg 상시 사용 없음(go2rtc가 담당). **스냅샷/썸네일**만 보조: go2rtc `/api/frame.jpeg?src=<name>` 우선, 불가 시 백엔드가 `ffmpeg -rtsp_transport tcp -i <rtsp> -frames:v 1 out.jpg`(ams `camera.py` 패턴 차용)로 단발 캡처. 상시 녹화 ffmpeg supervisor는 P2.

---

## 7. 외부 연동·드라이버 (ONVIF / Hikvision ISAPI / Hanwha SUNAPI 구체)

세 벤더의 인증은 공통적으로 **HTTP Digest**(일부 ONVIF는 WS-UsernameToken). 모두 `requests`/`httpx`의 `HTTPDigestAuth` 사용. HTTPS 자체서명 인증서 흔하므로 `verify` 옵션 노출.

### 7.1 ONVIF (`OnvifDriver`, onvif-zeep)
- **디스커버리**: WS-Discovery(멀티캐스트 `239.255.255.250:3702`, `Probe` SOAP). `wsdiscovery`/`onvif-zeep`의 discovery로 `XAddrs`(서비스 URL)·`Scopes`(제조사/모델/하드웨어) 수집. UDP 멀티캐스트라 동일 L2/대역만 도달 → 타 대역은 수동.
- **장치정보**: `devicemgmt.GetDeviceInformation()` → Manufacturer/Model/FirmwareVersion/SerialNumber.
- **프로필/스트림**: `media.GetProfiles()` → 각 Profile의 `VideoEncoderConfiguration`(Encoding=H264/H265, Resolution, RateControl.FrameRateLimit). `media.GetStreamUri({StreamSetup:{Stream:'RTP-Unicast',Transport:{Protocol:'RTSP'}}, ProfileToken})` → RTSP URL.
- **capabilities/services**: `devicemgmt.GetCapabilities()`(PTZ/Events/Media 주소), `GetServices(IncludeCapability=true)`(네임스페이스별 지원). PTZ 존재 시 `ptz` 서비스 바인딩.
- **PTZ**: `ptz.ContinuousMove({ProfileToken, Velocity:{PanTilt:{x,y}, Zoom:{x}}})`, `ptz.Stop`, `ptz.RelativeMove`, `ptz.AbsoluteMove`, `ptz.GetPresets`, `ptz.GotoPreset({PresetToken})`, `ptz.SetPreset({PresetName})`, `ptz.RemovePreset`. 속도/공간은 `GetConfigurationOptions`로 범위 확인.
- **스냅샷**: `media.GetSnapshotUri(ProfileToken)` → HTTP GET(Digest).
- **이벤트(수집만, P3 연결)**: `events`(PullPoint) 지원 여부만 capabilities에 기록.

### 7.2 Hikvision ISAPI (`IsapiDriver`, requests+Digest, XML)
- **장치정보**: `GET /ISAPI/System/deviceInfo` → `<DeviceInfo>`의 `model`/`firmwareVersion`/`serialNumber`/`deviceType`.
- **스트림 채널**: `GET /ISAPI/Streaming/channels` → 채널별 `<StreamingChannel>`(id 101=main,102=sub,103=third). 각 채널 `<Video>`의 `videoCodecType`(H.264/H.265/H.265+), `videoResolutionWidth/Height`, `maxFrameRate`(×100, 예 2500=25fps), `constantBitRate`. RTSP 경로 규칙: `/Streaming/Channels/101`(main), `/102`(sub).
- **capabilities**: `GET /ISAPI/System/capabilities`, PTZ는 `GET /ISAPI/PTZCtrl/channels/1/capabilities`, 이벤트는 `GET /ISAPI/Event/triggers`(motion/linedetection/fielddetection/tamperdetection 존재 확인).
- **PTZ**:
  - 연속: `PUT /ISAPI/PTZCtrl/channels/1/continuous`, body `<PTZData><pan>..</pan><tilt>..</tilt><zoom>..</zoom></PTZData>`(−100..100). stop은 0 전송.
  - 절대: `PUT /ISAPI/PTZCtrl/channels/1/absolute`(`<elevation>/<azimuth>/<absoluteZoom>`).
  - 프리셋: 목록 `GET /ISAPI/PTZCtrl/channels/1/presets`, 이동 `PUT /ISAPI/PTZCtrl/channels/1/presets/<id>/goto`, 저장 `POST/PUT .../presets/<id>`(`<PTZPreset><id>..<name>..`), 삭제 `DELETE .../presets/<id>`. 토큰=presetID 정수.
  - 정규화: 백엔드 [-1,1] → ISAPI [-100,100] 매핑.
- **스냅샷**: `GET /ISAPI/Streaming/channels/101/picture`(Digest, JPEG).
- **이벤트(P3)**: `GET /ISAPI/Event/notification/alertStream`(멀티파트 스트림). P1은 지원만 기록.

### 7.3 Hanwha SUNAPI (`SunapiDriver`, requests+Digest, query CGI/JSON)
- 엔드포인트 기본형 `/<group>-cgi/<file>.cgi?msubmenu=<sub>&action=<view|set|control|add|remove>&...`. 응답은 key=value 또는 JSON(`responsejson` 지원 시).
- **장치정보**: `GET /stw-cgi/system.cgi?msubmenu=deviceinfo&action=view` → Model/FirmwareVersion/DeviceType/MAC.
- **스트림/프로필**: `GET /stw-cgi/media.cgi?msubmenu=videoprofile&action=view&Channel=0` → 프로필별 EncodingType(H264/H265/MJPEG)/Resolution/FrameRate/Bitrate. RTSP 경로 규칙: `/profile1/media.smp`, `/profile2/media.smp`(프로필 번호 기반).
- **capabilities**: `GET /stw-cgi/attributes.cgi/...`(또는 `/stw-cgi/system.cgi?msubmenu=...`)로 PTZ/Audio/Event 속성. 이벤트 상태는 `GET /stw-cgi/eventstatus.cgi?msubmenu=eventstatus&action=monitor`(P3에서 사용).
- **PTZ** (`/stw-cgi/ptzcontrol.cgi`):
  - 연속: `?msubmenu=continuous&action=control&Channel=0&Pan=<-1..1 매핑>&Tilt=..&Zoom=..`. stop은 0.
  - 절대/상대: `?msubmenu=absolute|relative&...&Pan=&Tilt=&Zoom=`.
  - 프리셋: 목록 `?msubmenu=preset&action=view`, 이동 `?msubmenu=preset&action=control&Preset=<n>`, 저장 `?msubmenu=preset&action=add&Preset=<n>&Name=<>`, 삭제 `?action=remove&Preset=<n>`. 토큰=preset 번호.
  - 정규화: 백엔드 [-1,1] → SUNAPI 속도 스케일(모델별 범위, capabilities에서 확인).
- **스냅샷**: `GET /stw-cgi/video.cgi?msubmenu=snapshot&action=view&Profile=<n>`(JPEG).

### 7.4 폴백·차이 처리
- **CompositeDriver**: 벤더 메서드 우선, 미지원/HTTP 4xx면 ONVIF로 폴백. 예) 구형 Hanwha의 특정 속성 누락 시 ONVIF GetProfiles로 스트림 보강.
- **자격증명 검증 실패(401)**: `status=unauthorized`로 분리(오프라인과 구분)하여 UI에 명확 표기.
- **벤더 RTSP 경로 차이**: ISAPI=`/Streaming/Channels/{ch}{stream}`, SUNAPI=`/profile{n}/media.smp`, ONVIF=GetStreamUri 결과. `streams.rtsp_path`에 확정 저장.

---

## 8. 프론트엔드(TS) (라이브 그리드·레이아웃 에디터·PTZ·카메라추가 마법사·DESIGN.md 적용)

### 8.1 디렉터리 (ams 페이지-디렉터리 패턴 + TS)
```
frontend/src/
├─ pages/
│  ├─ live/
│  │  ├─ LivePage.tsx                # 대시보드 선택 + LiveGrid 호스트
│  │  ├─ index.ts
│  │  ├─ components/
│  │  │  ├─ LiveGrid.tsx             # 그리드 렌더 + dnd-kit
│  │  │  ├─ CameraTile.tsx           # 단일 타일(비디오+오버레이)
│  │  │  ├─ VideoPlayer.tsx          # WebRTC→MSE→HLS 폴백 엔진
│  │  │  ├─ PtzControls.tsx          # PTZ 패드/줌/프리셋
│  │  │  ├─ LayoutEditor.tsx         # 레이아웃 편집(스팬/비율/프리셋)
│  │  │  ├─ LayoutPresetBar.tsx      # 1/4/9/16/32/커스텀
│  │  │  └─ RatioModeToggle.tsx      # fit/stretch/crop
│  │  ├─ hooks/
│  │  │  ├─ useWebRTC.ts  useMSE.ts  useDashboard.ts  useLiveAuthToken.ts
│  │  └─ api/live.api.ts
│  ├─ cameras/
│  │  ├─ CamerasPage.tsx             # 카메라 목록(TanStack Table)
│  │  ├─ components/
│  │  │  ├─ CameraAddWizard.tsx      # 검색/수동 → 프로빙 → 확정 (3-step)
│  │  │  ├─ DiscoveryList.tsx        # WS-Discovery 결과
│  │  │  ├─ ProbeResultCard.tsx      # capability 표시(확정 전)
│  │  │  ├─ CameraHealthBadge.tsx    # 상태 점
│  │  │  └─ StreamEditor.tsx
│  │  └─ api/camera.api.ts
│  └─ dashboards/
│     ├─ DashboardsPage.tsx          # 대시보드 CRUD + ACL 관리
│     └─ api/dashboard.api.ts
├─ types/  axp.d.ts                  # Camera/Stream/Dashboard/LayoutCell/Capabilities 타입
└─ routing/ (P0 AppRoutingSetup 확장)
```

### 8.2 라우트 & 상태관리
- 라우트(P0 `AppRoutingSetup` 확장): `/live`, `/live/:dashboardUuid`, `/cameras`, `/cameras/add`, `/dashboards`. 모두 `RequireAuth` 하위.
- 상태: **TanStack Query**(서버 상태: 카메라/대시보드/프로빙) + 로컬 상태(편집 중 레이아웃은 컴포넌트 state, 저장 시 mutation). 전역 Provider 추가 최소화(P0 Provider 중첩 순서 유지).
- 라이브 토큰: 라이브 WS/스냅샷은 짧은 수명 **scoped live token**(audience=`live`)을 `useLiveAuthToken`이 발급받아 WS 쿼리/헤더로 전달(쿠키 불가 환경 대비). access JWT 재사용도 허용(P0 정책에 맞춤).

### 8.3 카메라 추가 마법사 (`CameraAddWizard`)
1. **소스 선택**: 탭 [네트워크 검색 | 수동 입력]. 검색 탭은 `GET /discovery/onvif` 결과를 `DiscoveryList`로 표시(제조사/모델/IP/서비스URL), 선택 시 host/port 자동 채움. 수동 탭은 host/포트 직접 입력(IP 범위 입력 시 순차 probe).
2. **인증·프로빙**: ID/PW 입력 → `POST /discovery/probe` → 로딩 후 `ProbeResultCard`에 vendor/model/firmware/PTZ/audio/streams(main·sub 해상도·코덱·fps)/reachable 표시. 자격증명 오류면 `unauthorized` 메시지.
3. **확정**: 표시명 입력 + 기본 라이브/전체화면 스트림 선택(보통 sub/main) → `POST /cameras`. 성공 시 카메라 목록/라이브로 이동, go2rtc 동기화 완료 후 타일이 곧 점등.

### 8.4 VideoPlayer 폴백 엔진 (`VideoPlayer.tsx` + `useWebRTC`/`useMSE`)
- 입력: `go2rtcName`, `mode('webrtc'|'mse'|'hls'|'auto')`, `ratioMode`.
- auto 순서: WebRTC 시도(`POST/WS /live/webrtc/<name>`로 SDP/ICE) → N초 내 트랙 미수신/실패 시 MSE(`WS /live/mse/<name>`) → 그래도 실패 시 HLS(`/live/hls/<name>/index.m3u8`).
- `<video>` 속성: `autoplay muted playsInline`. ratioMode 매핑: `fit`→`object-contain`(레터박스), `stretch`→`object-fill`, `crop`→`object-cover`. 페이지 비가시(`visibilitychange`)·타일 오프스크린(IntersectionObserver) 시 연결 일시중단으로 부하 절감.
- 재연결: 끊김 시 지수 백오프(ams `useTelemetryStream`/`camera.py` 재연결 패턴 차용).

### 8.5 LiveGrid + LayoutEditor (dnd-kit)
- `LiveGrid`는 `dashboards.layout`(4.7)을 12열 CSS Grid로 렌더. 각 셀=`CameraTile`(`gridColumn: span w; gridRow: span h`).
- 편집 모드: dnd-kit `DndContext`+`useSortable`로 셀 이동/스왑. 리사이즈 핸들로 `w/h`(스팬) 변경, 충돌 시 자동 정렬. `LayoutPresetBar`로 1/4/9/16/32 프리셋 즉시 적용(셀 재배치), 커스텀은 자유 배치. `RatioModeToggle`로 대시보드/셀 단위 비율 모드. "저장"→`POST /dashboards/<uuid>`(layout JSON).
- 빈 셀에 카메라 드롭(카메라 목록 패널에서 드래그) → `camera_uuid` 할당.

### 8.6 PtzControls
- PTZ 카메라(`ptz_supported && scope⊇ptz`)에서만 표시. 방향 패드(8방향, mousedown→`continuous`, mouseup→`stop`), 줌 +/−, 속도 슬라이더, 프리셋 드롭다운(목록/이동/저장/삭제). 명령은 `POST /cameras/<uuid>/ptz`. 권한 없으면 컨트롤 비표시(서버에서도 403 이중가드).
- 전체화면 단일뷰에서 더 큰 PTZ 오버레이 제공.

### 8.7 DESIGN.md 적용 (Tesla 미니멀의 NVR 해석)
DESIGN.md는 백색 캔버스 기준이지만 NVR 라이브는 **다크 캔버스에 영상이 히어로**(DESIGN의 "사진/영상이 모든 감정 무게를 진다" 원칙을 영상으로 치환). 적용 규칙:
- **캔버스**: 라이브 페이지 배경 `Carbon Dark(#171A20)`. 그리드 갭은 8px 기반(4/8px), 타일 사이 구분은 **테두리 대신 여백**(DESIGN: 선이 아닌 간격으로 분리). 타일 라운드 4px(precision), 그림자 **없음**(Level 0 flat).
- **UI 크롬 최소화**: 타일 오버레이(카메라명/상태/FPS)는 평소 숨김, hover/포커스 시만 표면화(frosted: `rgba(23,26,32,0.55)` 위 순백 텍스트). 네비/툴바는 떠 있는 느낌, 테두리·그림자 없음.
- **색**: 유일 강조색 `Electric Blue(#3E6AE1)` — 라이브 연결중/선택 셀 테두리·기본 CTA("카메라 추가","저장")에만. 상태 점(온/오프라인)은 기능적 신호로 최소 채도 녹/적 허용(DESIGN의 폼-컨텍스트 예외 준용)하되 과용 금지.
- **타이포**: Universal Sans(Display=히어로 텍스트, Text=UI). 본문/네비 14px, 가중치 400/500만(bold·light 금지), letter-spacing normal, 대문자 변환 금지.
- **버튼**: 4px 라운드, primary=Electric Blue/순백 텍스트, secondary=흰 배경/Graphite, 0.33s 트랜지션, scale/translate hover 금지(색 전환만).
- **모달/마법사**: 오버레이 `rgba(128,128,128,0.65)`, 패널은 흰 배경(관리 화면은 라이트, 라이브는 다크 — 컨텍스트 분리). 입력 placeholder `Silver Fog(#8E8E8E)`.
- **반응형**: DESIGN 브레이크포인트 준용. 모바일에서 그리드는 1열(세로 스택), PTZ는 풀폭 컨트롤로. 터치 타깃 ≥44px.

---

## 9. 작업 분해 (순서 있는 체크리스트)

1. **의존 패키지/유틸**: `cryptography`·`onvif-zeep`(+WS-Discovery)·`requests`/`httpx` 추가. `util/crypto.py`(Fernet, `CREDENTIAL_ENC_KEY`, `cred_key_id` 라우팅) 구현 + unit.
2. **모델/마이그레이션**: `cameras`/`streams`/`dashboards`/`dashboard_acl`/`ptz_presets` 모델 + 4.8 SQL(또는 P0 스켈레톤 ALTER). `to_dict`에서 자격증명 제외 보장.
3. **드라이버 기반**: `driver/base.py`(ABC + DTO), `factory.detect_vendor/build_driver`, `CompositeDriver`. unit(파서/시그니처는 픽스처 XML/JSON으로).
4. **벤더 드라이버**: `isapi.py`/`sunapi.py`/`onvif.py` — device_info/profiles/capabilities/snapshot/PTZ. 픽스처 기반 파싱 테스트.
5. **capability_probe 서비스** + `discovery` 서비스(WS-Discovery). `POST /discovery/probe`, `GET /discovery/onvif` 뷰/컨트롤러.
6. **카메라 CRUD**: `camera.py`(view/controller) + 암호화 저장 + 중복감지 + streams 자동생성.
7. **go2rtc 드라이버/동기화**: `driver/go2rtc.py`(REST + yaml 폴백), `service/go2rtc_sync.py`. 등록/수정/삭제에 연동. compose에 `axp-go2rtc` 확인.
8. **라이브 시그널링 프록시**: `/live/webrtc|mse|hls` 뷰(JWT+scope 검증 후 go2rtc WS/HTTP 릴레이). scoped live token 발급.
9. **스냅샷/썸네일**: `snapshot.py` + `thumbnail_refresh` 태스크.
10. **PTZ API**: `ptz.py`(view/controller) + 프리셋 + scope 가드. `ptz_presets` 캐시.
11. **헬스 태스크**: `camera_health_check`(Celery beat) + 상태 WS 푸시.
12. **대시보드/ACL**: `dashboard.py`(view/controller) + layout 검증 + ACL 권한.
13. **권한맵 확장**: P0 RBAC에 `cameras`/`live`/`ptz`/`dashboards` + `camera_scope`/`dashboard_scope` 키 + 가드 헬퍼.
14. **프론트 타입/API**: `types/axp.d.ts`, `*.api.ts`(Axios, `data?.data` 언랩).
15. **CamerasPage + CameraAddWizard + DiscoveryList + ProbeResultCard**.
16. **VideoPlayer 폴백 엔진**(useWebRTC/useMSE/HLS) + CameraTile.
17. **LiveGrid + LayoutEditor + dnd-kit + 프리셋/비율 모드**.
18. **PtzControls**.
19. **DashboardsPage + ACL UI**.
20. **DESIGN.md 적용/폴리시**(다크 캔버스, hover 오버레이, 색/타이포 토큰).
21. **테스트 전반**(12절) + 회귀 점검 + 보안 점검(13절).
22. **마이그레이션 최종 SQL 확정** + 문서 갱신(10·14절).

---

## 10. 다른 기능/Phase에 미치는 영향 (Cross-feature Impact) ★

| 대상 | 영향 | P1에서 준비할 것 |
|---|---|---|
| **P2 녹화/스토리지** | 녹화는 go2rtc의 **동일 스트림**(`go2rtc_name`)을 ffmpeg recorder가 소비. main 스트림이 녹화 기본. | `streams.go2rtc_name`/`role`/`codec`을 P2가 그대로 사용하도록 안정적 네이밍·인덱스 확정. `cameras.is_enabled`로 녹화 대상 토글 일관. go2rtc 소스는 `copy`(무재인코딩) 유지(P2 세그먼트 copy 전제). |
| **P3 이벤트** | ONVIF PullPoint/ISAPI alertStream/SUNAPI eventstatus 구독은 P3. | `capabilities.events`에 지원/transport를 P1에서 수집·저장. 드라이버에 이벤트 메서드 **자리(stub)** 남김. 카메라 모델/채널 식별자 고정. |
| **P4 AI** | AI detector도 go2rtc main 스트림 공유. | `go2rtc_name` 규약·decode 프레임 공유 전제 유지. 카메라별 AI on/off는 P4가 `cameras`에 컬럼 추가 예정(P1 스키마와 충돌 없게 여유). |
| **P5 자동화/모니터** | 모니터 클라이언트는 특정 **대시보드 한정 scoped JWT**로 라이브만 봄. | `dashboards`/`dashboard_acl`/layout JSON을 모니터가 재사용. 라이브 시그널링 프록시가 audience=`monitor` 토큰도 검증하도록 토큰 검증부를 일반화. PTZ 권한 모델을 규칙엔진(자동 프리셋 이동)이 재사용 가능하게. |
| **P6 패리티** | 양방향오디오/디워핑/마스킹/시퀀스 자동전환. | `cameras.two_way_audio`/`audio_supported` 미리 수집. layout JSON `version` 필드로 후속 확장(시퀀스/사이클) 호환. WebRTC 경로에 오디오 송신 추가 여지(현재 recv 위주). |
| **인증/RBAC(P0)** | P1이 권한맵에 다수 키 추가 + 카메라/대시보드별 scope 도입. | `camera_scope`/`dashboard_scope` 해석 헬퍼를 공용 util로 두어 P3~P6가 재사용. 신규 카메라 추가 시 기존 user 권한맵에 자동 반영 정책(기본 deny/admin allow) 결정 필요(→14). |
| **공통 WS/실시간** | 헬스/상태 push용 WebSocket 채널 신설. | 단일 WS 게이트웨이로 상태·(후속)이벤트·detection을 다중화하도록 채널 네이밍 규약(`camera.status`, 후속 `event.*`) 정립. |
| **보안 횡단** | 자격증명 평문이 go2rtc/메모리에 존재. | go2rtc 내부망 전용·파일권한·API 프록시 강제. crypto 키 회전(`cred_key_id`) 설계 → 모든 후속 Phase 동일 키 사용. |
| **i18n/시간대** | 라이브 오버레이/상태 라벨 다수. | ko/en 메시지 키 추가, 표시 KST·저장 UTC 일관. |

> 본 절은 구현 중 변동 시 즉시 갱신(PLAN 0절 규칙). 특히 `go2rtc_name` 규약과 `streams` 스키마는 P2~P4가 직접 의존하므로 변경 시 영향 큰 항목으로 표시.

---

## 11. 리스크 & 완화

| 리스크 | 영향 | 완화 |
|---|---|---|
| **WS-Discovery 미도달**(타 대역/멀티캐스트 차단) | 카메라 검색 누락 | 수동 IP/범위 추가 + 벤더 API 직접 프로빙을 1급 경로로. 디스커버리는 보조. |
| **벤더 펌웨어별 엔드포인트 편차**(ISAPI/SUNAPI 버전차) | 프로빙/PTZ 실패 | CompositeDriver로 ONVIF 폴백. 파싱은 관대하게(필드 누락 허용) + 픽스처 다버전 테스트. `unknown`이면 수동 RTSP 경로 입력 모드. |
| **H.265 sub 스트림 WebRTC 비호환** | 그리드 검은 화면 | MSE 폴백 + 마법사에서 "sub를 H.264로" 권고 + 최후 온디맨드 트랜스코딩(경고). |
| **WebRTC NAT/ICE**(외부망) | 라이브 연결 실패 | 단일 온프레미스는 호스트 네트워크/내부 IP 후보. 외부는 리버스프록시 공인후보/TURN. MSE/HLS 폴백 항상 제공. |
| **자격증명 평문 노출**(go2rtc.yaml/메모리/로그) | 보안 사고 | 내부망 전용·파일권한 600·API 프록시·로그 마스킹·Fernet 저장·키 회전. REST 동기화 우선(yaml 최소화). |
| **카메라 동시 연결 과다**(헬스 폴링 + 프로빙) | 카메라/네트워크 부하 | go2rtc 단일연결 원칙 준수. 헬스는 go2rtc 상태 조회 위주(직접 RTSP 재연결 자제). 프로빙은 타임아웃·동시성 제한. |
| **레이아웃 JSON 신뢰 입력** | 깨진 그리드/저장 오류 | 서버 스키마 검증(좌표 경계·카메라 존재·중복 셀). 버전 필드. |
| **대시보드 ACL 우회** | 비인가 라이브 시청 | 라이브 시그널링 프록시가 매 연결마다 scope+ACL 재검증(프론트 신뢰 금지). |
| **go2rtc 컨테이너 다운** | 전체 라이브 중단 | 헬스 표면화 + 자동 재시작(compose restart) + 백엔드 503 명확화. |

---

## 12. 테스트 계획 (unit/integration/e2e)

### Unit
- `crypto`: 암복호화 왕복, 잘못된 키/`cred_key_id` 처리, `to_dict` 자격증명 비노출.
- 드라이버 파서: ISAPI deviceInfo/Streaming/channels XML, SUNAPI videoprofile/deviceinfo 응답, ONVIF GetProfiles(zeep mock) → 정규화 결과 검증. PTZ 값 매핑([-1,1]↔벤더 범위).
- `factory.detect_vendor`: 각 시그니처(ISAPI/SUNAPI/ONVIF/unknown) 분기.
- `go2rtc_sync`: streams → REST 호출/yaml 머지 페이로드, 삭제. 자격증명 주입 위치(자리표시자 치환).
- 권한: `camera_scope`/`dashboard` ACL 판정 매트릭스(admin/owner/acl-view/acl-edit/deny).
- layout 스키마 검증(경계/중복/미존재 카메라).

### Integration (Flask 테스트 클라이언트 + 드라이버/ go2rtc mock)
- 카메라 CRUD: probe(mock) → create → streams 생성 → go2rtc_sync 호출 확인 → get/edit(자격증명 유지)/delete(soft + go2rtc 제거).
- 권한 가드: 각 엔드포인트 비인가 403, scope 부족 시 403(특히 PTZ/대시보드).
- 라이브 시그널링: `/live/webrtc|mse` WS 핸드셰이크가 scope 검증 후 go2rtc(mock)로 릴레이.
- 헬스 태스크: 상태 전이(online/offline/unauthorized)와 `last_error` 기록.
- 대시보드/ACL: 공유/회수에 따른 접근 변화.

### E2E (Playwright)
- 시나리오: 로그인 → 카메라 추가 마법사(검색 or 수동 → 프로빙 결과 표시 → 확정) → 라이브 페이지에서 타일 점등(WebRTC/MSE) → 4분할 레이아웃 적용·셀 스팬·비율 모드 → PTZ 패드/프리셋 동작 → 대시보드 저장 후 새로고침 시 복원 → 권한 없는 사용자 PTZ 미표시/403.
- 실카메라 없는 CI: go2rtc + 테스트용 RTSP(예: ffmpeg `testsrc` → mediamtx/rtsp-simple-server)로 합성 스트림 사용.

### 회귀
- P0 인증/RBAC/디자인 셸·기존 페이지 무영향 확인(권한맵 확장이 기존 가드 깨지 않는지).

---

## 13. 성능·보안 체크포인트

### 성능
- go2rtc **카메라당 1소스** 불변(라이브 N뷰어가 카메라 부하에 무관). 그리드=sub, 전체화면=main 강제.
- 무재인코딩(`copy`) 우선. 트랜스코딩은 명시적 옵트인.
- 비가시 타일/탭 연결 일시중단(IntersectionObserver/visibilitychange).
- 헬스 폴링은 go2rtc 상태 API 위주(직접 RTSP 재시도 최소화). 프로빙 동시성·타임아웃 제한.
- DB: FK 미사용·인덱스 설계(4절). 카메라 목록 N+1 회피(streams는 필요 시 일괄 로드).

### 보안
- 모든 P1 API `@login_required` + 권한 가드. 라이브/스냅샷/PTZ는 **카메라 scope**까지, 대시보드는 **ACL**까지 검증(프론트 신뢰 금지).
- 자격증명 Fernet 암호화·키 회전·로그/응답 마스킹. go2rtc 내부망 전용 + 프록시 강제(브라우저가 go2rtc 직접 접근 불가).
- SSRF 주의: 디스커버리/프로빙 host는 사설망 범위 검증(메타데이터 IP·loopback 차단 옵션), 포트 화이트리스트.
- 입력 검증: PTZ 값/속도 범위, layout JSON 스키마, IP/포트 형식.
- HTTPS 자체서명 카메라: `verify` 옵션 명시(기본 검증, 필요 시 사용자 동의 후 off).
- 패키지 최신 stable + 취약점 점검(PLAN 11절).

---

## 14. 미해결 질문 / 결정 필요 사항

1. **P0 스켈레톤 범위**: `cameras`/`streams`/`dashboards`가 P0에서 어디까지 생성됐는가? → 4.8을 CREATE/ALTER로 확정.
2. **라이브 인증 방식**: 라이브 WS/스냅샷에 access JWT 재사용 vs 별도 short-lived `live` scoped token? (브라우저 WS 헤더 제약·보안 트레이드오프) → 토큰 정책 확정 필요.
3. **go2rtc 동기화 1차 경로**: REST API vs yaml 파일(+reload)? (가용성/원자성/평문 노출 면) → 1차 REST 권장하나 운영 합의 필요.
4. **WebRTC 외부망 전략**: 호스트 네트워크/공인 ICE 후보 vs TURN 운영? (단일 온프레미스 + 외부접속 요건) → 네트워크 토폴로지 확정.
5. **H.265 sub 정책**: WebRTC 비호환 시 자동 트랜스코딩 허용 한도(성능 vs 호환) → 기본 off + 경고로 제안.
6. **신규 카메라 권한 기본값**: 카메라 추가 시 기존 user들의 `camera_scope`에 자동 view 부여 vs 기본 deny(admin만)? → 운영 정책 결정.
7. **PTZ 프리셋 저장 위치**: 카메라 펌웨어 신뢰 vs `ptz_presets` 동기화 강제? → 1차 카메라 신뢰 + 라벨 캐시 제안.
8. **상태 푸시 채널**: 신규 WebSocket 게이트웨이를 P1에서 도입(P3~P5 공용) vs SSE 임시? → 공용 WS 권장.
9. **디스커버리 SSRF 정책**: 프로빙 대상 IP 범위 제한(사설망 only/화이트리스트)을 강제할지 → 보안 기본값 결정.

### 14.1 구현 시 채택한 결정 (2026-06-05, P1 구현)
- **1. P0 스켈레톤**: P0가 `cameras`/`streams`/`dashboards` 최소 스켈레톤을 생성 → **`migrations/0001_phase1.sql` 가 빈 P0 테이블 DROP 후 풀 P1 스키마로 재생성** + `dashboard_acl`/`ptz_presets` CREATE. 모델도 풀 스키마로 확장(create_all=테스트 SQLite, init SQL=docker 일치).
- **2. 라이브 인증**: P0 **access JWT 재사용**(별도 live 토큰 없음). WS 미사용으로 헤더/쿼리 둘 다 허용(`Authorization` 또는 `?access_token=`, `<video>` 제약 대응). scoped monitor 토큰은 P5.
- **3. go2rtc 동기화**: **REST 1차**(`PUT/DELETE /api/streams`), 자격증명 런타임 복호화 주입(DB엔 자리표시자). yaml은 부팅 시드.
- **4/6.4 라이브 전송**: WS(MSE) 대신 **WebRTC(SDP POST 프록시) → fMP4 HTTP 스트림 폴백**(`/live/mp4`, Flask WS 불필요·헤드리스 검증 가능). 풀 MSE-WS/HLS는 후속.
- **6. 신규 카메라 권한**: **기본 deny**(admin/superuser만). 비-admin은 `camera_scope[uuid|*]` 명시 부여 필요(`PermissionService.has_camera_scope`/`can_ptz`).
- **7. PTZ 프리셋**: 카메라 펌웨어 신뢰 + `ptz_presets` 라벨 캐시.
- **8. 상태 푸시**: P1은 **프론트 폴링**(TanStack Query `refetchInterval`)으로 헬스 갱신 + Celery `camera_health_check`(30s). 공용 WS 게이트웨이는 후속(P3+).
- **9. SSRF**: `server/util/net.py::validate_probe_host` — loopback/link-local/메타데이터(169.254.169.254)/멀티캐스트 차단, 사설+공인 LAN 허용.
- **5. H.265 sub**: go2rtc `#video=copy` 기본(무재인코딩). 자동 트랜스코딩 미적용(후속, 경고와 함께 옵트인).

### 14.2 검증 메모
실카메라 부재 → 드라이버 파싱은 **픽스처 unit 테스트**(ISAPI/SUNAPI XML·CGI), 라이브 미디어는 **go2rtc `exec:ffmpeg` 합성 테스트 패턴**으로 프록시·스냅샷 경로를 e2e 검증. ONVIF/WS-Discovery는 구조 검증(목) + 컨테이너 import. **backend pytest 80 passed**, 프론트 `tsc`/`vite build` 무에러.
