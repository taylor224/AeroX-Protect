# Phase 6 — 패리티 & 폴리시

> 마스터 플랜: [`../PLAN.md`](../PLAN.md) · 디자인: [`../DESIGN.md`](../DESIGN.md) · 선행: [`phase-1.md`](phase-1.md)(카메라/스트림/capability/PTZ), [`phase-2.md`](phase-2.md)(세그먼트·캐시·보존·재생·내보내기), [`phase-3.md`](phase-3.md)(이벤트 정규화·정책·스케줄), [`phase-4.md`](phase-4.md)(YOLO detection·검색·분산 AI), [`phase-5.md`](phase-5.md)(규칙엔진·모니터·알림).
> **구현 전 본 문서 + PLAN.md를 읽고, "10. Cross-feature Impact" 절을 반드시 확인·갱신**한다. 네임스페이스 `axp`, Flask MVC(view→controller→service/driver→model), Celery+Redis, 응답은 `ResponseBuilder`. 저장 타임스탬프는 **전 계층 `DATETIME(3)` UTC**(SSOT §12.1 — P3도 `DATETIME(3)`로 통일, 본 Phase 신규 컬럼도 동일), **API 직렬화는 epoch ms(또는 ISO), 표시·스케줄 해석은 KST**.
>
> **본 Phase의 성격**: P6는 단일 기능 묶음이 아니라 **상용 NVR 제품 패리티를 채우는 광범위한 고급 기능 백로그**다. 따라서 다른 Phase처럼 "한 번에 전부 구현"하지 않는다. 본 문서는 **각 기능을 기능군으로 묶어 우선순위·의존성·난이도·후속 Phase 분리 여부를 판정하는 포트폴리오/로드맵 문서**이며, 코드레벨이 아니라 **실행 가능한 설계 방향 + 데이터/엔드포인트 영향 + 리스크**를 제공한다. 큰 기능(LPR/얼굴, 다중 NVR, 원격 포털, 출입통제)은 본 문서에서 **별도 Phase 분리를 권고**한다.

---

## 1. 목표 & 성공 기준(DoD)

P6는 "P0~P5로 동작하는 NVR 위에, 경쟁 제품이 제공하는 **고급·차별화 기능**을 우선순위에 따라 점진적으로 얹되, 각 기능이 기존 계약(스트림/녹화/이벤트/AI/규칙)을 깨지 않고 **플래그로 켜고 끌 수 있게** 통합한다"를 목표로 한다.

P6는 단일 마일스톤이 아니므로 DoD를 **(A) 본 설계 문서의 완결성**과 **(B) 각 기능군의 개별 DoD**로 나눈다.

**(A) 문서 DoD — 본 문서가 충족해야 할 것:**

1. 모든 P6 후보 기능이 **기능군 + 우선순위(High/Med/Low) + 의존 Phase + 구현 난이도(S/M/L/XL) + 후속 상세 Phase 분리 필요 여부** 표로 정리됨(2절).
2. 각 기능에 **무엇을 / 핵심 접근 / 의존성 / 데이터·엔드포인트 영향 / 리스크**가 명시됨(6·7절).
3. P1~P5 계약에 요구하는 변경(마이그레이션·플래그·역호환)이 **Cross-feature Impact**에 빠짐없이 정리됨(10절).
4. 자체 Phase(P7+)로 분리할 만큼 큰 기능이 **명시적으로 권고**됨(9절).

**(B) 기능군별 개별 DoD(해당 기능을 실제 착수·완료할 때의 기준):**

5. **라이브 고급**: 지원 카메라에서 ① 브라우저↔카메라 **양방향 오디오** 통화, ② 권한자만 보이는/모두에게 마스킹되는 **프라이버시 마스킹**, ③ 어안 카메라 **디워핑** 프리셋, ④ **시퀀스/자동전환** 레이아웃, ⑤ **지도 기반 모니터링**에서 카메라 핀 클릭→라이브, ⑥ **PTZ 오토트랙**(지원 카메라 토글) 중 착수 기능이 단독 시연 가능.
6. **녹화/재생 고급**: ① 해상도별 **이중 녹화** 정책, ② **공유 링크**(비회원 만료/비밀번호 열람), ③ 내보내기 **워터마크·비밀번호 잠금**, ④ **북마크/라벨** 중 착수 기능이 단독 시연 가능. 엣지녹화/암호화는 가이드+옵션 수준.
7. **AI 고급**: ① **시맨틱 이미지 검색(CLIP)** 자연어 질의→썸네일 결과, ② **사람/차량 카운팅 + occupancy**, ③ **배회(loitering)** 규칙, ④ **오디오 분류**, ⑤ (분리 Phase) **LPR/얼굴** 중 착수 기능이 단독 시연 가능.
8. **관리/확장**: ① **백업·아카이빙**(NAS/클라우드), ② **배치 카메라 추가**(P1 보강), ③ (분리 Phase) **다중 NVR 통합 뷰 / 원격 포털** 중 착수 기능이 단독 시연 가능.
9. **횡단**: 모든 신규 기능은 **feature flag**(`settings` 또는 `feature_flags`)로 토글 가능하고, off 시 P0~P5 동작·성능에 영향 없음. 신규 권한키는 P0 권한맵에 추가되고 admin 전권. 모든 신규 API는 카메라 스코프/권한 점검.

---

## 2. 범위 (기능군 전체 목록 + 우선순위 표)

> **우선순위**: High=패리티에 필수·자주 요구·기반 재사용으로 저비용 / Med=차별화·중요하나 비용/리스크 중간 / Low=니치·하드웨어 의존·후속.
> **난이도**: S(≤1주), M(1–3주), L(3–6주), XL(별도 Phase 권장, 6주+ 또는 외부 의존 큼).
> **분리**: ✅=자체 후속 Phase로 분리 권고, ➖=P6 내 처리 가능, △=조건부(규모 커지면 분리).

### 2.1 라이브 고급

| # | 기능 | 우선 | 의존 | 난이도 | 분리 | 한줄 요지 |
|---|---|---|---|---|---|---|
| L1 | 양방향 오디오(go2rtc backchannel) | High | P1(streams/audio cap)·P0(auth/scope) | M | ➖ | go2rtc WebRTC sendrecv + 카메라 backchannel(ONVIF/벤더). 권한·동시화자 제어 |
| L2 | 프라이버시 마스킹 | High | P1·P2(녹화)·P4(오버레이) | M | ➖ | 카메라측 OSD 마스크 우선, 서버측은 클라이언트 렌더 마스크 + 다운로드 시 굽기 옵션 |
| L3 | 시퀀스/순차회전 레이아웃 | High | P1(dashboards.layout) | S | ➖ | 대시보드 N개를 dwell 시간으로 자동 순환(로컬 모니터·웹 공통) |
| L4 | 이벤트 자동 화면전환(event spotlight) | High | P1·P3(events WS)·P5(monitors) | S | ➖ | 이벤트 수신 시 해당 카메라를 전체/하이라이트 셀로 자동 전환 |
| L5 | 어안렌즈 디워핑(fisheye) | Med | P1(capability)·라이브 파이프 | M | ➖ | 클라이언트 WebGL 디워핑(파노라마/쿼드/PTZ가상). 카메라 내장 디워핑은 별 스트림 |
| L6 | 지도 기반 모니터링(leaflet/maplibre) | Med | P1·P0(권한)·DESIGN | M | ➖ | 평면도/지도 위 카메라 핀·FOV·이벤트 점멸. ams의 leaflet/maplibre 재사용 |
| L7 | GPU 디코딩 튜닝(라이브) | Med | P1·P4(GPU 토글) | M | △ | go2rtc/ffmpeg HW 디코드(NVDEC/VAAPI) 옵션화. 디코드는 주로 클라이언트지만 썸네일/AI/타임랩스 디코드 가속 |
| L8 | 객체 자동추적(PTZ auto-track) | Low | P1(PTZ continuous)·P4(detection/track) | L | △ | detection track→PTZ continuous move 폐루프. 안전·튜닝 난도 높음 |

### 2.2 녹화/재생 고급

| # | 기능 | 우선 | 의존 | 난이도 | 분리 | 한줄 요지 |
|---|---|---|---|---|---|---|
| R1 | 공유 링크(비회원 열람) | High | P2(playback/export)·P0(scoped JWT) | M | ➖ | 만료·비밀번호·워터마크 포함 scoped 토큰 링크. 클립/라이브 한정 공유 |
| R2 | 북마크/라벨 | High | P2(recordings)·P3(events) | S | ➖ | 타임라인 임의 시점/구간 북마크 + 색·라벨·검색. 보존 잠금 연계 |
| R3 | 내보내기 워터마크/비밀번호 잠금 | High | P2(export_jobs/transcode) | M | ➖ | transcode 시 워터마크 drawtext/overlay, 산출물 AES 암호 컨테이너/zip |
| R4 | 이중 녹화(해상도별) | Med | P2(recorder/segments/storage) | M | ➖ | main+sub 동시 세그먼트 녹화, 보존등급 차등(고해상도 단기·저해상도 장기) |
| R5 | 녹화 암호화(at-rest) | Med | P2(disks/segments) | L | △ | 디스크 단위(LUKS, 권장·가이드) vs 파일 단위(앱 암호화, seek/copy 비용) |
| R6 | 엣지 녹화(카메라 SD) | Low | P1(드라이버)·P2(타임라인 병합) | L | △ | 카메라 SD 클립을 ISAPI/SUNAPI/ONVIF Replay로 조회·갭필·임포트 |

### 2.3 AI/분석 고급

| # | 기능 | 우선 | 의존 | 난이도 | 분리 | 한줄 요지 |
|---|---|---|---|---|---|---|
| A1 | 시맨틱 이미지 검색(CLIP 재활용) | High | P4(detector/검색·임베딩)·P2(프레임) | M | ➖ | ams `clip_filter.py` 재사용. 썸네일/크롭 임베딩 인덱싱 + 자연어 질의 |
| A2 | 사람/차량 카운팅 + occupancy | High | P4(detection/track)·P3(events) | M | ➖ | 라인 통과 카운팅(in/out) + 영역 점유수 시계열. 혼잡 임계 알림(P5) |
| A3 | 배회(loitering) | High | P4(track 체류시간)·P3·P5 | M | ➖ | 영역 내 track dwell ≥ T → loitering 이벤트. P3 enum 이미 예약 |
| A4 | 오디오 감지/분류 | Med | go2rtc(오디오)·P4(워커) | M | △ | YAMNet/PANNs류 경량 분류(개짖음/유리깨짐/비명/경보). 오디오 파이프 신설 |
| A5 | 연기/화재 감지 | Med | P4(detector 모델) | M | △ | 전용 YOLO/분류 모델. 오탐 관리·검증 데이터 필요 |
| A6 | 동물/택배 감지 | Med | P4(detector 클래스) | S | ➖ | YOLO 클래스 확장(dog/cat/bird, package). 대부분 모델/라벨 작업 |
| A7 | LPR(번호판 인식) | High | P4·신규 OCR 파이프·DB | XL | ✅ | 검출→정렬→OCR(지역 특화)→`plates`. 정확도·국가별 규격 → **Phase 7 권고** |
| A8 | 얼굴 인식(로컬 DB) | Med | P4·임베딩·벡터검색·DB | XL | ✅ | 검출→임베딩→ANN 매칭→`faces/persons`. 프라이버시·법규 → **Phase 7 권고** |

### 2.4 관리/확장 & 장치

| # | 기능 | 우선 | 의존 | 난이도 | 분리 | 한줄 요지 |
|---|---|---|---|---|---|---|
| M1 | 배치 카메라 추가(P1 보강) | High | P1(디스커버리/프로빙) | S | ➖ | 검색결과 다중선택·공통 자격증명·CSV 임포트·일괄 프로빙 잡 |
| M2 | 백업·아카이빙(클라우드/NAS) | High | P2(segments/recordings)·Celery | M | ➖ | 보호/이벤트 클립을 S3/SMB/NFS로 비동기 아카이브 + 복원 인덱스 |
| M3 | 도어벨/인터컴 | Med | P1·L1(양방향오디오)·P3(io/call event)·P5 | M | △ | SIP/ONVIF doorbell call 이벤트→통화 UI→문열기(IO) 연계 |
| M4 | RAID 스토리지 가이드 | Med | P2(disks) | S | ➖ | 문서+상태 표면화(mdadm/btrfs/ZFS SMART·degraded 표시). 구현 아닌 가이드+모니터 |
| M5 | 다중 NVR 중앙관리·통합 뷰 | High | P0(auth/federation)·P1~P5 전반 | XL | ✅ | 사이트 페더레이션·통합 카메라/이벤트/검색. 아키텍처 변경 → **Phase 8 권고** |
| M6 | 원격 접속 포털(포워딩/VPN 불필요) | High | P0(auth)·인프라(relay) | XL | ✅ | WebRTC TURN + 시그널 릴레이/리버스 터널. 보안·운영 → **Phase 9 권고** |
| M7 | 출입통제 도어 컨트롤러 | Low | P1(io 드라이버)·P3·P5 | L | ✅ | Access 컨트롤러/리더·도어·일정·기록. 별도 도메인 → **Phase 10 권고** |
| M8 | 모바일 네이티브 앱 | Low | 전체 API·푸시 | XL | ✅ | PWA(P5) 이후 RN/Flutter. **후속 Phase 권고** |

### 2.5 알림/기타

| # | 기능 | 우선 | 의존 | 난이도 | 분리 | 한줄 요지 |
|---|---|---|---|---|---|---|
| N1 | SMS 알림 채널 | Med | P5(알림 채널 추상)·SOLAPI | S | ➖ | P5 채널 인터페이스에 SMS 드라이버(ams SOLAPI 패턴) 추가 |
| N2 | 알림 통합/음소거(grouping/snooze) | Med | P5(알림/규칙) | S | ➖ | 카메라·타입·시간창 음소거, 동일 이벤트 묶음(스팸 억제) |

**총괄**: High 12개(대부분 S/M·기반 재사용), Med 11개, Low 6개. **자체 Phase 분리 권고 5개**: LPR(P7), 얼굴(P7과 묶거나 P7b), 다중 NVR(P8), 원격 포털(P9), 출입통제(P10), 모바일 앱(후속). 나머지는 P6 내에서 우선순위순 점진 구현.

---

## 3. 선행 의존성

> P6는 P0~P5의 산출물을 **소비**한다. P4/P5 문서는 본 문서 작성 시점 미작성이나, PLAN.md 7·9·10절이 정의한 계약(아래 "기대 계약")을 전제로 한다. 착수 시 해당 Phase 문서로 시그니처를 확정한다(블로킹 항목은 14절).

| 출처 | P6가 사용하는 산출물 | 사용 기능 |
|---|---|---|
| **P0** | `axp` 골격, MVC/Blueprint, `BaseDB`(Snowflake·soft delete·audit), `ResponseBuilder`, JWT(access/refresh, **scoped 토큰**: monitor/node/api audience), Redis, WS 허브, 권한맵(JSON)·`@permission_required`, 자격증명 암호화(`util.crypto`), i18n, `settings` | 전 기능(특히 공유링크=scoped 토큰, 원격포털=federation auth, feature flag) |
| **P1** | `cameras`(vendor/driver/host/암호화 자격증명/`capabilities` JSON/`two_way_audio`/`audio_supported`/`ptz_supported`), `streams`(main/sub/third·`go2rtc_name`·codec/res), `driver/{onvif,isapi,sunapi}`(인증·세션·PTZ continuous·snapshot), `service.capability_probe`, `dashboards`(`layout` JSON)·`dashboard_acl`, go2rtc 동기화(`go2rtc_sync`), 시그널링 프록시 | 양방향오디오, 마스킹, 디워핑, 시퀀스/자동전환, 지도, 오토트랙, 배치추가, 도어벨, 이중녹화 스트림 선택 |
| **P2** | `segments`(camera/disk/rel_path/start_ts/end_ts/codec)·`recordings`(reason `continuous/manual/event/schedule`·`retention_class`)·`disks`·`storage_policies`(`cache_buffer_seconds`)·`export_jobs`(copy/transcode·`download_token`·`expires_at`)·`service.segment_indexer`·`storage_manager`·`task.transcode/thumbnail`·playback/타임라인 API·`/frame?ts=` | 이중녹화, 암호화, 엣지녹화 임포트, 공유링크, 워터마크 내보내기, 북마크, 백업/아카이빙, 시맨틱검색 프레임 소스 |
| **P3** | `events`(정규화 타입·`region`·`recording_id`·`dedup`)·`event_policies`·`schedules`·`event_outbox`·`signals.event_created`·정규화 enum(`loitering/face/lpr` **예약됨**)·모션 오버레이 메타·구독 워커 | 자동화면전환, 카운팅/배회/오디오/연기 이벤트, 도어벨 call 이벤트, 마스킹 영역 정의 재사용 |
| **P4** | YOLO `detector` 워커(GPU 토글, runway_monitor 확장: `detector.py`/`tracker.py`/`pipeline.py`/`zones.py`)·`detections`(class/conf/bbox/`track_id`)·객체 검색·`ai_nodes`(분산)·detection→event 링크 | 카운팅·배회·연기·동물/택배·오토트랙·**시맨틱검색(CLIP)**·LPR/얼굴(검출 단계) |
| **P5** | 규칙엔진(`rules` trigger/condition/action)·알림 채널 추상(push/email/webhook)·IP/SIP 스피커·IO 드라이버·모니터 페어링(`monitors`/`pairing_codes`)·웹훅 | 자동화면전환(모니터), 혼잡/배회/오디오 알림, SMS/음소거, 도어벨/출입통제 액션 |

**P6 착수 전 확인(블로킹):** (a) P4 detector의 **프레임/크롭 접근 인터페이스**(CLIP 임베딩·LPR/얼굴 크롭 재사용 가능 여부)와 `track_id` 안정성(카운팅/배회/오토트랙 핵심). (b) go2rtc **backchannel(양방향오디오)** 지원 빌드·카메라별 backchannel 경로(ONVIF/벤더). (c) P5 알림 채널 인터페이스 시그니처(SMS/grouping). (d) P0 scoped 토큰의 **audience 확장 여지**(공유링크용 `share` audience). (e) P2 `export_jobs.transcode_preset`에 워터마크/암호 옵션 추가 가능 여부.

---

## 4. 데이터 모델 영향 (신규/변경 테이블·컬럼 요약)

> 컨벤션(PLAN 11): Snowflake `BIGINT` PK, soft delete(`deleted_at`), 감사 컬럼, **FK 최소화**(논리 참조+인덱스), 스키마 `axp`(prefix 없음). **시각 컬럼은 전 계층 `DATETIME(3)` UTC**(SSOT §12.1 — P3/이벤트 도메인도 `DATETIME(3)`로 통일; 본 절 신규 테이블의 모든 시각 컬럼(`*_ts`/`bucket_ts`/감사 컬럼)도 동일, 아래 요약 표는 타입 생략 시 이 규약을 따름). 본 절은 **기능군별 모델 영향 요약**이며, 분리 권고 기능(LPR/얼굴/다중NVR/원격/출입통제)의 상세 스키마는 각 후속 Phase 문서로 미룬다.

### 4.1 신규 테이블(P6 내 구현 기능)

| 테이블 | 핵심 컬럼(요약) | 용도 | 기능 |
|---|---|---|---|
| `feature_flags` | `key`(UNIQUE), `enabled`, `scope`(global/camera), `camera_id` NULL, `value` JSON, 감사 | 기능 토글(전역/카메라) | 횡단 |
| `privacy_masks` | `camera_id`, `name`, `shapes` JSON(0–1 폴리곤), `mode`(`camera_osd`/`server_render`/`burn_export`), `min_role`/`required_perm`, `enabled`, 감사 | 마스킹 영역(P3 region 좌표 규약 재사용) | L2 |
| `bookmarks` | `camera_id`, `ts` 또는 `start_ts/end_ts`, `label`, `color`, `note`, `recording_id` NULL, `event_id` NULL, `lock_retention`(bool), `created_by_id`, 감사 | 타임라인 북마크/라벨 | R2 |
| `share_links` | `token`(UNIQUE, 해시 저장), `kind`(`clip`/`live`/`event`), `target_ref`(camera/recording/event id), `range_start/range_end` NULL, `password_hash` NULL, `watermark`(bool), `max_views` NULL, `view_count`, `expires_at`, `revoked_at` NULL, `created_by_id`, 감사 | 비회원 공유 링크 | R1 |
| `archive_jobs` | `target_type`(`recording`/`event`/`range`), `target_ref`/`range`, `dest_type`(`s3`/`smb`/`nfs`/`local`), `dest_config_id`, `status`, `progress`, `bytes_total/bytes_done`, `manifest_path`, `celery_task_id`, `error`, 감사 | 백업/아카이빙 작업 | M2 |
| `archive_targets` | `name`, `type`(`s3`/`smb`/`nfs`), `config_enc`(자격증명 암호화), `path_template`, `enabled`, 감사 | 아카이브 대상(자격증명 암호화 저장) | M2 |
| `counting_lines` | `camera_id`, `name`, `geometry` JSON(라인/영역 0–1), `direction_labels`(in/out), `class_filter` JSON(person/car…), `enabled`, 감사 | 카운팅/occupancy 규칙 정의 | A2 |
| `counting_stats` | `camera_id`, `line_id`, `bucket_ts`, `in_count`, `out_count`, `occupancy`, `class` | 시계열 카운트(집계, append) | A2 |
| `audio_models` / `audio_detections` | (모델 등록) / `camera_id`, `ts`, `label`, `score`, `clip_path` NULL | 오디오 분류 결과 | A4 |

### 4.2 기존 테이블 변경(역호환·플래그)

| 대상(소유 Phase) | 변경 | 비고/역호환 |
|---|---|---|
| `cameras`(P1) | `two_way_audio`/`audio_supported`는 **이미 존재**(P1이 표시만). P6가 **동작 연결**. 추가: `fisheye`(bool)·`fisheye_params` JSON(렌즈 중심/반경/모드), `auto_track_enabled`(bool), `edge_recording`(bool) | 모두 nullable/default 0 → 기존 행 영향 없음. capabilities JSON에 `audio.output/two_way`, `dewarp` 표면화 |
| `streams`(P1) | `is_backchannel`(bool) 또는 `audio_backchannel_path`(VARCHAR) — backchannel 송신 경로 표기 | nullable. go2rtc 설정 생성 시 사용 |
| `recordings`(P2) | (변경 없음 가능) 이중녹화는 `recordings`에 `stream_role`(main/sub) 또는 `quality_tier` 추가 시 차등 보존. 암호화는 `encrypted`(bool)·`enc_key_id` 추가 | 추가 컬럼은 default로 역호환. **이중녹화/암호화는 P2 협의 필요(10절)** |
| `segments`(P2) | 이중녹화: 동일 (camera, 시간)에 `stream_role` 구분 행 허용(인덱스 `(camera_id, stream_role, start_ts)`). 암호화: `enc`(bool)·`enc_iv` | 고빈도 테이블 → 컬럼 추가 신중, default 유지 |
| `export_jobs`(P2) | `watermark`(bool)·`watermark_text`·`password_protected`(bool)·`enc_algo` 추가 | transcode 경로만 사용, copy 모드는 무시 |
| `events`(P3) | enum에 `loitering`(예약됨)·신규 `count`/`occupancy`·`audio_class`·`smoke`·`doorbell_call` 추가. `face`/`lpr`은 예약됨(P7 채움) | enum은 VARCHAR(32)라 값 추가만 → 스키마 변경 불필요 |
| `event_policies`(P3) | 신규 타입에 대한 정책 행만 추가(스키마 불변) | 데이터만 |
| `permissions`(P0) | 신규 권한키(아래 5절) 추가 | 권한맵 JSON 갱신, admin 전권 |
| `settings`(P0) | feature flag·HW 디코드·아카이브 기본값 등 | KV |
| `dashboards.layout`(P1) | layout JSON에 `sequence`(dwell/순서)·`event_spotlight`·`map` 모드 필드 추가(버전업 `version:2`) | JSON·버전 가드로 역호환 |

### 4.3 분리 Phase로 미루는 스키마(요약만)

- **P7 LPR/얼굴**: `plates`(plate_text/region/conf/track/event_id), `plate_lists`(allow/deny), `faces`(embedding BLOB/vector), `persons`(이름/동의/보존), `face_matches`. 벡터검색(pgvector 불가→ MySQL은 외부 인덱스 or sqlite-vss/FAISS 사이드카) — **P7에서 결정**.
- **P8 다중 NVR**: `sites`(원격 NVR 등록·토큰), `site_cameras`(통합 카탈로그), 통합 검색 fan-out 캐시. 
- **P9 원격 포털**: `relay_sessions`, `turn_credentials`(단명), `device_tunnels`.
- **P10 출입통제**: `access_controllers`, `doors`, `card_holders`, `access_events`, `access_schedules`.

---

## 5. 백엔드 설계 (기능군별 API·서비스·드라이버 영향 요약)

> 공통: `/api/v1` prefix, `Authorization: Bearer`(공유링크만 예외=scoped share 토큰), `@login_required`+`@permission_required('<perm>')`, 카메라 스코프 교집합, 페이지네이션 ams 호환(`page/items_per_page/sort/order/q`). 무거운 작업(아카이브/워터마크 transcode/임베딩 인덱싱)은 Celery 위임.

### 5.1 신규 권한키(P0 권한맵 추가)

`audio:talk`(양방향오디오), `masks:read/update`, `share:create/manage`, `bookmarks:read/update`, `archive:read/run`, `ai:count`, `ai:semantic_search`, `ai:audio`, `ptz:autotrack`, `maps:read/update`. (SSOT §12.2 P6+ 카탈로그. LPR/얼굴/출입통제/다중NVR 권한키는 각 후속 Phase.) admin 전권.

### 5.2 라이브 고급 API/서비스

| Method | Path | 권한 | 요지 |
|---|---|---|---|
| POST | `/cameras/{uuid}/talk/offer` | `audio:talk` | WebRTC SDP offer→go2rtc backchannel 협상(sendrecv). 동시화자 락(Redis) |
| POST | `/cameras/{uuid}/talk/stop` | `audio:talk` | 통화 종료·락 해제 |
| GET/PUT | `/cameras/{uuid}/privacy-masks` | `masks:read/update` | 마스크 CRUD. 카메라 OSD 마스크는 driver로 푸시 |
| GET/PUT | `/cameras/{uuid}/fisheye` | `cameras:update` | 디워핑 파라미터(중심/반경/모드) 저장. 렌더는 클라이언트 |
| POST | `/cameras/{uuid}/autotrack` | `ptz:autotrack` | 오토트랙 on/off(지원 카메라). 폐루프는 워커 |
| GET/PUT | `/dashboards/{uuid}/sequence` | `dashboards:update` | 시퀀스(순서/dwell)·event_spotlight·map 설정(layout JSON v2) |
| GET/PUT | `/maps` , `/maps/{id}/markers` | `maps:read/update` | 지도/평면도·카메라 핀·FOV 정의 |

- **서비스**: `service/talk_session.py`(backchannel 세션·동시성 락), `service/privacy_mask.py`(좌표 검증·OSD 푸시·burn 파라미터), `service/dewarp.py`(파라미터 검증·프리셋). 
- **드라이버**: `driver/onvif`·`driver/isapi`·`driver/sunapi`에 **양방향오디오 backchannel 경로 탐색**·**카메라 OSD 프라이버시 마스크 set/get**(ISAPI `PrivacyMask`, SUNAPI `privacy.cgi`, ONVIF는 제한적) 메서드 추가. 디워핑/오토트랙은 카메라 내장 기능이면 드라이버, 아니면 서버/클라이언트.
- **go2rtc**: `go2rtc_sync`가 backchannel 활성 카메라에 대해 stream 설정에 backchannel/오디오 출력 경로 주입(P1 동기화 확장).

### 5.3 녹화/재생 고급 API/서비스

| Method | Path | 권한 | 요지 |
|---|---|---|---|
| POST/GET | `/share-links` , `/share-links/{id}` | `share:create/manage` | 공유 링크 발급/관리(만료·비밀번호·워터마크·max_views) |
| GET | `/s/{token}` (공유 뷰어) | (share 토큰) | 비회원 열람 엔드포인트(클립/라이브/이벤트). 비밀번호 검증·조회수 차감 |
| GET/POST/DELETE | `/bookmarks` | `bookmarks:read/update` | 북마크 CRUD, 타임라인·검색 표면화 |
| POST | `/exports` (확장) | `clips:export` | P2 export에 `watermark/password` 옵션 추가(transcode 경로) |
| GET/POST | `/archive-targets` , `/archive-jobs` | `archive:read/run` | 아카이브 대상·작업(상태/진행률) |
| PUT | `/cameras/{uuid}/dual-recording` | `recordings:control` | 이중녹화(main/sub·보존등급) 정책 |

- **서비스**: `service/share_link.py`(scoped `share` 토큰 발급·검증·rate limit), `service/archiver.py`(대상 추상: S3/SMB/NFS, manifest 생성·복원 인덱스), `service/dual_recording.py`(P2 recorder에 sub 트랙 추가 지시). 
- **드라이버**: `driver/archive_s3.py`·`driver/archive_smb.py`·`driver/archive_nfs.py`(자격증명 암호화 사용). 엣지녹화(R6)는 `driver/{isapi,sunapi,onvif}`에 **Replay/SD 클립 조회**(ISAPI `ContentMgmt/search`, ONVIF Replay/Search) 추가.
- **Celery**: `task/archive.py`(스트리밍 업로드·재시도·체크섬), `task/transcode.py` 확장(워터마크 drawtext·암호 컨테이너).

### 5.4 AI 고급 API/서비스

| Method | Path | 권한 | 요지 |
|---|---|---|---|
| GET | `/search/semantic` | `ai:semantic_search` | 자연어 질의→CLIP 임베딩 매칭→썸네일/이벤트 결과 |
| POST | `/search/semantic/reindex` | `ai:semantic_search`(admin) | 임베딩 인덱싱(범위/카메라) 잡 트리거 |
| GET/PUT | `/cameras/{uuid}/counting` | `ai:count` | 카운팅 라인/영역 정의 |
| GET | `/analytics/counting` | `ai:count` | occupancy/in-out 시계열 조회 |
| (정책) | `event_policies`에 `loitering/count/occupancy/audio_class/smoke` 행 | `policies:update` | 신규 이벤트 타입 정책 |

- **워커(P4 detector 확장, runway_monitor 자산 재사용)**:
  - **시맨틱검색(A1)**: ams `worker/runway_monitor/clip_filter.py`의 `CLIPModel`/`CLIPProcessor` 로직 재사용 → `worker/detector/semantic.py`. 두 경로: ① **이벤트/detection 크롭 임베딩**을 저장(검색 인덱스), ② 질의 텍스트 임베딩과 코사인 유사도. 인덱스는 MVP에서 MySQL+근사(소규모) 또는 FAISS/sqlite-vss 사이드카(중규모). 
  - **카운팅/배회(A2/A3)**: `tracker.py`(track id)·`zones.py`(영역) 재사용 → 라인 통과 카운트·영역 dwell 시간 계산. 배회는 P3 `loitering` 이벤트로 발행.
  - **오디오(A4)**: go2rtc 오디오 추출(ffmpeg)→경량 분류(YAMNet/PANNs) `worker/detector/audio.py`. CPU 가능, 별 파이프.
  - **연기/동물/택배(A5/A6)**: detector 모델/클래스 확장.
- **공통**: 모든 AI 결과는 P3 `events`(+P4 `detections`)로 정규화 적재 → 검색·규칙(P5)·알림 재사용(중복 파이프 금지).

### 5.5 관리/확장 API/서비스

| Method | Path | 권한 | 요지 |
|---|---|---|---|
| POST | `/cameras/batch` | `cameras:create` | 다중 카메라 일괄 생성(공통 자격증명/CSV)→프로빙 잡 |
| POST | `/cameras/discover/batch-add` | `cameras:create` | 디스커버리 결과 다중선택 추가(P1 보강) |
| GET/PUT | `/feature-flags` | admin | 기능 토글 |
| (분리) | `/sites/*`(P8), `/relay/*`(P9), `/access/*`(P10) | 후속 | 다중NVR/원격/출입통제 |

- **서비스**: `service/batch_onboard.py`(P1 프로빙을 잡 큐로 병렬), `service/feature_flag.py`(캐시·무효화). 도어벨(M3)은 `driver/sip.py`(또는 P5 SIP 스피커 확장) + call 이벤트(P3)→통화 UI(L1 재사용)→문열기(P5 IO).

---

## 6. 라이브 고급 (양방향오디오·마스킹·디워핑·시퀀스/자동전환·지도·오토트랙)

### 6.1 L1 — 양방향 오디오(go2rtc backchannel) · High · M

- **무엇**: 웹/모니터에서 카메라 스피커로 말하고(half/full duplex), 카메라 마이크 수신. 인터컴·도어벨의 기반.
- **핵심 접근**: 라이브는 이미 WebRTC(P1). 양방향은 **go2rtc backchannel**(WebRTC `sendrecv`)을 사용 — go2rtc가 카메라의 ONVIF backchannel/벤더 2-way 오디오 경로로 전달. 프론트는 `getUserMedia(audio)`→peer connection에 트랙 추가, `POST /talk/offer`로 협상. **동시화자 1인 락**(Redis `axp:talk:{camera_id}`), 권한 `audio:talk`, 카메라 `two_way_audio=true`(P1 capability) 게이트. 코덤은 go2rtc가 협상(보통 PCMU/PCMA, OPUS↔G.711 트랜스코드 필요 시 go2rtc).
- **의존성**: P1(streams/audio cap·go2rtc_sync), P0(scope/권한), go2rtc backchannel 빌드.
- **데이터/엔드포인트**: `cameras.two_way_audio`(존재) 동작화, `streams.is_backchannel`(신규), `/cameras/{uuid}/talk/offer|stop`. 
- **리스크**: 벤더별 backchannel 경로/코덤 편차(특히 ONVIF), 에코·지연. → capability 프로빙 강화, half-duplex 기본, push-to-talk UI.

### 6.2 L2 — 프라이버시 마스킹 · High · M

- **무엇**: 영상 일부 영역을 가려 사생활 보호(창문/이웃집/키패드). 라이브·녹화·내보내기에 일관 적용.
- **핵심 접근**: 3계층(`privacy_masks.mode`):
  1. **camera_osd**(권장·근본): 카메라 펌웨어 OSD 프라이버시 마스크를 드라이버로 set(ISAPI `PrivacyMask`, SUNAPI privacy, ONVIF 제한적) → 녹화·라이브 모두 굽혀짐(불가역, 강한 프라이버시).
  2. **server_render**(유연): 좌표(0–1, P3 region 규약 재사용)를 클라이언트가 라이브/재생 위에 오버레이로 가림(권한자만 해제 볼 수 있음). 원본은 보존 → 사후 권한자 열람 가능(법·운영 유연).
  3. **burn_export**: 내보내기 시 transcode로 마스크를 굽음(공유·증거 제출용).
- **의존성**: P1(드라이버 OSD), P2(내보내기 burn), P4 오버레이 레이어(렌더 공유), P0(권한 `masks:update`, 해제 권한).
- **데이터/엔드포인트**: `privacy_masks`(신규), `/cameras/{uuid}/privacy-masks`. burn은 `export_jobs` 옵션.
- **리스크**: server_render는 클라이언트 우회 가능(원본 보존 시) → "강한 프라이버시"는 camera_osd/burn만 보장이라 UI에 명확 고지. 좌표↔실제 FOV 정합(PTZ 카메라는 프리셋별 마스크 필요 → 1차는 고정 카메라 한정).

### 6.3 L5 — 어안렌즈 디워핑(fisheye) · Med · M

- **무엇**: 360°/180° 어안 영상을 평면(파노라마/쿼드/가상 PTZ)으로 보정.
- **핵심 접근**: ① **카메라 내장 디워핑**(별 스트림/채널이면 P1 streams로 등록·선택 — 비용 0). ② **클라이언트 WebGL 디워핑**(원본 어안 + `fisheye_params`로 셰이더 변환, 가상 PTZ 인터랙션) — 서버 부하 0, 권장. 서버측 ffmpeg `v360` 디워핑은 온디맨드(썸네일/내보내기)만.
- **의존성**: P1(capability·streams), 라이브 플레이어.
- **데이터/엔드포인트**: `cameras.fisheye`/`fisheye_params`(신규), `/cameras/{uuid}/fisheye`. 
- **리스크**: 렌즈/마운트(천장/벽)별 파라미터 다양 → 프리셋 + 보정 UI. 클라이언트 GPU 부하(다수 타일).

### 6.4 L3/L4 — 시퀀스/순차회전 + 이벤트 자동전환 · High · S

- **무엇**: 대시보드 N개를 dwell 시간으로 순환(L3), 이벤트 발생 시 해당 카메라를 자동으로 큰 셀/전체로 전환(L4). 관제·로컬 모니터 핵심.
- **핵심 접근**: 순수 **프론트(+모니터 클라이언트)** 로직. `dashboards.layout` v2에 `sequence{order[],dwell_s}`·`event_spotlight{enabled,duration_s,priority}`. 이벤트 전환은 P3 `events` WS 채널 구독→우선순위 큐로 셀 스왑(쿨다운으로 깜빡임 방지). P5 모니터에도 동일 적용(scoped 토큰으로 WS 구독).
- **의존성**: P1(dashboards), P3(events WS), P5(monitors).
- **데이터/엔드포인트**: layout JSON 확장(스키마 변경 무), `/dashboards/{uuid}/sequence`.
- **리스크**: 이벤트 폭주 시 화면 난동 → dwell·쿨다운·우선순위·"수동 고정" 토글.

### 6.5 L6 — 지도 기반 모니터링 · Med · M

- **무엇**: 실내 평면도/실외 지도 위에 카메라 핀·FOV·실시간 이벤트 점멸, 핀 클릭→라이브/재생.
- **핵심 접근**: ams 프론트에 이미 있는 **leaflet/react-leaflet/maplibre-gl** 재사용(평면도는 leaflet ImageOverlay, 지도는 maplibre). `maps`(배경=업로드 이미지 또는 타일)·`map_markers`(camera_uuid·lat/lng 또는 x/y·heading·fov). 이벤트 WS로 핀 점멸(타입 색·DESIGN 절제). 핀 클릭→기존 라이브 플레이어 모달.
- **의존성**: P1(cameras), P3(events WS), DESIGN(절제된 단색), P0(권한 `map:*`).
- **데이터/엔드포인트**: `maps`/`map_markers`(신규), `/maps`·`/maps/{id}/markers`.
- **리스크**: 평면도 좌표계 관리·다층 건물. → 층별 맵 + 그룹.

### 6.6 L7 — GPU 디코딩 튜닝 · Med · M(△)

- **무엇**: HW 가속 디코드로 서버측 디코드 작업(썸네일·`/frame`·타임랩스·AI 입력) 경량화. 라이브는 클라이언트 디코드라 영향 적음.
- **핵심 접근**: ffmpeg `-hwaccel cuda|vaapi`(NVDEC/VAAPI), go2rtc HW 옵션. P4 GPU 토글과 **동일 토글 정책**(CUDA/CPU 자동·수동). 디코드 결과를 AI 워커에 zero-copy 전달(가능 시).
- **의존성**: P1·P2(디코드 작업), P4(GPU 토글 인프라).
- **데이터/엔드포인트**: `settings`(hwaccel 모드), 신규 테이블 없음.
- **리스크**: 드라이버/코덤(H.265 10bit) 호환·세션 한계. → CPU 폴백 자동, 프로브로 가용성 확인.

### 6.7 L8 — 객체 자동추적(PTZ auto-track) · Low · L(△)

- **무엇**: 움직이는 대상(사람/차량)을 PTZ가 자동 추종.
- **핵심 접근**: P4 detection+track(`track_id`)→대상 중심 오차→PTZ **continuous move**(P1) 폐루프(PID류) → 이탈/타임아웃 시 프리셋 복귀. 안전장치(속도 제한·금지영역·수동 우선).
- **의존성**: P1(PTZ continuous), P4(안정 track), P5(규칙 연계 선택).
- **데이터/엔드포인트**: `cameras.auto_track_enabled`(신규), `/cameras/{uuid}/autotrack`.
- **리스크**: 제어 루프 발진·다중 대상 혼선·기계 마모. → 보수적 튜닝, 카메라 내장 auto-track 있으면 그것 우선(드라이버 토글). **난도·리스크로 P6 후반/조건부.**

---

## 7. 녹화/AI/관리 고급 (이중·엣지·암호화·공유 / LPR·얼굴·카운팅·시맨틱 / 다중NVR·원격포털·백업)

### 7.1 녹화/재생 고급

**R1 공유 링크(비회원 열람) · High · M** — 클립/라이브/이벤트를 외부에 공유. `share_links`(토큰 해시·만료·비밀번호 해시·워터마크·max_views). `/s/{token}` 공개 뷰어는 **scoped `share` audience 토큰**(P0 확장)으로 해당 리소스만 접근(다른 API 불가). 비밀번호 검증·조회수 차감·취소. 라이브 공유는 WebRTC를 share 토큰으로 시그널. **리스크**: 토큰 유출 → 만료·max_views·비밀번호·워터마크·취소·rate limit. **데이터**: `share_links` 신규; P0 audience 확장; P2 playback/export 재사용.

**R2 북마크/라벨 · High · S** — 타임라인 임의 시점/구간에 라벨·색·메모. `lock_retention`=true면 P2 보존 잠금(`recordings.retention_class='protected'` 연계). 이벤트(P3)·검색 결과에서도 북마크 생성. **데이터**: `bookmarks` 신규. **리스크**: 낮음.

**R3 내보내기 워터마크/비밀번호 잠금 · High · M** — P2 `export_jobs` transcode 경로에 ffmpeg `drawtext`(사용자/시각/카메라 워터마크) + 산출물 **암호화**(AES-256 zip 또는 mp4 암호 컨테이너). copy 모드는 워터마크 불가(재인코딩 필요) → UI 안내. **데이터**: `export_jobs`에 옵션 컬럼. **리스크**: 재인코딩 비용 → 동시성 제한 큐(P2).

**R4 이중 녹화(해상도별) · Med · M** — main(고화질·단기)+sub(저화질·장기) 동시 세그먼트. P2 recorder가 카메라당 2 ffmpeg 세그먼터(또는 go2rtc 다중 출력) 운용, `segments.stream_role` 구분, 보존등급 차등(`storage_policies` 확장). 재생은 기본 main, 장기 구간은 sub 자동. **데이터**: `segments`/`recordings`에 `stream_role`/`quality_tier`. **리스크**: 디스크·CPU 2배 → 카메라별 토글, sub만 장기 권장. **P2 협의 필요(10절).**

**R5 녹화 암호화(at-rest) · Med · L(△)** — 두 방향: ① **디스크 단위(LUKS/dm-crypt, btrfs/ZFS 암호화)** — 성능 우수·seek/copy 무영향, 키 관리는 OS/HSM → **권장·가이드(M4와 연계)**. ② **앱 파일 단위** — 세그먼트 암호화 시 copy-내보내기·seek 비용 큼, 키 회전 복잡. **1차는 디스크 단위 가이드 + 옵션 플래그**. **데이터**: `segments.enc`/`recordings.enc_key_id`(앱 방식 시). **리스크**: 키 분실=데이터 영구 손실 → 키 백업 절차 문서화.

**R6 엣지 녹화(카메라 SD) · Low · L(△)** — 네트워크/NVR 장애 시 카메라 SD 녹화를 갭필·임포트. 드라이버에 SD 클립 검색/다운로드(ISAPI `ContentMgmt/search`+RTSP Replay, SUNAPI SD, ONVIF Replay/Search) → P2 타임라인에 "edge" 구간 병합·온디맨드 임포트. **데이터**: `recordings.reason='edge'`(또는 source 표기). **리스크**: 벤더별 Replay 편차·SD 신뢰성 → 갭 감지 시 임포트만(상시 미러 아님).

### 7.2 AI 고급

**A1 시맨틱 이미지 검색(CLIP 재활용) · High · M** — "빨간 옷 입은 사람", "흰색 트럭" 같은 자연어로 과거 영상 검색. **ams `clip_filter.py`의 CLIP 로직 직접 재사용**(`CLIPModel`/`CLIPProcessor`, GPU/CPU 자동). 인덱싱: 이벤트 스냅샷/detection 크롭(P3/P4)을 임베딩→저장. 질의: 텍스트 임베딩↔코사인 유사도 top-k→썸네일+이벤트/클립 점프. 인덱스 백엔드는 규모별(MVP MySQL 브루트포스→FAISS/sqlite-vss 사이드카). **데이터**: 임베딩 저장(이벤트/detection 확장 컬럼 또는 `embeddings` 테이블), `/search/semantic`. **리스크**: 임베딩 저장량·검색 지연 → 인덱싱 범위 제한(이벤트 우선)·배치·캐시. **P4 검색 인프라와 통합(중복 금지).**

**A2 사람/차량 카운팅 + occupancy · High · M** — 라인 통과 in/out 카운트 + 영역 점유수 시계열·혼잡 임계 알림. P4 `tracker.py`(track id)·`zones.py` 재사용. `counting_lines` 정의→워커가 통과/체류 계산→`counting_stats`(집계)·임계 초과 시 P3 `count/occupancy` 이벤트→P5 알림. **데이터**: `counting_lines`/`counting_stats` 신규, `events` enum 추가. **리스크**: 중복 카운트/오클루전 → track 안정성 의존(블로킹 확인), 양방향 라인·디바운스.

**A3 배회(loitering) · High · M** — 영역 내 동일 track dwell ≥ T → loitering. P3에 **enum 이미 예약됨**. 워커가 track별 영역 체류시간 누적→임계→이벤트. **데이터**: `events.type='loitering'`(예약), `event_policies` 행. **리스크**: track 끊김으로 dwell 리셋 → track 재연결/그레이스, 영역·시간 튜닝.

**A4 오디오 감지/분류 · Med · M(△)** — 개짖음/유리깨짐/비명/경보 등. go2rtc 오디오→ffmpeg 추출→경량 분류(YAMNet/PANNs) `worker/detector/audio.py`(CPU 가능, 별 파이프). 결과→`audio_detections`·P3 `audio_class` 이벤트→P5. **데이터**: `audio_models`/`audio_detections` 신규, `events` enum. **리스크**: 환경 소음 오탐·프라이버시(음성 저장) → 임계·클립 보존정책·동의 고지.

**A5 연기/화재 감지 · Med · M(△)** — 전용 모델(연기/불꽃 YOLO/분류). detector 모델 슬롯 추가. **리스크**: 안전 기능이라 **오탐·미탐 책임** 큼 → "보조 알림"으로 한정, 검증 데이터·임계, 법적 면책 고지. **A6 동물/택배 · Med · S** — YOLO 클래스 확장(dog/cat/bird, package)·존 연계(택배=현관 영역+package). 대부분 라벨/모델 작업.

**A7 LPR(번호판) · High · XL · ✅ 분리(Phase 7)** — 차량 검출→번호판 검출→정렬/투시보정→OCR(국가/지역 특화 모델)→`plates`(allow/deny 리스트·이벤트·검색). **분리 사유**: OCR 정확도·지역별 번호판 규격·전용 데이터/모델·성능(전용 파이프)로 단일 기능이 한 Phase 분량. P3에 `lpr` enum 예약됨. **A8 얼굴 인식 · Med · XL · ✅ 분리(Phase 7)** — 검출→정렬→임베딩→ANN 매칭→`persons`/`faces`. **분리 사유**: 벡터검색 인프라(FAISS/외부)·프라이버시·법규(동의/보존·삭제권)·정확도 튜닝. P3에 `face` enum 예약됨. **두 기능은 검출 단계(P4 detector)는 공유하나 후처리·DB·UI·법적 처리가 무거워 P7로 묶어 분리.**

### 7.3 관리/확장 고급

**M1 배치 카메라 추가(P1 보강) · High · S** — 디스커버리 결과 다중선택 + 공통 자격증명 일괄 적용 + CSV 임포트 → 병렬 프로빙 잡. P1 온보딩/프로빙 재사용, 진행률 표면화. **데이터**: 없음(잡 상태는 Redis/경량). **리스크**: 대량 동시 프로빙 부하 → 동시성 제한.

**M2 백업·아카이빙(클라우드/NAS) · High · M** — 보호/이벤트 클립을 S3/SMB/NFS로 비동기 아카이브 + manifest(복원 인덱스). `archive_targets`(자격증명 암호화)·`archive_jobs`. 정책(이벤트 자동 아카이브·보존만료 전 오프로드)·복원. P2 segments/recordings·storage_manager 재사용. **데이터**: `archive_targets`/`archive_jobs` 신규. **리스크**: 대용량 전송 비용·중단 재개 → 체크섬·재시도·대역 제한·증분.

**M3 도어벨/인터컴 · Med · M(△)** — SIP/ONVIF 도어벨 call 이벤트→통화 UI(L1 양방향오디오 재사용)→문열기(P5 IO). `driver/sip.py`(또는 P5 SIP 스피커 확장)·P3 `doorbell_call` 이벤트. **리스크**: SIP/벤더 편차·실시간 통화 품질.

**M4 RAID 스토리지 가이드 · Med · S** — 구현이 아니라 **가이드+상태 표면화**: mdadm/btrfs/ZFS RAID 구성 권고 문서 + SMART/degraded/재구축 상태를 disks 상태 패널에 표시(M5 암호화·R5와 연계). **데이터**: `disks` 상태 필드 활용(P2). **리스크**: 낮음(가이드).

**M5 다중 NVR 중앙관리·통합 뷰 · High · XL · ✅ 분리(Phase 8)** — 여러 온프레미스 NVR을 한 콘솔에서: 통합 카메라/이벤트/검색(fan-out)·SSO·정책 배포. **분리 사유**: 페더레이션 인증(P0 scoped/site 토큰 확장)·통합 검색 fan-out·버전 호환·네트워크 토폴로지로 **아키텍처 변경**. PLAN "단일 온프레미스(P6에서 다중NVR/원격 확장 설계)"에 맞춰 **P6은 설계만, 구현은 P8**.

**M6 원격 접속 포털(포워딩/VPN 불필요) · High · XL · ✅ 분리(Phase 9)** — 클라우드 릴레이로 NAT 뒤 NVR 접근. WebRTC는 **TURN**, 제어/시그널은 **리버스 터널/릴레이**(NVR이 아웃바운드로 릴레이에 상주). **분리 사유**: 릴레이 인프라 운영·E2E 보안·인증·과금/규모로 자체 Phase. **P6은 설계·보안 모델만**.

**M7 출입통제 도어 컨트롤러 · Low · L · ✅ 분리(Phase 10)** — Access 컨트롤러/리더·도어·카드/일정·출입기록. 별도 도메인(상용 출입통제 시스템급). **분리 사유**: 하드웨어·보안·도메인 규모. **M8 모바일 네이티브 앱 · Low · XL · ✅ 후속** — PWA(P5) 이후 RN/Flutter, 푸시·라이브 WebRTC. 전체 API 안정화 후.

### 7.4 알림/기타

**N1 SMS · Med · S** — P5 알림 채널 추상에 SMS 드라이버(ams **SOLAPI** 패턴 재사용). **N2 알림 통합/음소거 · Med · S** — 카메라/타입/시간창 snooze·동일 이벤트 grouping(스팸 억제). P5 규칙/알림에 정책 추가. **데이터**: P5 알림 모델 확장(또는 `notification_mutes`).

---

## 8. 프론트엔드(TS) (기능군별 화면 영향 요약·DESIGN.md 적용)

> React 18 + Vite 7 + TS + Tailwind + Radix/shadcn + TanStack + dnd-kit. ams 패턴(페이지별 디렉터리, `@`=`src/`, Axios+JWT 인터셉터, i18n ko/en). DESIGN **Tesla 미니멀**: 흰 캔버스·사진/영상 우선, 그림자·그라데이션·테두리 지양, 단일 액센트 **Electric Blue `#3E6AE1`**(주 CTA·활성), 4px 라운드, 0.33s 트랜지션, 텍스트 Carbon `#171A20`/Graphite `#393C41`/Pewter `#5C5E62`. 영상이 주인공이므로 컨트롤은 hover 시 절제되게 노출.

| 기능군 | 신규/변경 화면(`frontend/src/pages/...`) | DESIGN 적용 요지 |
|---|---|---|
| 라이브 고급 | `live/` 확장: 양방향오디오 **PTT 버튼**(활성=Electric Blue, 통화중 표시), `MaskOverlay`(server_render), `FisheyeViewer`(WebGL·가상PTZ 드래그), 시퀀스/스포트라이트 컨트롤, `pages/maps/`(leaflet/maplibre 핀·FOV·이벤트 점멸) | 컨트롤 최소·hover 노출, 이벤트 점멸은 점멸 대신 0.33s 페이드 단색 |
| 녹화/재생 고급 | `playback/` 북마크 마커·라벨, `ShareLinkModal`(만료/비번/워터마크 토글), 내보내기 모달에 워터마크/비번 옵션, `pages/share/`(비회원 뷰어=초미니멀, 브랜딩 최소) | 북마크 마커=절제된 색 틱, 공유 뷰어는 영상 전면·UI 거의 없음 |
| AI 고급 | `pages/search/` **시맨틱 검색바**(자연어 입력→썸네일 그리드, 2:1·12px 라운드·overflow hidden 카드), `analytics/counting/`(occupancy 차트=ApexCharts 톤다운), 카운팅 라인 에디터(영상 위 dnd) | 썸네일 그리드가 주인공(DESIGN 카드 규칙), 차트 단색·격자 최소 |
| 관리/확장 | `cameras/` 배치추가 마법사(다중선택·CSV), `pages/archive/`(대상·작업·진행률), `settings/feature-flags`, (분리) sites/relay/access 자리 | 진행률 바 Electric Blue, 테이블 TanStack·테두리 최소 |

- **공유 컴포넌트 재사용**: 마스킹/카운팅 라인/디워핑 편집은 P3 모션 오버레이·P1 레이아웃 에디터의 **좌표 오버레이/드래그 패턴 재사용**(ResizeObserver로 영상 표시영역 스케일). 지도는 ams `AircraftMap.jsx`/`leaflet.js` 플러그인 패턴 참고.
- **i18n/접근성**: 신규 라벨 ko/en, 시각 KST 표시(저장 UTC), 터치 타깃 ≥44px, PTT/오토트랙 등 위험 동작은 명시적 확인.

---

## 9. 작업 분해 (기능군별 우선순위·후속 Phase 분리 권고)

> P6는 백로그이므로 **웨이브(wave) 단위**로 점진 착수. 각 웨이브는 단독 시연 가능. High·저난도·기반 재사용부터.

**Wave 1 — 빠른 패리티(High·S/M, 기반 재사용 큼)**
1. L3 시퀀스 + L4 이벤트 자동전환(layout v2, S) — 프론트 위주.
2. R2 북마크/라벨(S) + R1 공유 링크(M, P0 share audience 확장 선행).
3. M1 배치 카메라 추가(S, P1 보강).
4. A1 시맨틱검색(M, ams CLIP 재사용·P4 인덱스 통합).
5. L1 양방향오디오(M, go2rtc backchannel·동시화자 락).

**Wave 2 — 차별화(High/Med·M)**
6. L2 프라이버시 마스킹(camera_osd+server_render, M).
7. A2 카운팅/occupancy + A3 배회(M, P4 track 재사용·`loitering` enum 활용).
8. M2 백업/아카이빙(M).
9. R3 내보내기 워터마크/비번(M).
10. L6 지도 모니터링(M, leaflet/maplibre 재사용).

**Wave 3 — 비용/리스크 중간(Med·M/L)**
11. L5 디워핑(클라이언트 WebGL), L7 GPU 디코딩 튜닝.
12. R4 이중녹화(P2 협의), R5 암호화(디스크 단위 가이드+옵션), M4 RAID 가이드.
13. A4 오디오 분류, A5 연기, A6 동물/택배.
14. M3 도어벨/인터컴, N1 SMS, N2 알림 음소거.

**Wave 4 — 고난도/조건부(Low·L)**
15. L8 PTZ 오토트랙, R6 엣지녹화.

**별도 Phase 분리 권고(P6에서 설계만, 구현은 후속):**
- **Phase 7 — LPR & 얼굴 인식**(A7+A8): OCR/임베딩·벡터검색·프라이버시·법규.
- **Phase 8 — 다중 NVR 중앙관리/통합 뷰**(M5): 페더레이션·통합 검색.
- **Phase 9 — 원격 접속 포털**(M6): TURN/릴레이·리버스 터널.
- **Phase 10 — 출입통제**(M7): Access 도메인.
- **후속 — 모바일 네이티브 앱**(M8).

> PLAN 9·10절(로드맵·매핑)에 위 분리 Phase를 반영 권고(14절 Q에 포함).

---

## 10. 다른 기능/Phase에 미치는 영향 (Cross-feature Impact) ★

> P6 기능이 P0~P5 계약에 요구하는 변경. **원칙: 기존 동작 역호환, 신규는 feature flag로 격리, 신규 컬럼은 default로 무영향.**

| 대상(소유) | 영향 | 조치(마이그레이션·플래그·합의) |
|---|---|---|
| **P0 인증** | 공유링크용 **scoped `share` audience** 토큰 신설(특정 리소스만, 다른 API 불가). 다중NVR/원격은 **site/federation 토큰**(P8/P9). | P0 token 서비스에 `share` audience·claims(resource_ref/expiry/max_views) 추가. 검증 미들웨어 분기. |
| **P0 권한맵** | 신규 권한키 다수(5.1). | 권한맵 JSON·권한 편집 UI에 키 추가, admin 전권. |
| **P0 settings/flags** | `feature_flags`로 전 기능 토글. | 신규 `feature_flags` 테이블 또는 settings KV + 캐시 무효화. |
| **P0 WS 허브** | 자동전환·지도·카운팅 실시간은 기존 `events` 채널 재사용(신규 채널 최소화). | 페이로드에 spotlight/카운트 요약 추가(스키마 가산). |
| **P1 cameras/streams** | `two_way_audio`/`audio_supported`(존재) **동작 연결**; 신규 `fisheye/fisheye_params/auto_track_enabled/edge_recording`(cameras), `is_backchannel`(streams). capabilities JSON에 `audio.output`·`dewarp`·`privacy_mask`·`backchannel` 표면화. | nullable/default → 기존 영향 없음. capability_probe가 backchannel/OSD마스크/dewarp 지원 탐지(P1 프로빙 확장). |
| **P1 드라이버** | onvif/isapi/sunapi에 **backchannel 경로·OSD 프라이버시 마스크 set/get·SD Replay 검색·(선택) 카메라 디워핑/auto-track 토글** 메서드 추가. | 드라이버 인터페이스 확장(역호환: 신규 메서드, 미지원은 capability=false). |
| **P1 go2rtc 동기화** | backchannel 활성 카메라 stream 설정에 backchannel/오디오 출력 주입. 이중녹화 시 sub 출력 추가. | `go2rtc_sync` 확장(설정 생성 분기). |
| **P1 dashboards.layout** | `sequence`/`event_spotlight`/`map` 필드(layout JSON **v2**). | 버전 가드(v1 읽기 호환), 마이그레이션은 lazy(읽을 때 v2 기본 주입). |
| **P2 recordings/segments** | **이중녹화**: `stream_role`/`quality_tier` 추가, 동일시간 복수행 허용·인덱스. **암호화**: `enc`/`enc_key_id`. **엣지**: `reason='edge'`/source. **워터마크/암호**: `export_jobs` 옵션 컬럼. | **P2 소유자 합의 필요**(컬럼 추가·인덱스·reason enum 확장). default로 역호환. 고빈도 `segments` 컬럼 추가는 신중(가능하면 별 테이블/메타). |
| **P2 recorder/supervisor** | 이중녹화 시 카메라당 2 세그먼터(또는 go2rtc 다중출력). 보존정책 차등. | P2 recorder가 stream_role별 녹화 지원하도록 확장 합의. |
| **P2 storage_policies** | 이중녹화 보존등급·아카이브 오프로드(보존만료 전 외부 이전) 정책. | 정책 컬럼 추가(quality_tier 보존·archive_before_delete). |
| **P2 export/transcode** | 워터마크 drawtext·산출물 암호화 옵션. copy 모드는 미지원 고지. | `task.transcode` 확장, `export_jobs` 옵션. |
| **P2 playback/타임라인** | 북마크·엣지·이중녹화 트랙을 타임라인에 표면화. 공유링크는 playback 재사용. | 타임라인 응답에 bookmark/edge/tier 마커 가산. |
| **P3 events enum** | `loitering`(예약) 활성 + `count`/`occupancy`/`audio_class`/`smoke`/`doorbell_call` 추가. `face`/`lpr`은 P7. | enum=VARCHAR → 값 추가만(스키마 불변). event_policies 행 추가. |
| **P3 정규화/오버레이** | 마스킹 좌표·카운팅 라인·배회 영역이 P3 region(0–1) 규약·오버레이 레이어 재사용. | 좌표 유틸·렌더 공유(중복 금지). |
| **P3 구독/파이프라인** | 오디오/연기/카운팅 결과를 P3 `events`로 적재(AI도 P3 enum·outbox 경유). | detection→event 정규화 경로 재사용(P4와 합의). |
| **P4 detector** | **CLIP 임베딩(시맨틱)**·카운팅/배회 track·오디오/연기/동물 모델·오토트랙 track·LPR/얼굴 검출 단계가 모두 P4 워커 확장. 검색 인프라(임베딩 인덱스)는 **P4와 통합**(중복 금지). | P4 detector에 모델/파이프 슬롯·프레임/크롭 접근 API·임베딩 출력 합의(블로킹). GPU 토글 정책 공유(L7). |
| **P4 detections** | 카운팅/배회는 `track_id` 안정성 의존. 임베딩 저장 위치(detections 확장 vs `embeddings` 테이블). | track id 계약 확인, 임베딩 저장 설계 P4와 합의. |
| **P5 규칙/알림** | 혼잡/배회/오디오/연기/도어벨이 **규칙 트리거**(기존 trigger/condition/action 재사용). SMS 채널·grouping/snooze는 알림 추상 확장. 자동전환은 모니터(P5)에도 적용. | P5 알림 채널 인터페이스에 SMS 드라이버, 음소거/그룹 정책 추가. 규칙 trigger에 신규 이벤트 타입 노출. |
| **P5 모니터** | 시퀀스/자동전환·지도가 모니터 클라이언트(scoped 토큰)에서 동작. | 모니터 토큰으로 WS·layout v2 구독 허용. |
| **보존/스토리지** | 카운팅 시계열·임베딩·오디오 클립·아카이브가 추가 저장 증가. | 보존정책·집계 다운샘플·임베딩 인덱싱 범위 제한. |
| **PLAN.md** | 분리 Phase(P7~P10·모바일) 신설·매핑 갱신. | 9·10절 로드맵·매핑에 반영(14절 Q). |

---

## 11. 리스크 & 완화

| 리스크 | 영향 | 완화 |
|---|---|---|
| **범위 과대(전 기능 동시 추진)** | 미완·품질저하·회귀 | 웨이브·우선순위 엄수, High·기반재사용부터, 큰 기능 **별도 Phase 분리**(LPR/얼굴/다중NVR/원격/출입통제) |
| 벤더별 backchannel/OSD마스크/SD Replay 편차 | 양방향오디오·마스킹·엣지 미지원 다발 | capability 프로빙 강화, 미지원 명확 고지, ONVIF 폴백·기능 게이트 |
| AI 오탐/미탐(연기·LPR·얼굴·카운팅) | 안전·법적·신뢰 문제 | "보조" 한정·임계/검증 데이터, 안전기능 면책 고지, track 안정성 의존 항목은 사전 검증 |
| 프라이버시·법규(얼굴/오디오/마스킹 우회) | 컴플라이언스 위반 | 강한 프라이버시는 camera_osd/burn만 보장 고지, 얼굴/음성은 동의·보존·삭제권(P7 별도), 감사 로그 |
| 공유링크/원격포털 노출면 확대 | 무단 접근·SSRF·릴레이 남용 | scoped 토큰(리소스 한정)·만료·max_views·비번·워터마크·rate limit·취소; 원격은 E2E·아웃바운드 전용·인증 강화(P9) |
| 이중녹화·워터마크·아카이브 자원 | CPU/디스크/네트워크 2배+ | feature flag·동시성 제한 큐·sub만 장기·증분/대역제한 아카이브·HW 디코드(L7) |
| 암호화 키 분실 | 데이터 영구 손실 | 디스크단위(OS/HSM) 권장·키 백업 절차 문서화, 앱 암호화는 옵션 |
| P4/P5 문서 미확정(계약 변동) | 통합 재작업 | 착수 전 블로킹 계약 확인(3절), enum/시그널 예약 활용, 어댑터로 결합 |
| go2rtc backchannel 빌드/코덤 | 양방향오디오 불가 | 빌드 옵션 확인, half-duplex 기본, 트랜스코드(go2rtc) 폴백 |
| 자격증명 평문 노출(아카이브 대상·카메라) | 보안 | P0 암호화 저장만, 로그/응답 마스킹, 내부 URL 비노출 |

---

## 12. 테스트 계획 (개략)

> P6 기능별로 P0~P5와 동일 기준(unit/integration/e2e + 회귀). 본 절은 기능군 대표 케이스(개략).

**Unit**
- 좌표/도형: 마스크·카운팅 라인·디워핑 파라미터의 0–1 정규화·검증·경계.
- 공유링크 토큰: 만료·max_views·비번 검증·권한 범위(다른 리소스 거부).
- 카운팅/배회 로직: 라인 통과(in/out)·dwell 누적·디바운스(mock track).
- CLIP 임베딩: clip_filter 재사용 함수의 임베딩/유사도(소형 fixture).
- feature flag·권한키 게이트.

**Integration (DB+Celery eager + mock driver/worker)**
- 양방향오디오: offer→go2rtc(mock) 협상·동시화자 락.
- 마스킹: camera_osd 드라이버 push(mock)·server_render 메타·burn export 옵션.
- 아카이브: recordings→S3/SMB(mock) 업로드·manifest·재시도·복원.
- 시맨틱검색: 인덱싱 잡→질의 top-k(소형 임베딩 셋).
- 카운팅/배회/오디오/연기: 워커(mock 프레임/track)→P3 events 적재→P5 규칙 트리거.
- 이중녹화: stream_role별 segments 생성·차등 보존(P2 mock).

**e2e (Playwright)**
- 시퀀스/자동전환: 이벤트 주입→스포트라이트 셀 전환.
- 공유링크: 발급→비회원 뷰어 열람(비번)→만료/취소 후 거부.
- 시맨틱 검색: 질의→썸네일 그리드→클립 점프.
- 양방향오디오: PTT 통화 시작/종료(mock 미디어).
- 지도: 핀 클릭→라이브, 이벤트 점멸.

**회귀(필수)**: P1 라이브/PTZ/온보딩, P2 녹화/재생/내보내기/보존, P3 이벤트/스케줄, P4 검색/detection, P5 규칙/알림/모니터가 P6 기능 on/off 양쪽에서 정상. 특히 **flag off 시 P0~P5 성능·동작 무변화**를 회귀로 보증.

---

## 13. 성능·보안 체크포인트

**성능**
- **flag off = 비용 0**: 모든 신규 워커/인덱싱/이중녹화는 토글 off 시 기존 파이프에 영향 없음(별 큐·별 워커·조건부 적재).
- 무재인코딩 원칙 유지: 마스킹 server_render·디워핑·시퀀스는 클라이언트 렌더(서버 디코드 회피). 워터마크/암호/타임랩스만 재인코딩(동시성 제한 큐).
- 임베딩/카운팅/오디오는 **별 큐**(P4/P5 큐와 격리), 인덱싱 범위 제한(이벤트 우선)·배치·다운샘플 집계.
- 이중녹화·아카이브는 자원 2배 → 카메라별 토글·sub 장기·증분/대역제한.
- HW 디코드(L7)로 서버측 디코드 작업 경감, CPU 폴백 자동.
- 신규 조회는 인덱스 설계(`(camera_id,*_ts)`)·페이지네이션·기간 상한, N+1 회피(`selectinload`).

**보안**
- 모든 신규 API `@login_required`+세부 권한+**카메라 스코프 교집합**. 공유링크만 scoped `share` 토큰(리소스 한정).
- 공유링크/원격포털: 만료·max_views·비번·워터마크·취소·rate limit; 원격은 아웃바운드 전용·E2E·인증 강화(P9).
- 자격증명(카메라·아카이브 대상): P0 암호화 저장만, 복호화 메모리 한정, 로그/응답/raw 마스킹, 내부 URL 비노출.
- 프라이버시: 강한 마스킹은 camera_osd/burn만 보장 고지; 얼굴/오디오는 동의·보존·삭제권·감사(P7 별도 처리).
- 입력 검증(좌표·기간·enum 화이트리스트), 파일/경로 안전(아카이브 path traversal 방지), XML/외부 파서 XXE 방지.
- 양방향오디오·문열기·오토트랙 등 **물리 영향 동작**은 권한+명시 확인+감사 로그.
- 패키지 최신 stable(go2rtc·ffmpeg·CLIP/torch·leaflet/maplibre·archive SDK), 취약점 점검.

---

## 14. 미해결 질문 / 결정 필요 사항

- **Q1. 분리 Phase 확정**: LPR/얼굴(P7), 다중NVR(P8), 원격포털(P9), 출입통제(P10), 모바일(후속)을 PLAN 로드맵에 정식 신설할지(권장). 우선순위·순서는?
- **Q2. P4 검색/임베딩 인프라**: 시맨틱검색·얼굴의 벡터검색 백엔드(MySQL 브루트포스 vs FAISS/sqlite-vss 사이드카 vs 외부 벡터DB). P4와 통합 지점·임베딩 저장 위치(detections 확장 vs `embeddings` 테이블).
- **Q3. 이중녹화 모델**: `segments`에 `stream_role` 추가(고빈도 테이블 영향) vs 카메라당 별 세그먼트 네임스페이스. P2 recorder가 stream_role별 녹화를 1차 지원하는지.
- **Q4. 녹화 암호화 방식**: 디스크 단위(LUKS/btrfs/ZFS, 권장·가이드) vs 앱 파일 단위(seek/copy 비용). 키 관리(OS/HSM/앱) 정책.
- **Q5. go2rtc backchannel**: 사용 빌드의 backchannel 지원·타깃 Hanwha/Hikvision 모델군 2-way 오디오 경로·코덤(트랜스코드 필요 여부).
- **Q6. 프라이버시 강도 정책**: server_render(원본 보존·권한 해제) 허용 범위 vs 규제상 camera_osd/burn 강제 대상. 얼굴/오디오 저장 동의·보존기간.
- **Q7. 공유링크 audience**: P0 토큰에 `share` audience·claims(resource/expiry/max_views/password)를 신설하는 형태 확정.
- **Q8. 원격포털 토폴로지**: 셀프호스트 릴레이 vs 매니지드. TURN/시그널 릴레이 운영·과금·보안 모델(P9 상세).
- **Q9. 엣지녹화 범위**: 갭필 임포트만(권장) vs 상시 미러. 벤더 Replay 지원 매트릭스.
- **Q10. 오토트랙 우선순위**: 카메라 내장 auto-track(드라이버 토글) vs 서버 폐루프. 안전 한계·금지영역 정책.

> 확정 시 본 문서 해당 절 + `../PLAN.md`(7장 데이터 모델·9·10장 로드맵/매핑) + 분리 시 신규 `plan/phase-7.md…` 에 반영한다.
