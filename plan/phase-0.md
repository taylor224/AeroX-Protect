# Phase 0 — 기반(Scaffold)

> 마스터 플랜 [`../PLAN.md`](../PLAN.md) 와 100% 일관. 본 문서는 P1~P6 가 그 위에서 동작하는 토대(저장소·Docker·JWT/RBAC·핵심 모델·디자인 셸)를 **바로 구현 착수 가능한 수준**으로 정의한다. 레퍼런스 패턴은 `../../ams-front` 를 그대로 따른다(JS → TS 이식).

---

## 1. 목표 & 성공 기준(DoD)

**목표**: 네임스페이스 `axp` 의 전체 저장소 골격을 세우고, Docker Compose 한 방으로 모든 서비스(`axp-mysql · axp-redis · axp-go2rtc · axp-backend · axp-worker · axp-detector · axp-frontend`)가 기동하며, JWT 인증·RBAC 가 동작하고, Tesla 미니멀 디자인 셸로 로그인 → 보호 라우트 진입까지 시연 가능한 상태.

**완료 기준(Definition of Done)**
1. `docker compose up` 으로 7개 서비스가 전부 healthy 가 된다. `axp-backend:GET /api/v1/healthz` 가 `{"status":"success"}` 200 반환.
2. `poetry run migrate` 가 빈 DB(`axp` 스키마)에 모든 P0 테이블 + P1~P6 스켈레톤 테이블을 생성한다.
3. `poetry run seed-admin` (또는 부트스트랩 env) 로 최초 `admin` 계정이 1회 생성된다(Argon2 해시).
4. JWT 흐름 동작:
   - `POST /api/v1/auth/login` → access(15m, body) + refresh(14d, httpOnly 쿠키) 발급.
   - `GET /api/v1/auth/me` → Bearer access 로 본인 정보 반환.
   - `POST /api/v1/auth/refresh` → refresh 회전(이전 jti denylist 등록, 새 access+refresh 발급).
   - `POST /api/v1/auth/logout` → 현재 access·refresh jti denylist 등록, 쿠키 삭제.
   - 만료된/위조된/denylist 된 토큰은 401, 권한 부족은 403.
5. RBAC 동작: `@login_required` + `@permission_required('cameras','read')` 가 권한맵(JSON) 기준으로 통과/차단. `admin` 은 전권, `user` 는 부여된 권한만.
6. 브루트포스 방어: 동일 `login_id` 30분 내 5회 실패 시 계정 잠금(`locked_until`) + `audit_logs` 기록.
7. 프론트: `/auth/login` 페이지(순백 카드 + `#3E6AE1` CTA, 다크 캔버스 배경) → 로그인 성공 시 앱 셸(좌측 순백 사이드바 + 상단바 + 콘텐츠)로 진입. 새로고침 후에도 세션 유지(silent refresh). ko/en 토글, 토스트 동작.
8. 401 응답 시 axios 인터셉터가 1회 자동 refresh 후 원요청 재시도, refresh 실패 시 `/auth/login` 리다이렉트.
9. 모든 P0 백엔드 기능에 대한 pytest 통과(아래 12절), 프론트 빌드(`npm run build`) 무에러.

---

## 2. 범위 (In-scope / Out-of-scope)

### In-scope
- 저장소 디렉터리 구조 전체 생성(`server/`, `frontend/`, `worker/`, `go2rtc/`, `migrations/`, `docker-compose.yml`).
- `config.py`, 환경변수 체계, 로깅, Sentry 초기화, `ResponseBuilder`, 예외 체계(`server/exception.py`).
- 공통 Base 모델: Snowflake ID, soft delete(`deleted_at`), 감사(`created_by_id`/`last_updated_by_id`), 타임스탬프(UTC 저장), `to_dict` 컨벤션, 페이지네이션 mixin.
- DB 부트스트랩 + `poetry run migrate`(ams `server/command.py` 패턴) + 마이그레이션 SQL 디렉터리(`migrations/`).
- 인증 도메인 완전 구현: `users`, `roles`, `permissions`, `refresh_tokens`(또는 Redis jti), `audit_logs`. JWT(PyJWT) access+rotating refresh, Argon2, 브루트포스 방어, Redis jti denylist.
- RBAC: `@login_required` / `@permission_required(resource, action)` 데코레이터, `admin`/`user` 역할, 권한맵 스키마.
- P1~P6 도메인 모델 **스켈레톤**(최소 컬럼 + 감사/soft delete): `cameras`, `streams`, `disks`, `storage_policies`, `dashboards`, `settings`.
- 공통 계약: 상태 코드/에러 코드 표준, 페이지네이션 파라미터(`page/items_per_page/sort/order/q`), 페이지네이션 응답 포맷.
- 프론트 기반: Vite7+TS, Tailwind+Radix(shadcn) + DESIGN.md → CSS 변수 디자인 토큰, 앱 셸(레이아웃/사이드바/상단바), 로그인 페이지, JWT AuthContext, ProtectedRoute, axios 클라이언트(인터셉터+자동 refresh), TanStack Query, i18n(ko/en, react-intl), 토스트(sonner).
- 7개 Docker Compose 서비스 정의(포트·볼륨·환경변수·의존관계·healthcheck) + 각 서비스 Dockerfile.

### Out-of-scope (후속 Phase)
- 실제 카메라 연동/디스커버리/프로빙, RTSP, PTZ → **P1**.
- go2rtc **동적 설정 생성**, 라이브뷰 WebRTC/MSE 재생 → P1(P0 는 go2rtc 컨테이너 기동 + 기본 설정 파일만).
- 녹화/ffmpeg 레코더/세그먼트 인덱싱/스토리지 정책 **로직** → P2(P0 는 모델 스켈레톤만).
- 이벤트/스케줄/AI/규칙엔진/모니터 페어링/알림 → P3~P5(P0 는 토큰 audience 정의·자리만).
- scoped 토큰(monitor/node/api) **발급 엔드포인트** → 해당 Phase(P0 는 토큰 구조에 `aud`/`scope` 클레임 자리만 마련).
- 데이터그리드 서버사이드 페이지네이션 **공통 컴포넌트**의 실사용 화면 → 각 Phase(P0 는 래퍼·계약만).

---

## 3. 선행 의존성

- 외부 선행: 없음(P0 가 최초 Phase). Docker / Docker Compose v2, Node 20+, Python 3.13, Poetry 설치 환경.
- 레퍼런스 일독 필수: `../PLAN.md`(전체), `../DESIGN.md`(디자인 토큰), `../../ams-front/CLAUDE.md`(컨벤션), 그리고 본 문서가 인용한 ams 파일들.
- 확정 결정사항(PLAN.md §2): 네임스페이스 `axp`, go2rtc, 단일 Compose, JWT 일원화, React18+Vite7+TS, 반응형 PWA.

---

## 4. 데이터 모델 (테이블·컬럼·타입·인덱스 / 마이그레이션 SQL 스케치)

### 4.0 공통 규칙 (전 테이블 적용)
- **DB/스키마**: MySQL 8, 단일 전용 스키마 `axp`, charset `utf8mb4`, collation `utf8mb4_unicode_ci`, 엔진 InnoDB. 전용 DB 이므로 테이블 prefix 없음.
- **PK**: `id BIGINT UNSIGNED` — **Snowflake ID**(애플리케이션 생성, `SNOWFLAKE_INSTANCE` env). autoincrement 미사용(분산·머지 안전). 로그성 테이블(`audit_logs`)도 Snowflake.
- **외부 식별자**: 사용자 노출/URL 용 `uuid CHAR(32)`(uuid4 hyphenless) 보조 인덱스. (ams `Member.uuid` 패턴)
- **감사 컬럼**(공통 mixin `AuditMixin`): `created_by_id BIGINT NULL`, `last_updated_by_id BIGINT NULL` (FK 미설정 — 성능상 논리참조만, PLAN §11 "불필요 FK 자제").
- **타임스탬프**: `created_at DATETIME(3) NOT NULL`, `updated_at DATETIME(3) NOT NULL` — **UTC `DATETIME(3)`(밀리초) 저장**(PLAN §12.1: 저장 UTC `DATETIME(3)`, 표시 KST). 앱에서 `datetime.now(timezone.utc)` 로 채움(server_default 는 `CURRENT_TIMESTAMP(3)`, MySQL 컨테이너 TZ=UTC 로 통일).
- **soft delete**: `deleted_at DATETIME(3) NULL`, 인덱스 포함. 조회는 항상 `deleted_at IS NULL`.
- **시간 정책**: 전 계층 **UTC `DATETIME(3)` 저장 / API 직렬화 epoch ms·ISO / 표시 KST**(PLAN §12.1). 컨테이너(`axp-mysql`, `axp-backend`)는 `TZ=UTC`. 모든 시각 컬럼(저빈도·고빈도 공통)은 `events`↔`recordings`↔`segments`↔`detections` 조인·범위질의 일관성을 위해 동일 `DATETIME(3)` 타입. 녹화 타임스탬프(P2+) 정확성을 위해 DB·내부 전부 UTC.
- **민감정보**: 카메라 자격증명 등은 `cryptography`(Fernet) 암호화 컬럼(`*_encrypted BLOB/TEXT`). P0 에서는 cameras 스켈레톤에 자리만.

공통 Base 정의(개념):
```python
# server/model/__init__.py — ams DataAccessLayer 그대로 + 공통 Mixin 추가
class TimestampMixin:
    created_at = Column(DateTime(fsp=3), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(fsp=3), nullable=False, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))
    deleted_at = Column(DateTime(fsp=3), nullable=True, index=True)

class AuditMixin:
    created_by_id = Column(BigInteger, nullable=True)
    last_updated_by_id = Column(BigInteger, nullable=True)

class SnowflakeMixin:
    id = Column(BigInteger, primary_key=True, autoincrement=False, default=generate_snowflake_id)
```
- `KST = timezone(timedelta(hours=9))`, `UTC = timezone.utc` 를 `server/model/__init__.py` 에 정의(ams 의 `KST` 위치와 동일).
- `generate_snowflake_id()` 는 `server/util/snowflake.py` (워커 ID = `config.SNOWFLAKE_INSTANCE`).

### 4.1 `users` (인증 주체)
| 컬럼 | 타입 | 제약/기본 | 설명 |
|---|---|---|---|
| id | BIGINT UNSIGNED | PK, Snowflake | |
| uuid | CHAR(32) | UNIQUE, INDEX | 외부 노출 ID |
| login_id | VARCHAR(190) | UNIQUE, INDEX, NOT NULL | 로그인 아이디(이메일 허용) |
| password | VARCHAR(255) | NOT NULL | Argon2id 해시 |
| name | VARCHAR(120) | NOT NULL | 표시 이름 |
| email | VARCHAR(190) | NULL, INDEX | |
| phone_number | VARCHAR(40) | NULL | 비밀번호 재설정 본인확인용 |
| role_id | BIGINT UNSIGNED | NOT NULL, INDEX | → `roles.id`(논리참조) |
| permissions | JSON | NOT NULL, default `{}` | 사용자 개별 권한 오버라이드(역할 권한과 병합) |
| language | VARCHAR(10) | default `'ko'` | ko/en |
| is_active | TINYINT(1) | default 1 | 비활성 토글 |
| failed_login_count | INT | default 0 | 브루트포스 카운터 |
| locked_until | DATETIME(3) | NULL | 계정 잠금 만료(UTC) |
| last_login_at | DATETIME(3) | NULL | |
| token_version | INT | NOT NULL, default 0 | **전 토큰 일괄 무효화**용(비번 변경·강제 로그아웃 시 +1) |
| created_at / updated_at / deleted_at | DATETIME(3) | | 공통 |
| created_by_id / last_updated_by_id | BIGINT | NULL | 공통 감사 |

인덱스: `uq_users_login_id(login_id)`, `uq_users_uuid(uuid)`, `idx_users_role_id`, `idx_users_deleted_at`.

> **권한 해석 규칙**: 유효 권한 = `roles.permissions`(역할 기본) 을 베이스로 `users.permissions`(개별 오버라이드)를 deep-merge. `admin` 역할은 `permissions = {"*": ["*"]}`(전권 와일드카드). 토큰에는 `user_id`, `role`, `token_version` 만 싣고 세부 권한은 매 요청 서버에서 해석(PLAN §8).

### 4.2 `roles`
| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| id | BIGINT UNSIGNED | PK, Snowflake | |
| name | VARCHAR(50) | UNIQUE, INDEX, NOT NULL | `admin` / `user` (확장 가능) |
| display_name | VARCHAR(100) | NOT NULL | "관리자" / "사용자" |
| description | VARCHAR(500) | NULL | |
| permissions | JSON | NOT NULL, default `{}` | 역할 기본 권한맵 |
| is_system | TINYINT(1) | default 0 | 시스템 기본 역할(삭제 불가) |
| created_at / updated_at / deleted_at / 감사 | | | 공통 |

시드: `admin`(`{"*":["*"]}`, is_system=1), `user`(`{}`, is_system=1).

### 4.3 `permissions` (권한 정의 카탈로그 — 화면/검증용 메타)
> 권한 **부여**는 `roles.permissions` / `users.permissions` JSON 으로 한다(빠른 해석). 본 테이블은 "어떤 권한이 존재하는가"를 정의해 프론트 권한 편집 UI·서버 검증에 쓰는 **카탈로그**.

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| id | BIGINT UNSIGNED | PK, Snowflake | |
| resource | VARCHAR(50) | NOT NULL, INDEX | PLAN §12.2 전체 자원: `cameras`,`live`,`ptz`,`streams`,`dashboards`,`recordings`,`playback`,`clips`,`storage`,`retention`,`events`,`policies`,`schedules`,`timelapse`,`detections`,`zones`,`triggers`,`ai`,`ai_nodes`,`rules`,`targets`,`monitors`,`notifications`,`api_tokens`,`users`,`roles`,`audit`,`settings` (+ per-scope `camera_scope`/`dashboard_scope`) |
| action | VARCHAR(50) | NOT NULL | `read`,`create`,`update`,`delete`,`discover`,`control`,`export`,`manage`,`share`,`cancel` 등 |
| description | VARCHAR(300) | NULL | |
| created_at / updated_at | | | (soft delete 불필요) |

유니크: `uq_permissions_resource_action(resource, action)`.
권한맵 JSON 포맷: `{"cameras": ["read","create"], "live": ["read"], "dashboards": ["read","update"]}`.

### 4.4 `refresh_tokens` (회전·재사용 탐지)
> Redis 의 jti **denylist** 와 병행. 단기 access 검증은 Redis 만으로 충분하지만, refresh 회전 **재사용 탐지**(도난 감지)와 감사를 위해 DB 에도 활성 refresh 패밀리를 둔다.

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| id | BIGINT UNSIGNED | PK, Snowflake | |
| user_id | BIGINT UNSIGNED | NOT NULL, INDEX | |
| jti | CHAR(36) | UNIQUE, INDEX, NOT NULL | refresh 토큰 jti(uuid4) |
| family_id | CHAR(36) | INDEX, NOT NULL | 회전 체인 식별(재사용 탐지 시 패밀리 전체 폐기) |
| issued_at | DATETIME(3) | NOT NULL | UTC |
| expires_at | DATETIME(3) | NOT NULL, INDEX | UTC |
| rotated_to_jti | CHAR(36) | NULL | 회전 후 다음 jti(이전 토큰 재사용 감지용) |
| revoked_at | DATETIME(3) | NULL | |
| user_agent | VARCHAR(255) | NULL | |
| ip | VARCHAR(64) | NULL | |
| created_at | DATETIME(3) | NOT NULL | |

인덱스: `uq_refresh_jti(jti)`, `idx_refresh_user(user_id)`, `idx_refresh_family(family_id)`, `idx_refresh_expires(expires_at)`.
정리: 만료 토큰은 Celery beat 태스크 `cleanup_expired_tokens`(매일 03:00 UTC)로 삭제.

### 4.5 `audit_logs` (보안·감사 + 접근 로그 통합)
| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| id | BIGINT UNSIGNED | PK, Snowflake | |
| action | VARCHAR(80) | NOT NULL, INDEX | `login_success`,`login_failed`,`logout`,`token_refresh`,`token_reuse_detected`,`account_locked`,`password_changed`,`permission_denied`,`user_created`,`user_updated`,`role_updated` 등 |
| target | VARCHAR(190) | NULL, INDEX | 대상(login_id, user uuid, resource:id 등) |
| user_id | BIGINT UNSIGNED | NULL, INDEX | 행위자(비로그인 실패는 NULL) |
| method | VARCHAR(10) | NULL | HTTP method(접근 로그) |
| path | VARCHAR(500) | NULL | 요청 경로 |
| ip | VARCHAR(64) | NULL | |
| user_agent | VARCHAR(255) | NULL | |
| detail | JSON | NULL | 부가 정보 |
| created_at | DATETIME(3) | NOT NULL, INDEX | UTC |

인덱스: `idx_audit_action(action)`, `idx_audit_user(user_id)`, `idx_audit_target(target)`, `idx_audit_created(created_at)`.
> ams 의 `MemberAuditLog` + `MemberAccessLog` 를 하나로 통합. 브루트포스 카운트는 `users.failed_login_count` 를 우선 사용하되, 분석용으로 `login_failed` 도 적재.

### 4.6 P1~P6 스켈레톤 (최소 컬럼 + 공통 mixin만, 로직은 해당 Phase)
> 목적: 마이그레이션·FK 방향·`to_dict` 계약을 P0 에서 고정해 후속 Phase 충돌 방지. 컬럼은 PLAN §7 개요와 일치하는 **최소셋**.

**`cameras`** (P1 확장):
| 컬럼 | 타입 | 설명 |
|---|---|---|
| id BIGINT PK / uuid CHAR(32) UNIQUE | | |
| name VARCHAR(120) NOT NULL | | |
| vendor VARCHAR(40) NULL | | hanwha/hikvision/onvif |
| model VARCHAR(120) NULL | | |
| driver VARCHAR(40) NULL | | sunapi/isapi/onvif |
| host VARCHAR(190) NULL / port INT NULL | | |
| credentials_encrypted TEXT NULL | | Fernet 암호화 |
| capabilities JSON default `{}` | | 프로빙 결과 |
| status VARCHAR(20) default `'unknown'` | | online/offline/error/unknown |
| enabled TINYINT(1) default 1 | | |
| 공통 mixin | | created/updated/deleted/감사 |

**`streams`** (P1):
| 컬럼 | 타입 | 설명 |
|---|---|---|
| id / camera_id BIGINT INDEX | | 논리참조 |
| role VARCHAR(10) | | main/sub |
| codec VARCHAR(20) NULL / resolution VARCHAR(20) NULL / fps INT NULL | | |
| go2rtc_name VARCHAR(120) NULL | | go2rtc 스트림 키 |
| 공통 mixin | | |

**`disks`** (P2):
| 컬럼 | 타입 | 설명 |
|---|---|---|
| id / uuid | | |
| mount_path VARCHAR(255) UNIQUE | | |
| capacity_bytes BIGINT NULL / reserved_free_bytes BIGINT default 0 | | |
| role VARCHAR(20) | | system/cache/record |
| enabled TINYINT(1) default 1 | | |
| 공통 mixin | | |

**`storage_policies`** (P2): `id`, `name`, `strategy VARCHAR(20)`(least_used/per_camera/round_robin), `config JSON default {}`, `enabled`, 공통 mixin.

**`dashboards`** (P1/P5): `id`, `uuid`, `name VARCHAR(120)`, `layout JSON default {}`, `acl JSON default {}`(뷰/편집 권한), `is_default TINYINT default 0`, 공통 mixin.

**`settings`** (전역 KV): `id`, `key VARCHAR(120) UNIQUE INDEX`, `value JSON`, `description VARCHAR(300)`, 공통 timestamp(soft delete 불필요). 시드: `gpu_enabled=false`, `timezone="Asia/Seoul"`, `retention_default_days=30`.
> **주의(PLAN §12.1)**: `settings.gpu_enabled` 시드는 **부트스트랩 placeholder**일 뿐이며, 전역 GPU on/off 권위는 **P4 `ai_settings.gpu_enabled`(전역 행)** 이다(P4 도입 시 이관, 중복 회피).

### 4.7 마이그레이션 전략 & SQL 스케치
- **방식**: ams 패턴 그대로 — SQLAlchemy 모델이 단일 진실, `poetry run migrate` 가 `db.create_all()` 로 생성(`server/command.py`). 추가로 운영 변경 추적용 SQL 을 `migrations/` 에 수기 보관(PLAN §11 "모델 변경 시 MySQL 기준 SQL 제공").
- `migrations/0000_init.sql` : 스키마 생성 + 모든 P0/스켈레톤 테이블 + 시드(`roles`, `permissions`, `settings`).

```sql
-- migrations/0000_init.sql (발췌)
CREATE DATABASE IF NOT EXISTS `axp`
  DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE `axp`;

CREATE TABLE `roles` (
  `id` BIGINT UNSIGNED NOT NULL,
  `name` VARCHAR(50) NOT NULL,
  `display_name` VARCHAR(100) NOT NULL,
  `description` VARCHAR(500) NULL,
  `permissions` JSON NOT NULL,
  `is_system` TINYINT(1) NOT NULL DEFAULT 0,
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  `deleted_at` DATETIME(3) NULL,
  `created_by_id` BIGINT NULL,
  `last_updated_by_id` BIGINT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_roles_name` (`name`),
  KEY `idx_roles_deleted_at` (`deleted_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `users` (
  `id` BIGINT UNSIGNED NOT NULL,
  `uuid` CHAR(32) NOT NULL,
  `login_id` VARCHAR(190) NOT NULL,
  `password` VARCHAR(255) NOT NULL,
  `name` VARCHAR(120) NOT NULL,
  `email` VARCHAR(190) NULL,
  `phone_number` VARCHAR(40) NULL,
  `role_id` BIGINT UNSIGNED NOT NULL,
  `permissions` JSON NOT NULL,
  `language` VARCHAR(10) NOT NULL DEFAULT 'ko',
  `is_active` TINYINT(1) NOT NULL DEFAULT 1,
  `failed_login_count` INT NOT NULL DEFAULT 0,
  `locked_until` DATETIME(3) NULL,
  `last_login_at` DATETIME(3) NULL,
  `token_version` INT NOT NULL DEFAULT 0,
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  `deleted_at` DATETIME(3) NULL,
  `created_by_id` BIGINT NULL,
  `last_updated_by_id` BIGINT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_users_login_id` (`login_id`),
  UNIQUE KEY `uq_users_uuid` (`uuid`),
  KEY `idx_users_role_id` (`role_id`),
  KEY `idx_users_deleted_at` (`deleted_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `permissions` (
  `id` BIGINT UNSIGNED NOT NULL,
  `resource` VARCHAR(50) NOT NULL,
  `action` VARCHAR(50) NOT NULL,
  `description` VARCHAR(300) NULL,
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_permissions_resource_action` (`resource`, `action`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `refresh_tokens` (
  `id` BIGINT UNSIGNED NOT NULL,
  `user_id` BIGINT UNSIGNED NOT NULL,
  `jti` CHAR(36) NOT NULL,
  `family_id` CHAR(36) NOT NULL,
  `issued_at` DATETIME(3) NOT NULL,
  `expires_at` DATETIME(3) NOT NULL,
  `rotated_to_jti` CHAR(36) NULL,
  `revoked_at` DATETIME(3) NULL,
  `user_agent` VARCHAR(255) NULL,
  `ip` VARCHAR(64) NULL,
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_refresh_jti` (`jti`),
  KEY `idx_refresh_user` (`user_id`),
  KEY `idx_refresh_family` (`family_id`),
  KEY `idx_refresh_expires` (`expires_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `audit_logs` (
  `id` BIGINT UNSIGNED NOT NULL,
  `action` VARCHAR(80) NOT NULL,
  `target` VARCHAR(190) NULL,
  `user_id` BIGINT UNSIGNED NULL,
  `method` VARCHAR(10) NULL,
  `path` VARCHAR(500) NULL,
  `ip` VARCHAR(64) NULL,
  `user_agent` VARCHAR(255) NULL,
  `detail` JSON NULL,
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (`id`),
  KEY `idx_audit_action` (`action`),
  KEY `idx_audit_user` (`user_id`),
  KEY `idx_audit_target` (`target`),
  KEY `idx_audit_created` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 시드
INSERT INTO `roles` (`id`,`name`,`display_name`,`permissions`,`is_system`,`created_at`,`updated_at`)
VALUES
 (1,'admin','관리자','{"*":["*"]}',1,UTC_TIMESTAMP(),UTC_TIMESTAMP()),
 (2,'user','사용자','{}',1,UTC_TIMESTAMP(),UTC_TIMESTAMP());

INSERT INTO `settings` (`id`,`key`,`value`,`created_at`,`updated_at`) VALUES
 (1,'gpu_enabled','false',UTC_TIMESTAMP(),UTC_TIMESTAMP()),
 (2,'timezone','"Asia/Seoul"',UTC_TIMESTAMP(),UTC_TIMESTAMP()),
 (3,'retention_default_days','30',UTC_TIMESTAMP(),UTC_TIMESTAMP());
-- cameras/streams/disks/storage_policies/dashboards/settings 스켈레톤 CREATE 는 동일 패턴으로 포함
```
> 위 시드의 정수 PK(1,2,…)는 부트스트랩 편의용 예약값. 런타임 생성 레코드는 Snowflake. (시드/Snowflake 범위 분리: 시드는 1~999 예약)

---

## 5. 백엔드 설계

### 5.1 레이어 구성 (ams MVC 그대로)
| 레이어 | 경로 | 역할 |
|---|---|---|
| View(Blueprint) | `server/view/api/` | 요청 파싱·데코레이터·`ResponseBuilder` 응답 |
| Controller | `server/controller/` | 비즈니스 로직, 예외 → 적절 응답 매핑 입력 |
| Model | `server/model/` | SQLAlchemy 2 모델 + 쿼리 classmethod |
| Service | `server/service/` | 도메인 서비스(토큰 발급/검증, 권한 해석) — P0: `token`, `auth` |
| Driver | `server/driver/` | 외부 연동(P0 없음, 디렉터리만 + `go2rtc` 자리) |
| Task | `server/task/list/` | Celery(P0: `cleanup_expired_tokens`) |
| Util | `server/util/` | `snowflake.py`, `tool.py`(safe_int 등 ams 이식), `pagination.py` |

P0 신규 파일:
- View: `server/view/api/auth.py`, `server/view/api/admin/user.py`, `server/view/api/admin/role.py`, `server/view/healthz.py`, `server/view/__init__.py`(blueprint 등록 — ams 패턴).
- Controller: `server/controller/auth.py`, `server/controller/user.py`, `server/controller/role.py`, `server/controller/audit_log.py`.
- Service: `server/service/token.py`(JWT 발급/검증/회전/denylist), `server/service/permission.py`(권한맵 병합·체크).
- Model: `server/model/user.py`, `role.py`, `permission.py`, `refresh_token.py`, `audit_log.py`, 스켈레톤들(`camera.py`, `stream.py`, `disk.py`, `storage_policy.py`, `dashboard.py`, `setting.py`).
- 데코레이터: `server/decorator.py`(`login_required`, `permission_required`, `roles_required`).
- 예외: `server/exception.py`. 앱: `server/__init__.py`, `config.py`, `server/command.py`, `server/__main__.py`.

### 5.2 인증 토큰 설계 (`server/service/token.py`)
- **라이브러리**: PyJWT(`HS256`, `config.JWT_SECRET`). flask-login **미사용**(ams 는 세션 기반이나 NVR 은 JWT 일원화 → `before_request` 에서 직접 토큰 해석 후 `flask.g.current_user` 주입).
- **access 클레임**: `{ "sub": <user_id>, "uuid": <uuid>, "role": "admin|user", "tv": <token_version>, "aud": "web", "iat", "exp"(+15m), "jti"(uuid4), "typ": "access" }`.
- **refresh 클레임**: `{ "sub", "aud": "web", "iat", "exp"(+14d), "jti", "fid": <family_id>, "typ": "refresh" }`.
- **scoped 토큰(후속 자리)**: `aud ∈ {"web","monitor","node","api"}`, monitor 토큰은 `scope: {"dashboards":[id], "actions":["read"]}` 클레임 추가(P5 에서 발급, P0 는 검증기에 aud 분기 자리만).
- **denylist(Redis)**: 로그아웃·강제만료 시 `axp:denylist:<jti> = 1`, TTL = 토큰 잔여 만료. access 검증 시 jti denylist 조회 + `tv == users.token_version` 확인(불일치 = 전역 무효).
- **refresh 회전**: refresh 검증 → 해당 jti 가 `refresh_tokens` 에 활성(미회전·미폐기)인지 확인 → 새 access+refresh 발급 + 이전 row `rotated_to_jti`/`revoked_at` 세팅 + 이전 jti denylist 등록. **재사용 탐지**: 이미 `rotated_to_jti` 가 채워진(=이미 회전된) refresh 가 다시 오면 도난으로 간주 → `family_id` 전체 폐기 + denylist + `token_reuse_detected` 감사.

### 5.3 API 표
모든 경로 `/api/v1/` 프리픽스. 권한 표기: `public`(무인증), `auth`(로그인만), `perm:<resource>:<action>`(권한 필요), `admin`(admin 역할).

| Method | Path | 권한 | 요청 | 응답(요지) |
|---|---|---|---|---|
| GET | `/api/v1/healthz` | public | — | `{status:success, data:{db, redis, version}}` |
| POST | `/api/v1/auth/login` | public | `{login_id, password}` | access(body) + refresh(쿠키) + user |
| POST | `/api/v1/auth/refresh` | public(쿠키/바디 refresh) | `{}`(웹: 쿠키) 또는 `{refresh_token}` | 새 access + refresh 회전 |
| POST | `/api/v1/auth/logout` | auth | `{}` | jti denylist, 쿠키 삭제 |
| GET | `/api/v1/auth/me` | auth | — | 본인 user + 유효권한 + 메뉴 |
| POST | `/api/v1/auth/change_password` | auth | `{previous_password, password}` | success / 400 |
| POST | `/api/v1/auth/language` | auth | `{language:'ko'|'en'}` | `{language}` |
| GET | `/api/v1/admin/users` | perm:users:read | `?page&items_per_page&sort&order&q` | 페이지네이션 user 목록 |
| POST | `/api/v1/admin/users` | perm:users:create | `{login_id,password,name,email,phone_number,role,permissions}` | 생성 user |
| GET | `/api/v1/admin/users/<uuid>` | perm:users:read | — | user 상세 |
| POST | `/api/v1/admin/users/<uuid>` | perm:users:update | `{name,email,role,permissions,is_active,...}` | 수정 user |
| DELETE | `/api/v1/admin/users/<uuid>` | perm:users:delete | — | success(soft delete) |
| POST | `/api/v1/admin/users/<uuid>/reset_password` | perm:users:update | `{password}` | success(+token_version++) |
| POST | `/api/v1/admin/users/<uuid>/unlock` | perm:users:update | — | success(잠금 해제) |
| GET | `/api/v1/admin/roles` | perm:users:read | — | role 목록 |
| POST | `/api/v1/admin/roles` | admin | `{name,display_name,permissions}` | 생성 |
| POST | `/api/v1/admin/roles/<id>` | admin | `{display_name,permissions}` | 수정(시스템 역할 권한 편집은 허용/이름변경 금지) |
| GET | `/api/v1/admin/permissions` | perm:users:read | — | 권한 카탈로그(프론트 권한편집 UI) |
| GET | `/api/v1/admin/audit_logs` | admin | `?page&items_per_page&action&q&from&to` | 감사로그 페이지네이션 |

**요청/응답 JSON 예시**

`POST /api/v1/auth/login`
```json
// req
{ "login_id": "admin", "password": "••••••••" }
// res 200  (refresh 는 Set-Cookie: axp_refresh=...; HttpOnly; Secure; SameSite=Strict; Path=/api/v1/auth)
{
  "status": "success",
  "data": {
    "access_token": "eyJhbGciOi...",
    "token_type": "Bearer",
    "expires_in": 900,
    "user": { "uuid": "8f...", "login_id": "admin", "name": "관리자",
              "role": "admin", "language": "ko",
              "permissions": {"*": ["*"]} }
  },
  "time": "2026-06-05T12:00:00+09:00"
}
// res 400 (실패)
{ "status": "bad_request", "message": "invalid_credentials", "time": "..." }
// res 429 (잠금)
{ "status": "too_many_requests", "message": "account_locked", "time": "..." }
```

`POST /api/v1/auth/refresh` → `200 { status:success, data:{ access_token, expires_in, token_type } }` + 새 refresh 쿠키. 실패 시 `401 { status:no_permission|forbidden, message:"invalid_refresh" }`(재사용 탐지 시 패밀리 폐기).

`GET /api/v1/auth/me`
```json
{ "status":"success", "data": {
  "user": { "uuid":"...","login_id":"admin","name":"관리자","email":null,
            "role":"admin","language":"ko" },
  "permissions": {"*":["*"]},
  "menus": [ {"title":"menu.live","icon":"video","path":"/live"}, ... ]
}, "time":"..." }
```

페이지네이션 목록 응답(공통 계약):
```json
{ "status":"success", "data": {
  "items": [ {...}, {...} ],
  "pagination": { "page":1, "items_per_page":20, "total":134, "total_pages":7 }
}, "time":"..." }
```

### 5.4 controller/service/driver/task 구성
- **`AuthController`**: `login(login_id, password, ip, ua)` → 검증(Argon2)·잠금·브루트포스·감사 → `TokenService.issue_pair(user, aud='web')`. `refresh(token)`, `logout(access_jti, refresh_jti)`, `change_password(...)`, `me(user)`. (ams `AuthController` 구조 차용)
- **`TokenService`**: `issue_pair`, `verify_access`, `verify_refresh`, `rotate_refresh`, `revoke`(denylist), `revoke_all(user)`(token_version++). Redis 클라이언트는 `config.REDIS_URI`.
- **`PermissionService`**: `effective_permissions(user)`(role+user 병합), `has(user, resource, action)`(와일드카드 `*` 처리).
- **`UserController` / `RoleController`**: CRUD + 페이지네이션(ams `get_list_by_type` 패턴: `count(), .limit().offset()`).
- **`AuditLogController`**: `record(action, ...)`, `get_list(...)`.
- **Driver**: P0 없음. `server/driver/__init__.py` + `go2rtc/` 자리만(P1 에서 `Go2rtcDriver`).
- **Task**: `server/task/list/maintenance.py::cleanup_expired_tokens`(beat 매일 03:00 UTC), `server/task/celery.py`·`celeryconfig.py` ams 패턴 이식(`app = Celery('axp', ...)`, `celery_use_db()` 데코레이터, `enable_utc=True`, `timezone='UTC'`).

### 5.5 설정·로깅·예외
- **`config.py`** (모든 시크릿 env, ams 패턴):
  ```python
  PROJECT_ENV = os.getenv('PROJECT_ENV')                 # development 시 디버그·비-secure 쿠키
  DATABASE_URI = 'mysql+pymysql://{id}:{pw}@{host}/{db}'  # axp-mysql / axp
  REDIS_URI = 'redis://{host}:6379'
  JWT_SECRET = os.getenv('JWT_SECRET')
  JWT_ACCESS_TTL = int(os.getenv('JWT_ACCESS_TTL', '900'))      # 15m
  JWT_REFRESH_TTL = int(os.getenv('JWT_REFRESH_TTL', '1209600'))# 14d
  SECRET_KEY = os.getenv('SECRET_KEY')
  SENTRY_DSN = os.getenv('SENTRY_DSN')
  SNOWFLAKE_INSTANCE = int(os.getenv('SNOWFLAKE_INSTANCE', '1'))
  CREDENTIAL_ENC_KEY = os.getenv('CREDENTIAL_ENC_KEY')   # Fernet (카메라 자격증명, P1+)
  GO2RTC_URL = os.getenv('GO2RTC_URL', 'http://axp-go2rtc:1984')
  CORS_ALLOWED_ORIGINS = os.getenv('CORS_ALLOWED_ORIGINS', '*')
  BOOTSTRAP_ADMIN_ID / _PW / _NAME = os.getenv(...)      # 최초 admin 시드용(옵션)
  ```
- **로깅**: `logging.basicConfig` — `PROJECT_ENV=development` 시 DEBUG, 운영 INFO. 요청 로깅은 `@app.before_request` 에서 `AuditLogController` 로 접근 로그 적재(ams `AccessLogController` 패턴, 단 정적/healthz 제외).
- **Sentry**: `sentry_sdk.init(dsn, integrations=[FlaskIntegration(), SqlalchemyIntegration()], traces_sample_rate=...)` — ams 동일. Celery 는 `CeleryIntegration`.
- **앱 초기화(`server/__init__.py`)**: ams 미러 — `ProxyFix`, CORS(`/api/*`), `db.db_init(config.DATABASE_URI, BaseDB)`, `@app.teardown_request`(→ `db.session.remove()`), 커스텀 JSON 인코더(datetime → ISO), `@app.before_request`(JWT 해석 → `g.current_user`, 접근 로그). 마지막 줄 `import server.view`.
- **예외(`server/exception.py`)**: `RowNotFoundException`, `InvalidParameterException(value)`, `ConflictException`, `NoPermissionException`, `AuthenticationException`, `TokenReuseException`, `AccountLockedException`. View 에서 예외 → `ResponseBuilder` 매핑(`RowNotFound→not_found`, `InvalidParameter→bad_request`, `NoPermission→forbidden`, `Authentication→no_permission(401)`, `AccountLocked→too_many_requests`).
- **`ResponseBuilder`** (`server/view/response.py`): ams 그대로 — `success/bad_request/no_permission(401)/forbidden(403)/not_found/conflict/too_many_requests/internal_server_error`. `time` 은 KST ISO(표시용).

### 5.6 데코레이터 (`server/decorator.py`)
```python
@login_required            # g.current_user 존재 검증, 없으면 401(no_permission)
@roles_required(['admin']) # 역할 검사
@permission_required('cameras','read')  # PermissionService.has() 검사, 실패 403 + audit(permission_denied)
```
- `login_required` 는 `before_request` 에서 토큰을 이미 해석했으므로 `g.current_user` 유무만 확인(검증 자체는 토큰 서비스). access 만료/denylist/위조면 `g.current_user=None` → 401.

---

## 6. 인프라 (docker-compose 서비스·볼륨·네트워크·환경변수)

네트워크: 단일 브리지 `axp-net`. 모든 서비스 join. 외부 노출은 frontend/backend(reverse proxy)만 권장.

| 서비스 | 이미지/빌드 | 포트(host:container) | 볼륨 | 의존(condition) | 핵심 env |
|---|---|---|---|---|---|
| **axp-mysql** | `mysql:8.4` | `3306:3306`(내부 권장) | `axp-mysql-data:/var/lib/mysql`, `./migrations:/docker-entrypoint-initdb.d:ro` | — | `MYSQL_DATABASE=axp`, `MYSQL_USER/PASSWORD`, `MYSQL_ROOT_PASSWORD`, `TZ=UTC` |
| **axp-redis** | `redis:7.4-alpine` | `6379`(내부) | `axp-redis-data:/data` | — | `--appendonly yes` |
| **axp-go2rtc** | `alexxit/go2rtc:latest` | `1984:1984`(API), `8554:8554`(RTSP), `8555:8555/tcp+udp`(WebRTC) | `./go2rtc/go2rtc.yaml:/config/go2rtc.yaml` | — | `TZ=UTC` |
| **axp-backend** | build `./server/Dockerfile`(uWSGI:10000) | `10000:10000`(내부; 프록시 뒤) | `axp-media:/media`(P2+ 공유), `./go2rtc:/go2rtc`(설정 생성, P1+) | mysql(healthy), redis(healthy) | `PROJECT_ENV`, `DATABASE_*`, `REDIS_URL=axp-redis`, `JWT_SECRET`, `SECRET_KEY`, `SENTRY_DSN`, `SNOWFLAKE_INSTANCE=1`, `CREDENTIAL_ENC_KEY`, `GO2RTC_URL`, `CORS_ALLOWED_ORIGINS` |
| **axp-worker** | build `./server/Dockerfile`(Celery 커맨드 override) | — | `axp-media:/media` | redis, mysql, backend | backend 와 동일 env, `SNOWFLAKE_INSTANCE=2`. command: `celery -A server.task.celery worker -B -l info`(beat 통합 또는 분리) |
| **axp-detector** | build `./worker/detector/Dockerfile`(FastAPI/YOLO) | `8099:8099`(내부) | `axp-media:/media:ro` | redis | `GPU_ENABLED=false`, `DETECTOR_BIND=0.0.0.0:8099`, (GPU 시 `deploy.resources.reservations.devices` NVIDIA) — P0 는 헬스 only stub |
| **axp-frontend** | build `./frontend/Dockerfile`(Vite build → serve/nginx :3000) | `3000:3000` | — | backend | `VITE_APP_API_URL=/api/v1`, `VITE_APP_NAME=axp`, `VITE_APP_VERSION` (빌드시 주입) |

- **healthcheck**: mysql(`mysqladmin ping`), redis(`redis-cli ping`), backend(`curl -f http://localhost:10000/api/v1/healthz`), go2rtc(`wget -q -O- http://localhost:1984/api`), detector(`curl -f .../healthz`), frontend(`wget -q -O- http://localhost:3000`). `depends_on: condition: service_healthy`.
- **볼륨**: `axp-mysql-data`, `axp-redis-data`, `axp-media`(P2 녹화 공유 — backend/worker/detector 공유, P0 는 정의만). 다중 HDD 풀(P2)은 `disks` 모델로 인덱싱하므로 Compose 에 추가 마운트(`/mnt/disk1` 등) 만 잡으면 됨.
- **Dockerfile(backend)**: ams `Dockerfile` 패턴(python:3.13-slim, poetry, uWSGI `--http-socket :10000 --module server:app`, non-root). ffmpeg 는 P2 에서 추가(`apt-get install ffmpeg`).
- **개발 모드**: `docker-compose.override.yml` 에 `PROJECT_ENV=development`, 소스 바인드 마운트, `flask run`/`vite dev`, `SESSION_COOKIE_SECURE` off.

---

## 7. 외부 연동·드라이버 (해당 시)

P0 에서 **실제 외부 연동 없음**(카메라/스피커/이메일/푸시는 P1+). 다만 토대만 마련:
- **go2rtc**: 컨테이너 기동 + 최소 `go2rtc/go2rtc.yaml`(빈 `streams: {}` + api/webrtc/rtsp 리스너). 동적 스트림 등록은 P1 `Go2rtcDriver`(REST `:1984/api`).
- **Redis**: 세션/denylist/Celery 브로커로 P0 부터 실사용.
- **Sentry**: P0 부터 backend·worker 에 적용.
- **드라이버 디렉터리 자리**: `server/driver/{onvif,isapi,sunapi,go2rtc,webhook,speaker,io,email,push}.py` 는 비어있는 모듈/인터페이스 stub 로 생성(후속 Phase 충돌 방지). P0 구현 없음.

---

## 8. 프론트엔드(TS) (디자인 토큰·앱 셸·인증 컨텍스트·라우팅·API 클라이언트·i18n)

### 8.1 스택·구조 (ams 미러, JS→TS)
- Vite7 + React18 + **TypeScript**(`.tsx`), `tsconfig.json`(`strict: true`), alias `@ → frontend/src/`.
- Tailwind + Radix(shadcn) `components/ui/`(ams 목록 이식: button/input/card/dialog/dropdown-menu/select/table/sonner/tooltip/sheet/separator/skeleton/switch/checkbox/...). shadcn 컴포넌트는 TS 로 작성.
- TanStack Query(서버상태) + TanStack Table(`components/data-grid/` 서버사이드 페이지네이션 래퍼) + react-intl(i18n) + sonner(토스트). dnd-kit·차트는 후속.
- 디렉터리: `src/{app, auth, providers, routing, layouts, pages, components/ui, components/data-grid, i18n, lib, config, types}`.

### 8.2 디자인 토큰 (DESIGN.md → CSS 변수, `src/styles/globals.css` + `tailwind.config.ts`)
> Tesla 미니멀: 순백 UI · 단일 액센트 `#3E6AE1` · 그림자 없음 · 4px 라운드 · 전환 0.33s. **NVR 특성상 다크 캔버스**(영상이 주인공) + 그 위에 순백 UI 패널.
```css
:root {
  /* accent */
  --axp-primary: #3E6AE1;            /* CTA only */
  --axp-primary-foreground: #FFFFFF;
  /* surfaces */
  --axp-surface: #FFFFFF;            /* 순백 UI 패널/사이드바/카드 */
  --axp-surface-alt: #F4F4F4;        /* Light Ash */
  --axp-canvas: #171A20;             /* Carbon Dark — 영상 그리드 캔버스/앱 배경 */
  /* text */
  --axp-text: #171A20;               /* Carbon Dark */
  --axp-text-secondary: #393C41;     /* Graphite */
  --axp-text-tertiary: #5C5E62;      /* Pewter */
  --axp-placeholder: #8E8E8E;        /* Silver Fog */
  /* lines */
  --axp-border: #EEEEEE;             /* Cloud Gray */
  --axp-border-strong: #D0D1D2;      /* Pale Silver */
  /* radius / motion */
  --axp-radius: 4px;
  --axp-radius-lg: 12px;             /* 큰 카드 */
  --axp-transition: 0.33s cubic-bezier(0.5, 0, 0, 0.75);
  /* shadow: 없음 (elevation = z-index/opacity/photography) */
}
```
- Tailwind theme 에 위 변수 매핑(`colors.primary`, `colors.surface`, `borderRadius.DEFAULT: '4px'`, `transitionTimingFunction`). shadcn `--primary` 등은 `#3E6AE1` 로 오버라이드. **box-shadow 유틸 사용 금지**(레이아웃은 border/spacing 로 구분, DESIGN.md §6·§7).
- 폰트: Universal Sans 미보유 시 폴백 `-apple-system, "Pretendard", Arial, sans-serif`(한글 가독성 위해 Pretendard 권장). 굵기 400/500 만 사용.

### 8.3 앱 셸 (`src/layouts/dashboard/`)
- 구조: 좌측 **순백 사이드바**(접이식, 메뉴는 `/auth/me` 의 menus + `config/menu.config.ts`) + 상단바(좌: AeroXProtect 워드마크, 우: 언어토글·사용자메뉴·로그아웃) + 우측 콘텐츠. 앱 전체 배경은 다크 캔버스(`--axp-canvas`), UI 패널은 순백.
- 컴포넌트: `Layout.tsx`, `Sidebar.tsx`, `Topbar.tsx`, `Breadcrumb`. 메뉴 활성/호버는 **배경색 전환만**(scale/translate 금지). CTA 만 `#3E6AE1`.
- 반응형(DESIGN.md §8): `<768px` 사이드바 → 드로어(Radix `sheet`), 상단 햄버거. PWA: `manifest.webmanifest` + 기본 service worker(설치 가능 수준만, 푸시는 P5).

### 8.4 인증 컨텍스트 (`src/auth/AuthProvider.tsx` + `useAuthContext`)
- ams `JWTProvider` 를 **실제 JWT 동작**으로 구현(ams 는 쿠키세션이라 Bearer 가 주석처리됨 → 본 프로젝트는 활성화).
- 상태: `auth: { access_token, expires_in } | null`, `currentUser`, `permissions`, `loading`.
- 메서드: `login(login_id, password)`(→ access 메모리/`localStorage(axp-auth-v{ver})` 저장 + refresh 는 httpOnly 쿠키라 JS 접근 안 함), `logout()`(서버 logout + 상태 clear), `verify()`(앱 부팅 시 `/auth/me`로 복원, access 만료면 interceptor 가 refresh), `hasPermission(resource, action)`.
- access 토큰은 메모리 우선 + 새로고침 복원을 위해 `localStorage` 보관(만료 짧음). refresh 는 **쿠키 only**(XSS 시 탈취 표면 축소).

### 8.5 라우팅 (`src/routing/AppRouter.tsx`)
- `react-router-dom` v6. 구조(ams `AppRoutingSetup` 패턴):
  - `/auth/login` (+ `/auth/reset-password` 자리) — 인증 레이아웃.
  - `<ProtectedRoute>`(ams `RequireAuth` 강화: `auth` 없으면 `/auth/login` 리다이렉트, 있으면 `/auth/me` 검증) → `<Layout>` 하위에 보호 라우트.
  - P0 보호 라우트: `/`(대시보드 플레이스홀더), `/users`(perm:users:read), `/settings`(perm:settings:read). P1~P6 페이지 경로는 `menu.config.ts` 에 자리만(`/live,/playback,/events,/cameras,/storage,/dashboards,/monitors,/rules,/ai`).
  - 권한 가드 `<RequirePermission resource action>` 래퍼(없으면 403 페이지).
- Provider 중첩(ams 순서 차용): `QueryClientProvider → AuthProvider → SettingsProvider → TranslationProvider(react-intl) → LayoutProvider → ToasterProvider(sonner) → Router`.

### 8.6 API 클라이언트 (`src/lib/axios.ts` — 인터셉터 + 자동 refresh)
```ts
// 핵심 동작
axios.defaults.baseURL = import.meta.env.VITE_APP_API_URL; // /api/v1
axios.defaults.withCredentials = true;                     // refresh 쿠키 전송
// request: 메모리 access → Authorization: Bearer
// response 401 처리: 단일 비행(single-flight) refresh
//   1) 401 && !config._retry && refresh 미진행  → POST /auth/refresh (쿠키)
//   2) 성공: 새 access 저장 → 원요청 재시도 (대기 큐 flush)
//   3) refresh 실패: auth clear → window.location = '/auth/login'
```
- 동시 401 다발 시 refresh 1회만 수행하고 나머지는 큐 대기(promise 공유). `/auth/login`·`/auth/refresh` 자체는 인터셉터 재귀 제외.
- 403 은 권한부족 → 토스트(`권한이 없습니다`) + 현재 페이지 유지(ams 의 무조건 리다이렉트와 달리 401/403 의미 분리).

### 8.7 로그인 페이지 (`src/pages/auth/LoginPage.tsx`)
- 다크 캔버스 풀스크린 배경 + 중앙 **순백 카드**(border만, 그림자 없음, radius 4px). 상단 "AeroXProtect" 워드마크, `login_id`/`password` 입력(placeholder `#8E8E8E`), `#3E6AE1` "로그인" CTA(40px, width 200~full, 0.33s 전환). 에러는 카드 내 인라인 + 토스트. Enter 제출. 폼: react-hook-form + zod(또는 Formik+Yup; ams 는 Formik, TS 신규는 react-hook-form 권장 — 택1, 본 문서는 zod 권장).

### 8.8 i18n (`src/i18n/`)
- react-intl. `messages/ko.json`, `messages/en.json`(P0 키: `menu.*`, `auth.*`, `common.*`, `error.*`). `I18N_DEFAULT_LANGUAGE='ko'`, `localStorage` + `?lang=` 동기화(ams `TranslationProvider` 패턴). 로그인 사용자의 `language` 와 동기화(`POST /auth/language`).

### 8.9 토스트
- sonner `<Toaster richColors position="top-center" />`. 성공/에러 헬퍼 `toast.success/error`. 색은 액센트 위주, 시맨틱 색은 sonner 기본(DESIGN.md 는 시맨틱 색 미정의 → 최소 사용).

---

## 9. 작업 분해 (순서 있는 체크리스트)

1. 저장소 골격 생성: `server/ frontend/ worker/{recorder,detector} go2rtc/ migrations/ docker-compose.yml`, `pyproject.toml`(ams deps + PyJWT 추가), `.env.example`.
2. `config.py` + `server/util/snowflake.py` + `server/exception.py` + `server/view/response.py`(ResponseBuilder 이식).
3. `server/model/__init__.py`(DataAccessLayer + Mixin + KST/UTC) + 공통 Base.
4. 모델 작성: `user, role, permission, refresh_token, audit_log` + 스켈레톤(`camera, stream, disk, storage_policy, dashboard, setting`) + `server/model` import 등록.
5. `server/__init__.py`(앱·ProxyFix·CORS·db_init·teardown·JSON 인코더·before_request[JWT 해석+접근로그]·Sentry) + `server/command.py`(`migrate`, `seed`) + `server/__main__.py`.
6. 서비스: `TokenService`, `PermissionService`. 데코레이터 `server/decorator.py`.
7. 컨트롤러: `AuthController, UserController, RoleController, AuditLogController`.
8. 뷰: `healthz`, `auth`, `admin/user`, `admin/role`, `admin/permission`, `admin/audit_log` + `server/view/__init__.py` blueprint 등록.
9. 부트스트랩 admin 시드(`seed-admin`) + `migrations/0000_init.sql` 작성.
10. Celery: `task/celery.py`, `celeryconfig.py`, `task/list/maintenance.py`(`cleanup_expired_tokens`).
11. 백엔드 Dockerfile(uWSGI) + worker/detector Dockerfile(stub) + go2rtc 기본 yaml.
12. `docker-compose.yml`(7서비스·네트워크·볼륨·healthcheck) + `docker-compose.override.yml`(dev).
13. 프론트 부트스트랩: Vite+TS+Tailwind+shadcn 초기화, `globals.css` 디자인 토큰, `tailwind.config.ts`.
14. 프론트 코어: `lib/axios.ts`(인터셉터+refresh), `AuthProvider`, `ProtectedRoute`/`RequirePermission`, `AppRouter`, providers wrapper.
15. 앱 셸: `layouts/dashboard`(Layout/Sidebar/Topbar) + `menu.config.ts`.
16. 페이지: `LoginPage`, 대시보드 플레이스홀더, `UsersPage`(목록/생성/권한편집 — data-grid 래퍼 활용), `SettingsPage` 자리.
17. i18n ko/en + sonner Toaster + PWA manifest/sw.
18. 테스트: pytest(인증/권한/회전/잠금) + 프론트 빌드/스모크.
19. 전수 점검(PLAN/DESIGN 일관성, 보안 체크리스트) → DoD 검증 → 본 문서 §14 갱신.

---

## 10. 다른 기능/Phase에 미치는 영향 (Cross-feature Impact) ★

P0 는 **전 Phase 의 토대**이므로 여기서 굳히는 계약이 곧 모든 Phase 제약이 된다.

| 영역 | P0 에서 고정하는 계약 | 영향받는 Phase | 비고 |
|---|---|---|---|
| **인증** | JWT 클레임 포맷, `aud`(web/monitor/node/api), `tv`, denylist 키 `axp:denylist:<jti>`, refresh 쿠키 경로 | P5(모니터 페어링=monitor 토큰), P4·P6(node/api scoped) | scoped 토큰은 같은 검증기 재사용 → P0 검증기에 aud 분기 자리 필수 |
| **RBAC** | 권한 카탈로그 `resource:action` 네이밍, 권한맵 JSON 병합 규칙, 데코레이터 시그니처 | 전 Phase(각자 자기 resource 권한 추가) | P1: `cameras/live/streams`, P2: `recordings/playback/storage`, P3: `events/schedules`, P4: `ai`, P5: `rules/monitors`. **새 권한은 카탈로그 시드에 append** |
| **Base 모델** | Snowflake ID, soft delete, 감사 컬럼, UTC 저장 | 전 Phase | 모든 신규 테이블이 동일 mixin 상속 → 마이그레이션 일관 |
| **시간 정책** | DB·서버 UTC 저장, 프론트 KST 표시 | P2(세그먼트 start/end_ts 정확성), P3(이벤트 ts) | 녹화 타임스탬프 정확성의 근간 — 변경 시 전 Phase 재검토 |
| **응답/페이지네이션** | `ResponseBuilder` 상태셋, `page/items_per_page/sort/order/q`, `{items, pagination}` 포맷 | 전 Phase(목록 API) | 프론트 data-grid 래퍼가 이 포맷 가정 |
| **스켈레톤 테이블** | `cameras/streams/disks/storage_policies/dashboards/settings` 컬럼·FK 방향(논리참조) | P1·P2·P5 가 ALTER 로 확장 | P0 에서 PK/uuid/관계 방향 확정 → 후속은 컬럼 추가만(파괴적 변경 회피) |
| **인프라** | 서비스명 `axp-*`, 네트워크 `axp-net`, 공유 볼륨 `axp-media`, go2rtc API URL | P1(go2rtc 등록), P2(media 마운트), P4(detector GPU) | `SNOWFLAKE_INSTANCE` 서비스별 분리(backend=1, worker=2)로 ID 충돌 방지 |
| **프론트 셸** | 디자인 토큰(CSS 변수), 메뉴 설정 스키마, 보호 라우트/권한 가드 | 전 Phase 페이지 | 각 Phase 는 `menu.config.ts` 에 항목 추가 + 페이지를 가드로 감쌈. 토큰 변경 시 전 화면 영향 |
| **드라이버 인터페이스 자리** | `server/driver/*` stub 시그니처 방향 | P1·P3·P5 | 빈 모듈이라도 미리 둬서 import 경로 안정화 |

**회귀 주의**: P0 의 토큰 검증·권한 데코레이터·Base mixin·응답 포맷은 이후 어떤 Phase 도 변경 시 **전 기능 회귀 테스트** 필요. 변경 결정은 PLAN §0(3) 에 따라 사용자 확인.

---

## 11. 리스크 & 완화

| 리스크 | 영향 | 완화 |
|---|---|---|
| JWT 도난(특히 access XSS) | 세션 탈취 | access 단기(15m)·메모리 우선, refresh httpOnly 쿠키, `tv` 전역 무효화, refresh 회전+재사용 탐지(패밀리 폐기) |
| refresh 동시요청 경쟁(여러 탭) | 정상 토큰이 재사용 탐지에 걸림 | 프론트 single-flight refresh, 서버는 **회전 grace**(직전 jti 짧은 유예) 또는 family 기반 관대 처리 — P0 결정 필요(§14) |
| 시간대 혼선(KST/UTC) | 녹화·이벤트 ts 오차(후속 치명) | DB·컨테이너 UTC 강제, 표시만 KST, 테스트로 round-trip 검증 |
| Snowflake ID 충돌 | PK 중복 | 서비스별 `SNOWFLAKE_INSTANCE` 분리, 시드 PK(1~999) 예약, 생성기 단위테스트 |
| Compose 기동 순서/healthcheck 미흡 | backend 가 DB 전에 떠서 크래시 | `depends_on: condition: service_healthy` + 앱 재시도 + `restart: unless-stopped` |
| go2rtc 최신 태그 변동 | 재현성 저하 | 이미지 **버전 핀**(`alexxit/go2rtc:1.9.x`), MySQL/Redis 도 마이너 핀 |
| 디자인 일탈(그림자·다색) | DESIGN.md 위반 | 토큰만 사용·box-shadow 유틸 비활성, 리뷰 체크리스트 |
| 패키지 취약점 | 보안 | 최신 stable 핀(PLAN §11), `pip-audit`/`npm audit` CI |
| 권한맵 JSON 자유도 → 오타 권한 | 권한 누수/거부 | 카탈로그 테이블로 서버 검증, 프론트는 카탈로그 기반 편집(자유입력 금지) |

---

## 12. 테스트 계획 (unit/integration/e2e)

**Unit (pytest, `tests/`)**
- `TokenService`: access/refresh 발급 클레임, 만료, 위조 서명 거부, denylist 적중, 회전(이전 폐기·새 발급), 재사용 탐지(패밀리 폐기), `tv` 불일치 무효.
- `PermissionService`: 와일드카드(`*`) 처리, role+user 병합 우선순위, 없는 권한 거부.
- `snowflake`: 단조 증가·인스턴스 분리·중복 없음.
- Argon2 해시/검증, 잠금 카운터 증가/리셋.

**Integration (Flask test client + 테스트 MySQL/Redis 또는 fakeredis)**
- `POST /auth/login` 성공/실패/잠금(5회), 감사 로그 적재.
- `GET /auth/me` 유효·만료·denylist access.
- `POST /auth/refresh` 정상 회전, 쿠키 누락, 만료 refresh, 재사용 토큰 → 401 + family 폐기.
- `POST /auth/logout` → 이후 access/refresh 거부.
- 데코레이터: `permission_required` 통과/403, `roles_required('admin')` 차단.
- `admin/users` CRUD + 페이지네이션(`page/items_per_page/sort/order/q`) + soft delete + reset_password(`tv++` 로 기존 토큰 무효).
- `healthz` db/redis 연결 반영.

**E2E / 스모크**
- 프론트: `npm run build` 무에러 + `tsc --noEmit`.
- (선택) Playwright: 로그인 → 대시보드 진입 → 새로고침 세션 유지(silent refresh) → 로그아웃 → 보호 라우트 접근 시 `/auth/login` 리다이렉트 → 언어 토글.
- Compose: `docker compose up` 후 7서비스 healthy + `curl /api/v1/healthz` 200(스크립트화).

**회귀**: P0 테스트 스위트를 이후 Phase CI 의 베이스라인으로 고정(인증/권한 회귀 방지).

---

## 13. 성능·보안 체크포인트

**성능**
- 쿼리: 불필요 join/FK 자제(논리참조), 목록은 `count()+limit/offset`(ams 패턴), N+1 회피(필요 시 `selectinload`). 인덱스: `login_id/uuid/role_id/deleted_at`, audit `action/created_at`.
- access 검증은 Redis(jti) + 서명 검증만(매 요청 DB 조회 최소화 — 사용자/권한은 토큰 클레임 + 필요한 라우트에서만 DB).
- 접근 로그 적재는 비차단/경량(정적·healthz 제외, 실패 시 무시).
- 프론트 번들: 코드 스플리팅(라우트별 lazy), TanStack Query 캐시.

**보안**
- 비밀번호 Argon2id, 평문 미저장·미로깅. 응답에 `password`·해시·refresh 토큰 절대 미포함.
- 브루트포스: 30분 5회 → `locked_until`, admin unlock. 비번 재설정 rate limit(ams 패턴).
- JWT: 강한 `JWT_SECRET`(env), HS256, `aud`/`exp`/`typ` 검증. refresh 쿠키 `HttpOnly; Secure; SameSite=Strict; Path=/api/v1/auth`.
- CSRF: API 는 Bearer 헤더라 기본 안전. refresh 쿠키 엔드포인트(`/auth/refresh`,`/auth/logout`)는 SameSite=Strict + (옵션) double-submit/Origin 체크.
- CORS: `CORS_ALLOWED_ORIGINS` 화이트리스트(운영), `*` 는 dev 한정.
- 인가: 모든 비-public 라우트에 데코레이터 강제. 권한 부족 시 정보 비노출(404 vs 403 정책: 존재 은닉 필요 리소스는 404).
- 자격증명 암호화 키(`CREDENTIAL_ENC_KEY`) env 주입, 카메라 비번 등 평문 응답 금지(P1 대비 P0 에서 컬럼·정책 확립).
- 컨테이너 non-root, 시크릿 env(이미지 미내장), 패키지 최신 stable + `pip-audit`/`npm audit`.
- Sentry 에 PII/시크릿 마스킹.

---

## 14. 미해결 질문 / 결정 필요 사항

1. **회원가입 정책** — **해소됨: admin 생성 전용**(사용자 결정 확정, PLAN §2·§12.3). 공개 회원가입·자가가입 없음. 최초 실행 셋업 마법사로 첫 admin 생성, 이후 admin 이 사용자 생성·권한 부여(가입신청/승인 플로우 미사용).
2. **refresh 동시요청 grace**: 멀티탭 동시 refresh 시 정상 토큰의 재사용 오탐 방지를 위해 직전 jti **짧은 유예(grace, 예 10s)** 를 둘지, 아니면 순수 단일회전(프론트 single-flight 의존)만 둘지. (보안 vs UX 트레이드오프 — 결정 필요)
3. **access 토큰 저장 위치**: 메모리 only(새로고침마다 silent refresh) vs `localStorage` 보관(XSS 노출 ↔ UX). 본 문서는 "메모리 우선 + localStorage 백업" 가정 — 보안 강화 시 메모리 only 로 변경 가능. (확정 필요)
4. **uWSGI 멀티프로세스 + Redis denylist**: 프로세스 간 상태는 Redis 공유라 무방하나, access **클레임 캐시**(권한) 도입 여부(성능 vs 즉시성). P0 는 캐시 없이 진행 가정.
5. **404 vs 403 노출 정책**: 비인가 리소스를 404 로 숨길 범위(카메라 등 민감 리소스 한정). 공통 규칙 확정 필요.
6. **프론트 폼 라이브러리**: ams 는 Formik+Yup. TS 신규는 react-hook-form+zod 권장 — 팀 표준 확정 필요(본 문서 zod 가정).
7. **Universal Sans 라이선스**: DESIGN.md 폰트 미보유 시 Pretendard 폴백 확정 여부(한글 NVR UI 가독성).

> 위 항목은 확정 시 본 문서와 `../PLAN.md` 에 반영(PLAN §0-4). 1 은 해소(admin-only 확정)됨. 현재 가정값으로 구현 착수 가능하며, 2·3 만 착수 전 사용자 확인 권장(인증 방향성 영향).

### 14.1 구현 시 채택한 결정 (2026-06-05, P0 구현 완료)
- **2. refresh grace**: grace 없이 **순수 단일회전 + 재사용 탐지(family 폐기)** 채택. 멀티탭 경쟁은 프론트 **single-flight refresh**(`lib/axios.ts`)로 방지. (향후 UX 이슈 시 직전 jti 짧은 grace 추가 가능.)
- **3. access 저장**: **`localStorage`(`axp-auth-v1`) + 메모리** 채택(ams 패턴). refresh 는 httpOnly 쿠키 only.
- **6. 폼 라이브러리**: **react-hook-form + zod** 채택.
- **7. 폰트**: **Pretendard 폴백** 채택(`-apple-system` 등).
- **4/5**: P0 가정 유지(클레임 캐시 없음 / 404-은닉은 민감 리소스 도입 시 각 Phase 결정).

### 14.2 DoD 검증 결과 (2026-06-05, 전 항목 PASS)
`docker compose up` → **7개 서비스 전부 healthy**(mysql·redis·go2rtc·backend·worker·detector·frontend). `migrate`/`seed`/`seed-admin` 동작, MySQL 시드 검증(roles=2·permissions=60·settings=3). JWT 로그인·`/me`·refresh 회전·logout denylist·브루트포스 잠금(5회→429)·RBAC 403 동작. **pytest 35 passed**, 프론트 `tsc --noEmit` + `vite build` 무에러. nginx `/api` 프록시·detector health 확인. 다음 단계 = **P1(카메라 온보딩 + 라이브뷰)**.
