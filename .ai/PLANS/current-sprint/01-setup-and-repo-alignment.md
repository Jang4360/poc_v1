# 01 저장소 정렬 및 실행 기반 정비

## 워크스트림

`구현 기반 정렬`

## 목표

부산 이음길 MVP가 Spring Boot + PostGIS + ETL + GraphHopper 기준선 위에서 일관되게 진행되도록 저장소 구조, 실행 경계, 이름 규칙을 정리한다.

## 범위

- `PostgreSQL + PostGIS`를 정규 데이터 저장소로 고정
- `poc/`를 백엔드 시작점으로 명확화
- `db/` 정규 DDL과 `etl/` 파이썬 적재 스크립트 골격 정리
- `graphhopper-plugin/` 및 Docker 실행 경계 정리
- 장애 유형, 경로 옵션, GraphHopper 프로필 명명 규칙 확정
- MVP 범위와 V2 범위 분리

## 비목표

- 전체 경로 API 구현
- 실제 ETL 적재 로직 완성
- Android 앱 완성

## 입력 근거

- `docs/prd.md`
- `docs/기능명세서.md` 또는 현재 기능 명세 문서
- `docs/erd.md`
- `docs/erd_v2.md`
- `.env`
- `poc/`
- `etl/raw/`

## 성공 기준

- [x] 런타임 기준선을 `PostgreSQL + PostGIS`로 고정한다.
- [x] 백엔드, ETL, GraphHopper 경계가 저장소에서 명시된다.
- [x] DB 스키마 소유권과 Spring/ETL 사용 방식이 명확히 분리된다.
- [x] MVP POC 초기 DDL에서 생성할 테이블 목록이 명시된다.
- [x] `DisabilityType`, `RouteOption`, GraphHopper 프로필 명명 규칙이 구현 기준으로 정리된다.
- [x] GraphHopper는 HTTP 서비스로 취급되고 `road_segments`가 이후 워크스트림의 네트워크 기준 테이블로 유지된다.
- [x] Docker Compose 기준 전체 기동 검증 계획이 정리된다.

## DB 스키마 소유권

- 정규 DDL의 canonical location은 `db/schema.sql`로 둔다.
- `etl/`은 Python 적재 로직과 원천 데이터 변환을 담당하며, DB 스키마의 소유자가 아니다.
- Spring Boot는 MVP POC에서 테이블을 자동 생성하지 않는다.
  - `spring.jpa.hibernate.ddl-auto=validate` 또는 동등한 검증 모드로 기존 스키마와 엔티티 매핑을 확인한다.
  - Spring이 사용하는 엔티티/Repository는 `db/schema.sql`로 생성된 테이블을 전제로 한다.
- Docker Compose의 PostGIS 초기화는 `db/schema.sql`을 마운트하거나 명시 실행한다.
- ETL과 Spring이 같은 테이블을 바라보도록 컬럼명은 `docs/erd_v2.md`의 camelCase를 우선한다. 실제 SQL에서 snake_case를 선택할 경우에는 별도 결정 문서가 필요하다.

## 생성 대상 테이블

`db/schema.sql`은 현재 MVP POC 구현에 필요한 다음 테이블만 생성한다.

- 장소 도메인: `places`, `place_accessibility_features`
- 보행 네트워크 도메인: `road_nodes`, `road_segments`, `segment_features`
- 대중교통 도메인: `low_floor_bus_routes`, `subway_station_elevators`

사용자 계정, 북마크, 자주 가는 길, 제보, 경로 로그 테이블은 이번 POC의 초기 DDL 범위에서 제외한다. 해당 기능을 구현할 때 별도 워크스트림에서 ERD와 DDL을 확장한다.

## 구현 계획

- [x] 기본 Spring Boot 식별자를 부산 이음길 기준으로 치환한다.
  - `group`: `kr.ssafy.ieumgil`
  - 애플리케이션 이름: `ieumgil-backend`
  - Java 패키지: `kr.ssafy.ieumgil.backend`
- [x] 백엔드 기준 의존성과 런타임 설정을 정리한다.
  - `spring-boot-starter-actuator`
  - `hibernate-spatial`
  - `jts-core`
  - datasource, health, GraphHopper base URL 설정
- [x] 백엔드 컨테이너 패키징을 추가한다.
  - `poc/Dockerfile`
  - `/actuator/health` 기반 healthcheck
- [x] ETL 실행 골격을 추가한다.
  - `etl/requirements.txt`
  - `etl/common/db.py`
  - 번호형 ETL 스크립트 진입점
- [x] 정규 DB DDL을 추가한다.
  - `db/schema.sql`
  - PostGIS extension
  - 현재 POC 대상 7개 테이블, PK, FK, 인덱스
- [x] 구현 전 보정 사항을 반영한다.
  - 기본 `com/example/poc` 패키지 잔재 제거
  - Hibernate 6 기준으로 dialect 강제 설정 제거
  - 주요 테이블 PK 전략 정리
  - psycopg3와 `pyshp` 기반 ETL 런타임으로 정리
- [x] GraphHopper 모듈과 실행 골격을 추가한다.
  - `graphhopper-plugin/`
  - `docker/graphhopper/Dockerfile`
  - GraphHopper 설정 및 엔트리포인트
- [x] 저장소 루트 서비스 오케스트레이션을 정리한다.
  - `docker-compose.yml`
  - `postgres`, `graphhopper`, `backend` 연동
  - `etl/raw/`, `db/schema.sql` 마운트
- [x] 구현 시점 이름 규칙을 확정한다.
  - 사용자 축: `VISUAL | MOBILITY`
  - 경로 옵션: `SAFE | SHORTEST | PUBLIC_TRANSPORT`
  - GraphHopper 프로필: `visual_safe`, `visual_fast`, `wheelchair_safe`, `wheelchair_fast`
- [x] V2 범위를 분리한다.
  - 완전한 Android 앱
  - LLM UI
  - 계정 동기화 및 운영 자동화
- [x] 장소 CSV 입력 기준을 확정한다.
  - `place_merged_broad_category_final.csv`를 정규 입력으로 사용

## 검증 계획

- [x] `scripts/verify.sh` 구조 검증을 실행한다.
- [x] `scripts/smoke.sh` 스모크 검증을 실행한다.
- [x] `python -m compileall etl`을 실행한다.
- [x] `docker compose config`를 실행한다.
- [x] 주요 place CSV 헤더 일치 여부를 확인한다.

## 검증 결과

- `scripts/codex-preflight.sh`: 통과
- `scripts/check-tdd-guard.sh --mode pre poc db etl graphhopper-plugin docker docker-compose.yml .ai/PLANS/current-sprint/01-setup-and-repo-alignment.md`: 통과
- `python3 -m compileall etl`: 통과
- `python3 etl/scripts/00_check_inputs.py`: 통과
- `python3 etl/scripts/01_centerline_load.py --stage preflight`: 통과
- `docker compose config`: 통과
- `cd poc && ./gradlew test bootJar`: 통과
- `scripts/verify.sh`: 통과
- `HARNESS_SMOKE_COMMAND='cd poc && ./gradlew test bootJar' scripts/smoke.sh`: 통과

## 예외 경로 확인

- 입력 파일 누락: `etl/scripts/00_check_inputs.py`와 `etl/scripts/01_centerline_load.py --stage preflight`에서 누락 파일을 명시하고 실패하도록 구성했다.
- 스키마/엔티티 불일치: Spring 설정은 `spring.jpa.hibernate.ddl-auto=validate`로 두어 실제 DB 연결 시 매핑 불일치가 기동 단계에서 드러나도록 했다.
- 외부 런타임 미기동: Docker Compose는 PostGIS와 GraphHopper placeholder healthcheck를 통해 backend 의존성을 명시한다.
- 포트 충돌: Compose host port는 환경변수로 조정 가능하게 두었다.

## 위험 및 열린 질문

- ~~템플릿 저장소 흔적이 남아 있으면 이후 계획과 코드가 실제 제품 맥락과 어긋날 수 있다.~~ → 해결: `com/example/poc` 빈 디렉터리 제거 완료.
- 로컬 환경이 Windows + Git Bash 기준이므로 Bash 스크립트가 이를 견뎌야 한다.
- 운영형 서비스보다는 로컬 검증형 POC가 우선이므로 과도한 인프라 자동화는 보류한다.
- **DEBT(워크스트림 02):** `contextLoads` 테스트가 DataSource/JPA를 배제해 `ddl-auto=validate` 방어선이 CI에서 동작하지 않는다. Entity 클래스 추가 시 Testcontainers 기반 통합 테스트로 교체해야 한다.
- **결정 완료:** ETL Python 스크립트의 camelCase 컬럼명 인용 규칙 → `ADR-001-etl-column-quoting.md` 참조.

## 의존성

- `.env`의 DB 접속 정보
- Docker Desktop 또는 동등한 컨테이너 실행 환경

## 핸드오프

- Build skill: `implement-feature`
- Validation skill: `check`
- Ship readiness note: 이후 워크스트림은 이 저장소 경계와 런타임 기준선을 전제로 진행할 수 있어야 한다.
