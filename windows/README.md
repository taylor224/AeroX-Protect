# AeroXProtect — Windows 네이티브 배포 (Docker 없이)

Inno Setup 인스톨러 하나로 설치되고, WinSW 기반 Windows 서비스(**런처**)가 전체
스택을 감독한다. 웹 UI 설정 페이지의 **시스템 업데이트** 카드가 GitHub Releases에서
새 버전을 받아 원클릭 자동 업데이트한다.

## 구성 (Docker ↔ Windows 대응)

| Docker | Windows 네이티브 |
|---|---|
| uWSGI | waitress (`python -m server.wsgi`, 127.0.0.1:10000) |
| nginx (frontend) | Caddy — SPA 정적 서빙 + `/api` 프록시 + `forward_auth`로 `/live-ws/` 티켓 검증 + `/updater/*` → 런처 |
| mysql:8.4 | MariaDB 11.8 (포터블, 루프백 **3307**) |
| redis:7.4 | redis-windows 7.4 (루프백 **6380**) |
| go2rtc 이미지 | go2rtc.exe (1984/8554/8555) |
| celery prefork | `--pool=threads -c 8 -B` (+ subs 큐 `--pool=threads -c 50`) |
| python:3.13 이미지 | nuget CPython 3.13 + 버전 디렉터리 동봉 site-packages(`PYTHONPATH` 주입) |

## 설치 트리

```
C:\AeroXProtect\
  runtime\    python, ffmpeg, go2rtc, caddy, redis, mariadb, fonts   ← 인스톨러만 교체
  launcher\   axp_launcher(stdlib 전용) + axp-service.exe(WinSW) + templates
  versions\v1.3.0\   site-packages, app(server+worker+migrations+config.py), frontend, VERSION
  current     → versions\vX 디렉터리 정션. 업데이트 = 정션 스왑, 롤백 = 재포인트
  config\     axp.env(시크릿, SYSTEM/Admins ACL), Caddyfile, my.ini, redis.conf, go2rtc.yaml
  data\       mariadb, redis, logs, staging, backups, media\thumbnails
  storage\    disk1\  (AXP_DISK_ROOT — 설치 시 변경 가능)
```

`config\`·`data\`·`storage\`는 자동 업데이트가 절대 건드리지 않는다.

## 런처

- Job Object(`KILL_ON_JOB_CLOSE`)에 전 자식 편입 → 런처가 죽어도 ffmpeg 고아 불가.
- 종료 사다리: CTRL_BREAK → graceful timeout → kill → Job Object.
- 기동 순서: mariadb → redis → go2rtc → caddy → (db-upgrade/seed/seed-admin) →
  backend → worker → subs → recorder → encoder → [detector(선택)].
- 컨트롤 API `127.0.0.1:10099` — Bearer(`AXP_LAUNCHER_TOKEN`) 또는 업데이트 진행률
  전용 HMAC 티켓(`SECRET_KEY` 파생, `server/service/update_ticket.py`와 동일 규격).
- CLI: `runtime\python\python.exe -m axp_launcher.ctl status|logs|restart|update-check|update-apply|stop`

## 자동 업데이트

1. 설정 페이지 카드 → `GET /api/v1/system/update/check` (백엔드가 런처에 프록시,
   런처가 GitHub `/releases/latest` 1시간 캐시 조회)
2. `POST /api/v1/system/update/apply` → 감사로그 + HMAC 티켓 발급 → 런처 상태머신 기동
3. 다운로드 → sha256 검증 → `versions\vX` 추출 → mariadb-dump 백업 → **앱 티어만 정지**
   (mariadb/redis/go2rtc/caddy/런처는 유지 → SPA와 `/updater/*` 진행률 폴링 생존)
   → 새 payload로 `db-upgrade` → 정션 스왑 → seed → 재기동 → healthz 게이트(120s)
4. 실패 시 자동 롤백: 정션 복귀 + (DDL이 돌았으면) dump 복원
5. `min_launcher_version` 미달 릴리스는 "인스톨러 필요"로 표시만 하고 스왑하지 않음

## 빌드 / 릴리스

- 태그 `vX.Y.Z` 푸시 → `.github/workflows/windows-bundle.yml`이 windows 러너에서
  wheel 게이트 → frontend build → `fetch-runtime.ps1`(핀 고정+sha256) →
  `assemble-bundle.ps1`(app zip + manifest + SHA256SUMS) → Inno Setup → 릴리스 첨부.
- 로컬 빌드: `windows/build/*.ps1` 주석 참고.
- `fetch-runtime.ps1`의 `Sha256 = 'SKIP'` 핀은 첫 fetch 후 실제 해시로 채울 것.

## 남은 하드닝 (P6)

- manifest minisign 서명 검증(`update.py` 검증 지점에 드롭인)
- Authenticode 코드서명 (없으면 SmartScreen 경고)
- Defender 실시간 검사에서 `storage\` 제외 안내(녹화 쓰기 처리량)
- AI detector 선택 컴포넌트(`site-packages-ai` + requirements-inference wheels)
