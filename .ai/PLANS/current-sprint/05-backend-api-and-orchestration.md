# 05 백엔드 API 및 오케스트레이션

## 워크스트림

`Spring Boot API와 경로/시설/대중교통 흐름 연결`

## 목표

`poc/`의 Spring Boot 백엔드를 기반으로 경로 탐색, 대중교통 보조 경로, 시설 조회 API를 연결하고, ETL과 GraphHopper 결과를 실제 서비스 흐름으로 묶는다.

## 범위

- 경로 탐색 API
- 시설 조회 API
- ODsay/BIMS 연동
- local-first MVP 범위 정리

## 비목표

- 완전한 회원 기능
- 익명 위험 제보 API
- 운영 자동화
- 관리자 백오피스

## 입력 근거

- `poc/`
- `.env`
- `docs/prd.md`
- `docs/erd.md`
- `.ai/PLANS/current-sprint/03-csv-etl-and-reference-data.md`
- `.ai/PLANS/current-sprint/04-graphhopper-routing-profiles_v2.md`

## 성공 기준

- [ ] `SAFE`, `SHORTEST`, `PUBLIC_TRANSPORT` 경로 옵션을 처리하는 API 계약이 정의되어 있다.
- [ ] 시설 조회 API가 최신 ERD에 맞는 테이블 구조를 사용한다.
- [ ] 대중교통 옵션이 `low_floor_bus_routes`, `subway_station_elevators`를 활용하는 흐름으로 정리되어 있다.
- [ ] Spring Boot는 `db/schema.sql`로 생성된 스키마를 사용하고, 테이블 자동 생성은 하지 않는다.

## 구현 계획

- [ ] `poc/` 내 패키지를 `routing`, `transit`, `places`, `common` 기준으로 정리한다.
- [ ] JPA 설정을 스키마 검증 모드로 둔다.
  - `spring.jpa.hibernate.ddl-auto=validate`
  - 운영/POC 공통으로 Spring의 자동 DDL 생성은 사용하지 않는다.
  - 엔티티 필드와 `db/schema.sql` 컬럼명이 어긋나면 애플리케이션 기동 단계에서 실패하도록 한다.
- [x] `/api/v1/routes/search` 계약을 구현한다.
  - 입력: 사용자 축, 출발/도착 좌표, 경로 옵션
  - 출력: 옵션별 경로와 segment 정보
- [x] `SAFE`, `SHORTEST`는 GraphHopper 4개 프로필과 매핑한다.
- [ ] `PUBLIC_TRANSPORT`는 ODsay/BIMS와 내부 참조 테이블을 함께 사용한다.
  - 저상버스 노선 여부 확인
  - 지하철 엘리베이터 접근 가능성 확인
- [ ] `/api/v1/places`는 `places`, `place_accessibility_features`를 함께 조회한다.
- [ ] local-first MVP 기준에 맞춰 계정 의존 흐름을 최소화한다.

## 검증 계획

- [ ] 시설 조회 응답이 `places`와 `place_accessibility_features`를 일관되게 묶는지 확인한다.
- [ ] `PUBLIC_TRANSPORT` 옵션이 참조 테이블과 외부 API를 통해 필터링되는지 검증한다.
- [x] GraphHopper 응답의 geometry, instructions, path details가 API 응답으로 전달되는지 확인한다.

## 위험 및 열린 질문

- `users`, `bookmarks`, `favorite_routes`, 제보/경로 로그 테이블은 ERD에 있으나 초기 `db/schema.sql` 생성 대상에서 제외된다. 해당 API를 실제 구현할 때 별도 DDL 확장이 필요하다.
- ODsay/BIMS 응답과 내부 station/route 매핑 정합성이 실제 품질을 좌우한다.
- 경로 결과를 API 응답 DTO로 어떻게 압축할지 결정이 필요하다.

## 의존성

- `03`의 참조 데이터 적재 결과
- `04`의 GraphHopper 프로필 및 import 결과

## 핸드오프

- Build skill: `start`
- Validation skill: `check`
- Ship readiness note: API는 최신 ERD와 ETL 산출물을 전제로 하며, 대중교통 필터링 로직이 누락 없이 연결되어야 한다.
