# 03 CSV ETL 및 참조 데이터 적재

## 워크스트림

`CSV, 정적 대중교통 참조, 연속수치지도 기반 접근성 보강 적재`

## 목표

`etl/raw/`의 CSV, 정적 대중교통 참조 정보, 그리고 새로 추가된 `drive-download-20260423T114350Z-3-001` 번들 데이터를 사용해 기존 `road_segments`, `segment_features`를 보강하고, 대중교통 및 시설 참조 테이블을 정리한다.

관련 보조 계획:

- `N3L_A0020000_26` 중심선과 `RVWD` 폭 속성을 이용한 보조 polygon 필터 레이어 적재 계획은 [03a-road-buffer-filter-layer.md](C:/Users/SSAFY/poc_v1/.ai/PLANS/current-sprint/03a-road-buffer-filter-layer.md)에 정리한다.

## 범위

- 장소 및 시설 접근성 CSV 적재
- 음향신호기, 횡단보도, 경사도, 엘리베이터 보강
- `road_segments`와 `segment_features` 공간 매칭 규칙 정리
- `low_floor_bus_routes` 적재
- `drive-download-20260423T114350Z-3-001` 기반 보조 레이어 적재 계획 수립

## 비목표

- 운영 자동화
- GraphHopper import 구현
- 전체 API 구현

## 입력 근거

- `etl/raw/place_merged_broad_category_final.csv`
- `etl/raw/place_accessibility_features_merged_final.csv`
- `etl/raw/stg_audio_signals_ready.csv`
- `etl/raw/stg_crosswalks_ready.csv`
- `etl/raw/slope_analysis_staging.csv`
- `etl/raw/subway_station_elevators_erd_ready.csv`
- `etl/raw/부산광역시_시내버스 업체별 연도별 버스 등록대수_20260330.csv`
- `etl/raw/drive-download-20260423T114350Z-3-001/`
- `docs/prd.md`
- `docs/erd.md`
- `docs/erd_v2.md`
- `.env`

## 성공 기준

- [x] 각 입력 데이터가 어떤 테이블과 컬럼을 채우는지 한국어 기준으로 명확히 정리되어 있다.
- [x] 기존 CSV 적재와 새 연속수치지도 번들 리포트가 충돌 없이 같은 `edgeId` 중심 규칙을 사용한다.
- [x] `road_segments` 직접 업데이트 대상과 `segment_features` 증적 적재 대상을 구분했다.
- [x] 검증 시 source row 수, 매칭 수, 미매칭 수, 다중 후보 충돌 수를 남기는 ETL 리포트가 생성된다.

## 구현 전 정리 원칙

- 다른 구현 레포에서 생성된 적재 수치, 통과 기록, 시각화 결과는 이 저장소의 완료 근거로 사용하지 않는다.
- 이 워크스트림은 현재 `etl/raw/` 입력 파일과 `docs/` 명세를 기준으로 다시 구현 전 상태에서 시작한다.
- 모든 ETL은 source row 수, 매칭 수, 미매칭 수, 충돌 수를 새로 산출해 리포트로 남겨야 한다.
- 기존 구현 경험에서 나온 규칙은 참고할 수 있지만, 체크리스트 완료 상태나 DB 적재 결과로 간주하지 않는다.

## 공통 구현 원칙

### 인코딩
- CSV는 `utf-8-sig`를 우선 사용하고, 실패 시 `cp949`, `euc-kr` 순서로 fallback한다.
- 버스 등록 CSV는 현재 `cp949`로 판독된다.
- `subway_station_elevators_erd_ready.csv`는 첫 컬럼명이 `"elevatorId"` (큰따옴표 포함)일 수 있으므로 `csv.DictReader` 이후 컬럼명에서 `"` 를 strip 처리한다.

### INSERT 멱등성 전략
- `places`, `place_accessibility_features`, `subway_station_elevators` INSERT: `ON CONFLICT DO UPDATE` (upsert)
  - `places`: 원천 `placeId`가 안정적인 PK이므로 `OVERRIDING SYSTEM VALUE`와 ON CONFLICT (`"placeId"`) DO UPDATE
  - `place_accessibility_features`: ON CONFLICT (`"placeId"`, `"featureType"`) DO UPDATE SET `"isAvailable"` = EXCLUDED.`"isAvailable"`
  - `subway_station_elevators`: ON CONFLICT (`"elevatorId"`) DO UPDATE
- `road_segments` 상태값 컬럼 UPDATE: 스크립트 실행 전 해당 컬럼을 `UNKNOWN`으로 일괄 리셋 후 재적재. 리셋과 적재를 단일 트랜잭션으로 묶는다.

### dry-run 플래그
- 모든 ETL 스크립트에 `--dry-run` 옵션을 기본 탑재한다.
- dry-run 실행 시 DB에 쓰지 않고 source/matched/unmatched/conflict 집계 리포트만 출력한다.
- 실제 적재 전 dry-run 리포트를 확인하는 것을 표준 절차로 한다.

### Geometry 처리
- `place_merged_broad_category_final.csv`의 `point` 컬럼은 WKT 형식(`POINT(lng lat)`, SRID 없음)이다. `etl/common/db.py`의 `ewkt()` 헬퍼로 `SRID=4326;POINT(...)` 형식으로 변환 후 `ST_GeomFromEWKT(%s)`로 적재한다.
- `stg_audio_signals_ready.csv`는 `point` WKT 대신 `lat`, `lng` 컬럼을 좌표 소스로 사용한다.
- `stg_crosswalks_ready.csv`는 `lat`, `lng` 컬럼이 없으므로 `point` WKT를 파싱해 사용한다.

### 리포트 저장 경로
- 모든 ETL 리포트는 `runtime/etl/` 하위에 스크립트 번호 기준으로 저장한다. 이 디렉터리는 `.gitignore`에 추가한다.

## 입력 파일별 적재 매핑

| 입력 파일 또는 레이어 | 원천 필드 | 적재/업데이트 대상 | 처리 규칙 |
| --- | --- | --- | --- |
| `place_merged_broad_category_final.csv` | `placeId`, `name`, `category`, `address`, `point`, `providerPlaceId` | `places` row 추가 | 정규 장소 입력으로 사용한다. `point`는 `GEOMETRY(POINT, 4326)`로 파싱하고, `providerPlaceId`가 있으면 중복 방지 키로 사용한다. |
| `place_merged_final.csv` | `placeId`, `name`, `category`, `address`, `point`, `providerPlaceId` | 보류 | `place_merged_broad_category_final.csv`와 헤더와 행 수가 같으므로 중복 적재하지 않는다. 구현 전 diff 리포트로 어느 파일을 정규 입력으로 고정할지 확인한다. |
| `place_accessibility_features_merged_final.csv` | `id`, `placeId`, `featureType`, `isAvailable` | `place_accessibility_features` row 추가 | `placeId`는 `places.placeId` FK로 연결한다. `UNIQUE (placeId, featureType)` 충돌은 재실행 안전하게 upsert한다. |
| `stg_audio_signals_ready.csv` | `sourceId`, **`lat`**, **`lng`**, `audioSignalState`, `stat` | `road_segments.audioSignalState` 업데이트, `segment_features` row 추가 | 좌표 소스는 `point` WKT 대신 `lat`/`lng` 컬럼을 사용한다. `stat='정상동작'`이고 `audioSignalState='YES'`인 row만 처리한다. 공간 매칭 임계값: **`<= 5m` 자동 반영, `5m~10m` review-required 리포트, `> 10m` skip**. 원본 포인트는 `segment_features.featureType='AUDIO_SIGNAL'`로 저장한다. 실행 전 `road_segments.audioSignalState`를 `UNKNOWN`으로 리셋 후 트랜잭션 내에서 적재한다. |
| `stg_crosswalks_ready.csv` | `sourceId`, `point`, `widthMeter`, **`lengthMeter`**, `crossingState` | `road_segments.crossingState`, `road_segments.widthMeter` 업데이트, `segment_features` row 추가 | `lat`/`lng` 컬럼이 없으므로 `point` WKT를 파싱해 좌표를 추출한다. `point` 결측 row는 제외한다. 공간 매칭 임계값: **`<= 5m` 자동 반영, `5m~10m` review-required, `> 10m` skip**. 2차 신뢰도 필터: `lengthMeter` 대비 매칭된 edge `ST_Length` 비율이 `0.2~5.0` 범위 밖이면 conflict 리포트로 분리. 원본 포인트는 `segment_features.featureType='CROSSWALK'`로 저장한다. 실행 전 `road_segments.crossingState`, `widthMeter`를 기본값으로 리셋 후 트랜잭션 내에서 적재한다. |
| `slope_analysis_staging.csv` | `metric_mean`, `width_meter`, `geometry_wkt_4326`, `stairs_data_status` | `road_segments.avgSlopePercent`, `road_segments.widthMeter` 업데이트, `segment_features` row 추가 | `geometry_wkt_4326` polygon과 `road_segments.geom`의 교차/겹침 비율로 `edgeId`를 결정한다. `metric_mean -> avgSlopePercent`, `width_meter -> widthMeter`로 반영한다. 원본 polygon은 `segment_features.featureType='SLOPE_ANALYSIS'`로 저장한다. `stairs_data_status='MISSING_SOURCE'`는 `stairsState`를 채우지 않는다. |
| `subway_station_elevators_erd_ready.csv` | `elevatorId`, `stationId`, `stationName`, `lineName`, `entranceNo`, `point` | `subway_station_elevators` row 추가, `road_segments.elevatorState` 업데이트, `segment_features` row 추가 | `stationId + entranceNo + point` 기준으로 중복 제거 후 `subway_station_elevators`에 적재한다. 포인트가 `road_segments.geom` 기준 `<= 15m`면 `elevatorState='YES'` 자동 반영, `15m ~ 30m`는 검토 리포트, `> 30m`는 skip한다. 원본 포인트는 `segment_features.featureType='SUBWAY_ELEVATOR'`로 저장한다. |
| `부산광역시_시내버스 업체별 연도별 버스 등록대수_20260330.csv` | `인가노선`, `운행구분`, `차량번호` | `low_floor_bus_routes` row 추가 | CSV는 차량 단위이므로 `인가노선`별로 집계한다. 해당 노선에 `운행구분='저상'` 차량이 하나 이상 있으면 `hasLowFloor=true`로 본다. 현재 정적 CSV에는 BIMS `routeId`가 없으므로 MVP ETL은 `인가노선`을 `routeNo`와 `routeId`에 같이 저장하고, BIMS routeId 치환은 후속 보강으로 남긴다. |
| `부산광역시_도시공간정보시스템_ 도로(도로면)_20250522.csv` | `도형아이디`, `보도차도구분`, `시군구`, `면적(제곱미트)` | 보류 | geometry가 없어 단독으로 `road_segments.edgeId`를 결정할 수 없다. 동일 `도형아이디`의 공간 도형 원천이 확보될 때만 `walkAccess` 또는 보도/차도 검증 후보로 사용한다. |
| `drive-download-20260423T114350Z-3-001/N3L_A0033320` | `WIDT`, `QUAL`, `BYYN`, `KIND`, `SCLS`, geometry | `road_segments.widthMeter`, `widthState`, `surfaceState` 업데이트, `segment_features` row 추가 | 실제 파일에 `WIDT`, `QUAL`, `BYYN`, `KIND`, `SCLS`가 존재한다. `QUAL` 코드표는 `SWQ000=미분류`, `SWQ001=아스콘`, `SWQ002=콘크리트`, `SWQ003=블록`, `SWQ004=비포장`, `SWQ005=아스콘/블록`, `SWQ999=기타`로 확정한다. 선형 geometry와 `road_segments.geom`의 겹침 길이 ranking으로 단일 `edgeId`가 확정된 경우 `WIDT -> widthMeter`, `widthState`를 반영하고, `QUAL -> surfaceState`를 파생한다. 원본 선형은 `segment_features.featureType='WIDTH'`와 `SURFACE` 증적으로 저장한다. |
| `drive-download-20260423T114350Z-3-001/N3A_C0390000` | `STRU`, `WIDT`, `SCLS`, `NAME`, geometry | `road_segments.stairsState`, `segment_features` row 추가 | 코드표 기준 계단 레이어는 `N1A_C0390000`/`N3A_C0390000`, 통합코드는 `C0393323=계단`, 구조 코드는 `SRD001=계단`, `SRD002=스텐드`다. 현재 부산 번들 `N3A_C0390000`는 3,939건이며 `SCLS=C0393323` 3,939건, `STRU=SRD001` 3,744건, `STRU=SRD002` 195건이다. `STRU=SRD001`만 `STAIRS` 및 `stairsState='YES'` 자동 승격 후보로 사용하고, `SRD002`는 계단이 아닌 스탠드로 `segment_features` 증적만 저장한다. |
| `drive-download-20260423T114350Z-3-001` 기타 레이어 | 각 SHP DBF 필드와 geometry | `segment_features` row 추가 또는 보류 | `N3A_A0063321`, `N3A_A0070000`, `N3A_A0080000`, `N3A_A0110020`, `N3A_C0390000`, `N3L_A0123373`는 증적 저장 우선이다. `N3L_A0020000`은 기존 정규 네트워크와 비교 리포트만 만들고 즉시 교체하지 않는다. `N3A_A0080000`은 `KIND=CRK001/CRK002` 값을 가지지만 파일만으로 횡단보도라고 단정하지 않는다. `N3L_F0010000`, `N3P_F0020000`은 등고선/표고 점 계열로 경사도 계산 후보지만 `avgSlopePercent` 직접 필드는 없다. 음향신호기 필드는 연속수치지도 번들에서 확인되지 않았다. |

## 구현 계획

- [x] **[사전] `place_merged_final.csv` vs `place_merged_broad_category_final.csv` diff 리포트를 생성한다.**
  - `etl/scripts/00b_diff_place_csvs.py` 스크립트를 만들어 row 수, 컬럼 집합, 샘플 값 차이를 비교한다.
  - 결과를 `runtime/etl/00b_place_csv_diff.json`으로 저장한다.
  - 두 파일이 동일하면 `place_merged_broad_category_final.csv`를 정규 입력으로 확정하고, 차이가 있으면 내용을 검토 후 결정한다.
- [x] `place_merged_broad_category_final.csv`를 `places`에 적재한다.
  - `placeId`, `name`, `category`, `address`, `providerPlaceId`는 직접 매핑한다.
  - `point`는 WKT(`POINT(lng lat)`) 형식이므로 `ewkt()` 헬퍼로 `SRID=4326;POINT(...)` 변환 후 `ST_GeomFromEWKT`로 적재한다.
  - ON CONFLICT (`"placeId"`) DO UPDATE로 중복 처리한다.
  - `providerPlaceId`가 빈 문자열인 경우 `None`으로 정규화한다.
- [x] `place_accessibility_features_merged_final.csv`를 `place_accessibility_features`에 적재한다.
  - `placeId`를 외래키로 연결한다.
  - `featureType`, `isAvailable`를 보존한다.
  - ON CONFLICT (`"placeId"`, `"featureType"`) DO UPDATE SET `"isAvailable"` = EXCLUDED.`"isAvailable"`
- [x] `stg_audio_signals_ready.csv`를 이용해 `road_segments.audioSignalState`와 `segment_features`를 보강한다.
  - 좌표 소스: `lat`/`lng` 컬럼 (WKT `point` 미사용).
  - `stat='정상동작'`이고 `audioSignalState='YES'`인 row만 처리한다.
  - 실행 전 `road_segments.audioSignalState`를 `'UNKNOWN'`으로 일괄 리셋 후 트랜잭션 내에서 적재한다.
  - 공간 매칭 임계값: `<= 5m` 자동 반영 / `5m ~ 10m` review-required 리포트 / `> 10m` skip.
  - 공간 매칭 절차: ST_DWithin 후보 검색 → ST_Distance 기준 ranking → 최근접 단일 edgeId 선정.
  - 원본 포인트는 `segment_features.featureType='AUDIO_SIGNAL'`로 남긴다.
- [x] `stg_crosswalks_ready.csv`를 이용해 `road_segments.crossingState`, `widthMeter` 업데이트, `segment_features` 적재를 수행한다.
  - 좌표 소스: `point` WKT 파싱 (`lat`/`lng` 컬럼 없음).
  - `point` 결측 row는 제외한다.
  - 실행 전 `road_segments.crossingState`를 `'UNKNOWN'`으로, `widthMeter`를 `NULL`로 일괄 리셋 후 트랜잭션 내에서 적재한다.
  - 공간 매칭 임계값: `<= 5m` 자동 반영 / `5m ~ 10m` review-required / `> 10m` skip.
  - 2차 신뢰도 필터: `lengthMeter` 대비 매칭된 edge `ST_Length` 비율이 `0.2~5.0` 범위 밖이면 conflict 리포트로 분리하고 UPDATE 제외.
  - 횡단보도 원본 포인트는 `segment_features.featureType='CROSSWALK'`로 남긴다.
- [x] `slope_analysis_staging.csv`를 이용해 `road_segments.avgSlopePercent`, `widthMeter`를 보강한다.
  - 좌표계는 반드시 `geometry_wkt_4326` 기준으로 사용한다 (`geometry_wkt`는 사용하지 않는다).
  - 실행 전 `road_segments.avgSlopePercent`만 `NULL`로 리셋 후 트랜잭션 내에서 적재한다. `widthMeter`는 기존 N3L/crosswalk 값을 보존하고 값이 비어 있는 edge에만 보강한다.
  - 교차한 polygon은 `segment_features.featureType='SLOPE_ANALYSIS'`로 남긴다.
  - `stairs_data_status='MISSING_SOURCE'`는 `stairsState`를 채우지 않는다.
- [x] `subway_station_elevators_erd_ready.csv`를 `subway_station_elevators`에 적재한다.
  - 파일 첫 컬럼명 `"elevatorId"`(큰따옴표 포함)를 strip 후 사용한다.
  - `elevatorId`가 결측이거나 `point`가 결측인 row는 별도 리포트로 분리한다.
  - ON CONFLICT (`"elevatorId"`) DO UPDATE로 재실행 안전하게 처리한다.
- [x] `subway_station_elevators_erd_ready.csv`의 포인트를 `road_segments`와 매칭해 `elevatorState`를 보강한다.
  - 실행 전 `road_segments.elevatorState`를 `'UNKNOWN'`으로 리셋 후 트랜잭션 내에서 적재한다.
  - `<= 15m`: 자동 반영.
  - `15m ~ 30m`: review-required 리포트.
  - `> 30m`: skip.
  - 원본 포인트는 `segment_features.featureType='SUBWAY_ELEVATOR'`로 남긴다.
- [x] `drive-download-20260423T114350Z-3-001/N3L_A0033320`를 이용해 `road_segments.widthMeter`를 보강한다.
  - 모든 구 폴더의 `N3L_A0033320.shp`를 포함한 번들 manifest를 생성했다.
  - `WIDT` 값이 있고 선형 geometry가 단일 `edgeId`에 고신뢰로 매칭된 경우에만 `WIDT -> widthMeter`를 업데이트한다.
  - `widthMeter` 기준으로 `widthState`를 파생한다.
    - `widthMeter >= 1.5`: `ADEQUATE_150`
    - `1.2 <= widthMeter < 1.5`: `ADEQUATE_120`
    - `0 < widthMeter < 1.2`: `NARROW`
    - `0` 또는 결측: `UNKNOWN`
  - 원본 선형은 `segment_features.featureType='WIDTH'`로 남긴다.
  - `BYYN`, `KIND`, `SCLS`는 상태값으로 승격하지 않고 `properties JSONB`에 보존한다.
- [x] `drive-download-20260423T114350Z-3-001/N3L_A0033320.QUAL`를 이용해 `road_segments.surfaceState`를 보강한다.
  - 코드표는 `SWQ000=미분류`, `SWQ001=아스콘`, `SWQ002=콘크리트`, `SWQ003=블록`, `SWQ004=비포장`, `SWQ005=아스콘/블록`, `SWQ999=기타`로 확정한다.
  - `surfaceState` 매핑은 `SWQ000 -> UNKNOWN`, `SWQ001 -> PAVED`, `SWQ002 -> PAVED`, `SWQ003 -> BLOCK`, `SWQ004 -> UNPAVED`, `SWQ005 -> OTHER`, `SWQ999 -> OTHER`로 사용한다.
  - `QUAL` 원천값은 `segment_features.featureType='SURFACE'`, `properties.QUAL=<원천코드>`로 증적 저장한다.
- [x] `drive-download-20260423T114350Z-3-001/N3A_C0390000`를 이용해 `road_segments.stairsState`와 `segment_features`를 보강한다.
  - 계단 객체 코드표는 `N1A_C0390000/N3A_C0390000` 레이어, `C0393323=계단`, `SRD001=계단`으로 확정한다.
  - `SRD002=스텐드`, `C0390130=스텐드`는 계단 접근성 상태로 승격하지 않는다.
  - 현재 부산 번들에는 `N3A_C0390000` 3,939건이 있고, `SCLS=C0393323` 3,939건, `STRU=SRD001` 3,744건, `STRU=SRD002` 195건이다.
  - `SCLS=C0393323`이고 `STRU=SRD001`인 row만 고신뢰 `edgeId` 매칭 후 `road_segments.stairsState='YES'`로 업데이트한다.
  - 원본 geometry는 `segment_features.featureType='STAIRS'`로 저장한다.
- [x] 저상버스 등록 CSV를 이용해 `low_floor_bus_routes`를 적재한다.
  - 정적 CSV는 저상버스 여부 판단 근거로 사용한다.
  - BIMS API 기반 `routeId` 치환과 실시간 `lowplate` override는 후속 보강으로 남긴다.
  - 현재는 `인가노선`을 `routeNo`와 `routeId`에 같이 저장한다.

## 신규 연속수치지도 번들 적재 계획

### 목적

`etl/raw/drive-download-20260423T114350Z-3-001/`에 추가된 구별 연속수치지도 레이어를 기존 `road_segments`, `segment_features` 보강 흐름에 연결한다. 이 작업은 정규 네트워크를 새로 정의하는 `02`가 아니라, 이미 적재된 네트워크를 보강하는 `03`의 범위로 다룬다.

### 레이어 분류

| 레이어 코드 | Geometry | 전역 건수 | 1차 적재 대상 | 계획 메모 |
| --- | --- | ---: | --- | --- |
| `N3L_A0020000` | `POLYLINE` | `252,315` | `road_segments` 비교/대체 후보 | 현재 정규 도로 중심선과 같은 계열이므로, 기존 `N3L_A0020000_26`와 차이 비교 후에만 교체 여부를 결정한다 |
| `N3L_A0033320` | `POLYLINE` | `36,311` | `segment_features` 우선, 일부 `road_segments` 승격 후보 | 보도성 선형 레이어로 추정되며 폭, 품질 정보를 가진다 |
| `N3A_A0080000` | `POLYGON` | `255` | `segment_features` | 교차로/교차영역 계열로 추정, 원본 polygon 보존 우선 |
| `N3A_C0390000` | `POLYGON` | `3,939` | `segment_features` | 구조물성 polygon 레이어로 추정, 직접 상태값 승격 금지 |
| `N3A_A0063321` | `POLYGON` | `187` | `segment_features` | 소규모 구조물 polygon, 타입 코드 검증 전에는 증적 적재만 수행 |
| `N3A_A0070000` | `POLYGON` | `1,352` | `segment_features` | 교량/구조물 계열로 추정, 증적 적재 우선 |
| `N3A_A0110020` | `POLYGON` | `124` | `segment_features` | 터널 면 계열로 추정, `영도구`에는 레이어가 없음 |
| `N3L_A0123373` | `POLYLINE` | `168` | `segment_features` | 터널 계열 선형 레이어로 추정, `영도구`에는 레이어가 없음 |
| `N3L_A0010000` | `POLYLINE` | `44,838` | 보류 | 라우팅 의미가 아직 불명확하므로 코드 사전 확인 전 보류 |
| `N3A_A0010000` | `POLYGON` | `139,741` | 보류 | 필드가 `UFID`, `SCLS`, `FMTA`뿐이라 접근성 의미를 확정할 수 없음 |
| `N3A_B0010000` | `POLYGON` | `606,974` | 보류 | 건물/시설 면 계열로 보이며 `places`나 `road_segments`에 직접 적재하지 않음 |
| `N3A_G0100000` | `POLYGON` | `88` | 보류 | 행정구역 경계 검증용 후보, 서비스 테이블 직접 적재 없음 |
| `N3A_G0110000` | `POLYGON` | `342` | 보류 | 동 경계 검증용 후보, 서비스 테이블 직접 적재 없음 |
| `N3L_F0010000` | `POLYLINE` | `17,870` | 보류 | 등고선/표고 선형 정보로 보이며 직접 접근성 상태값으로 사용하지 않음 |
| `N3P_F0020000` | `POINT` | `44,754` | 보류 | 표고 점 계열로 보이며 1차 적재 대상에서 제외 |

### 적재 전략

1. 번들 manifest를 만든다.
   - 16개 구 폴더를 모두 순회해 레이어 존재 여부, 경로, geometry 타입, row 수를 기록한다.
   - 결과는 `runtime/etl/continuous-map-load/` 아래 JSON으로 남긴다.
   - `영도구`의 `N3L_A0123373` 부재처럼 선택적 누락은 경고로만 기록한다.
2. source identity를 번들 기준으로 정규화한다.
   - `sourceDataset='drive-download-20260423T114350Z-3-001:N3L_A0033320'`처럼 번들명과 레이어 코드를 함께 기록한다. (컬럼명은 ADR-001에 따라 camelCase로 통일)
   - 구별 tile 간 충돌 가능성이 있으므로 원본 `UFID`는 정규 테이블 키로 쓰지 않고, 적재 리포트에서 `edgeId -> 구명/레이어/row index/UFID` 형태로만 추적한다.
3. `N3L_A0020000`는 즉시 교체하지 않는다.
   - 현재 `02`에서 적재한 `N3L_A0020000_26` 결과와 row count, geometry sample, source identity 차이를 비교한다.
   - 비교 리포트가 준비되기 전까지는 `road_segments` 정규 소스를 교체하지 않는다.
4. 비정규 레이어는 `segment_features` 우선으로 적재한다.
   - `N3L_A0033320`, `N3A_A0080000`, `N3A_C0390000`, `N3A_A0063321`, `N3A_A0070000`, `N3A_A0110020`, `N3L_A0123373`를 1차 대상으로 본다.
   - 기능 성격이 확정된 레이어는 `WIDTH`, `SURFACE`, `STAIRS`처럼 라우팅 의미가 드러나는 `featureType`을 사용하고, 원본 레이어 코드는 `sourceLayer`와 `properties JSONB`에 보존한다.
   - 기능 성격이 확정되지 않은 레이어는 `CONTINUOUS_MAP_<레이어코드>`처럼 원본 레이어를 명시하는 형태를 사용한다.
5. `road_segments` 직접 승격은 고신뢰 후보만 허용한다.
   - 1차 승격 후보는 `N3L_A0033320`이다.
   - 단일 세그먼트에 명확히 매칭된 경우에만 `widthMeter`, `widthState`를 업데이트한다.
   - `QUAL`은 코드표 또는 내부 매핑표 확정 후에만 `surfaceState`로 승격한다.
   - `BYYN`, `KIND`, `SCLS`는 보조 근거로만 저장하고 직접 상태값으로 승격하지 않는다.
   - `stairsState`는 코드표에서 계단 객체가 확인된 레이어만 `YES`로 승격한다.
   - `brailleBlockState`, `rampState`, `elevatorState`는 코드 사전 검증 전까지 이 번들에서 직접 채우지 않는다.

### 추가 필수 구현 체크리스트: slope/continuous DB 적재

- [x] **[스키마] 원본 증적 보존을 위한 `segment_features` 확장 또는 별도 evidence 테이블을 설계한다.**
  - 현재 `segment_features`는 `edgeId`, `featureType`, `geom`만 보존하므로 `metric_mean`, `width_meter`, `WIDT`, `QUAL`, `BYYN`, `KIND`, `SCLS`, `TYPE`, source row index 같은 원천 속성을 담을 수 없다.
  - 권장안: `segment_features`에 `sourceDataset`, `sourceLayer`, `sourceRowNumber`, `matchStatus`, `matchScore`, `properties JSONB`를 추가한다.
  - `sourceFeatureId`는 정규 PK로 쓰지 않는다. 원천 식별자는 `properties` 또는 `sourceRowNumber`로 추적하고, 서비스 조인은 계속 `edgeId` 기준으로 유지한다.
  - **[필수 선행] `db/schema.sql`에 `ALTER TABLE segment_features ADD COLUMN` 스크립트를 작성하고, Testcontainers(`postgis/postgis:16-3.4`) 기반 통합 테스트를 재실행해 스키마 적용을 검증한다. 이 ALTER가 완료되기 전까지 이하 체크리스트 구현을 착수하지 않는다.**
  - `properties JSONB` 컬럼에 대해 GIN 인덱스(`CREATE INDEX ... USING GIN ("properties")`) 필요 여부를 결정해 `schema.sql`에 반영한다. POC 단계에서는 검증 게이트 쿼리가 `properties` 조회를 포함하지 않으면 생략해도 무방하다.
- [x] **[ETL 설계] `slope_analysis_staging.csv` polygon overlay 적재 규칙을 구현 가능한 SQL/파이썬 흐름으로 고정한다.**
  - `geometry_wkt_4326`가 비어 있는 row는 `skipped_missing_geometry`로 리포트한다.
  - `metric_mean`이 숫자인 row만 `avgSlopePercent` 승격 후보로 본다.
  - `width_meter`가 숫자인 row만 `widthMeter` 승격 후보로 본다.
  - `ST_Intersects` 후보 중 `ST_Length(ST_Intersection(edge.geom, polygon)) / edge.lengthMeter` 또는 중심선 교차 길이 기준으로 단일 `edgeId`를 결정한다.
  - 다중 후보, 낮은 overlap, geometry 오류는 DB 증적 저장 없이 리포트로 분리하거나 `matchStatus='REVIEW'`로 저장한다.
- [x] **[ETL 구현] `slope_analysis_staging.csv`를 DB에 실제 적재한다.**
  - `segment_features.featureType='SLOPE_ANALYSIS'`로 원본 polygon 증적을 저장한다.
  - 고신뢰 매칭 row는 `road_segments.avgSlopePercent`를 업데이트한다.
  - **`widthMeter` 리셋 범위 확정**: 실행 전 리셋 대상은 `avgSlopePercent` 컬럼만으로 제한한다. `widthMeter`는 slope 소스에서 값이 있는 edgeId에 한해 `UPDATE ... WHERE "widthMeter" IS NULL` 방식으로 기존 crosswalk/N3L_A0033320 값을 보존한다. 무조건 NULL 리셋 금지.
  - **`widthState` 파생 우선순위**: `N3L_A0033320`, `slope_analysis_staging.csv`, crosswalk 모두 동일 임계값(`>= 1.5 → ADEQUATE_150`, `1.2-1.5 → ADEQUATE_120`, `< 1.2 → NARROW`)을 사용하며, 이 로직은 `reference_loader.py`의 단일 함수(`derive_width_state()`)로 추출해 공유한다.
  - **소스 우선순위**: `widthMeter` 업데이트 우선순위는 `N3L_A0033320 > slope_analysis_staging.csv > crosswalk` 순이다. 높은 우선순위 소스가 이미 값을 채운 edgeId는 낮은 우선순위 소스가 덮어쓰지 않는다.
  - dry-run과 actual-load 모두 source/matched/unmatched/review/conflict/skipped count를 리포트한다.
- [x] **[ETL 설계] 연속수치지도 번들의 실제 DB 적재 대상 레이어를 확정한다.**
  - 1차 필수 적재: `N3L_A0033320`, `N3A_C0390000`.
  - 증적 우선 적재: `N3A_A0063321`, `N3A_A0070000`, `N3A_A0080000`, `N3A_A0110020`, `N3L_A0123373`.
  - 비교 전용: `N3L_A0020000`.
  - 보류: `N3A_A0010000`, `N3L_A0010000`, `N3A_B0010000`, `N3A_G0100000`, `N3A_G0110000`, `N3L_F0010000`, `N3P_F0020000`.
- [x] **[ETL 구현] `N3L_A0033320`를 DB에 실제 적재한다.**
  - 모든 구 폴더의 `N3L_A0033320.shp`를 순회한다.
  - `WIDT`가 숫자인 row는 `widthMeter` 승격 후보로 본다.
  - **매칭 기준 확정**: 선형 geometry와 `road_segments.geom`의 겹침 길이를 우선 계산한다. 실제 데이터에서는 보도 선형과 도로 중심선이 나란히 떨어진 경우가 많아 strict overlap만으로는 0건 매칭이므로, 최종 구현은 `ST_DWithin(..., 5m)` 후보에서 겹침 길이 우선, 거리 차순으로 단일 `edgeId`를 선정한다.
  - 고신뢰 매칭 row는 `segment_features.featureType='WIDTH'`로 저장하고, `road_segments.widthMeter`, `road_segments.widthState`를 업데이트한다.
  - **`widthMeter` 업데이트 조건**: 이미 다른 소스(`N3L_A0033320`는 최우선 소스이므로 crosswalk 값을 포함해) 값이 있어도 덮어쓴다. `widthState`는 `derive_width_state()` 함수로 파생한다.
  - `QUAL`은 확정 코드표에 따라 `segment_features.featureType='SURFACE'` 증적으로 저장하고, `road_segments.surfaceState`로 승격한다.
  - `QUAL`, `BYYN`, `KIND`, `SCLS`는 `properties JSONB`에 보존한다.
- [x] **[ETL 구현] `N3A_C0390000` 계단 객체를 DB에 실제 적재한다.**
  - `SCLS=C0393323`이고 `STRU=SRD001`인 row만 계단으로 처리한다.
  - 계단으로 확정된 row는 `segment_features.featureType='STAIRS'`로 저장한다.
  - 고신뢰 단일 `edgeId` 매칭 row는 `road_segments.stairsState='YES'`로 업데이트한다.
  - `STRU=SRD002` 스텐드 row는 `stairsState`를 변경하지 않고 `properties`에 보존하거나 별도 review 리포트로 분리한다.
- [x] **[ETL 구현] 연속수치지도 증적 우선 레이어를 `segment_features`에 실제 적재한다.**
  - 대상: `N3A_A0063321`, `N3A_A0070000`, `N3A_A0080000`, `N3A_A0110020`, `N3L_A0123373`.
  - **`N3A_C0390000`는 이 항목에서 제외한다.** `N3A_C0390000`의 SRD001(계단) 적재는 위 체크리스트 6번에서 `featureType='STAIRS'`로 처리하고, SRD002(스텐드)는 review 리포트로만 남긴다. 이중 적재 방지.
  - `featureType='CONTINUOUS_MAP_<레이어코드>'` 형식으로 저장한다.
  - 단일 `edgeId` 매칭 실패 row는 `unmatched` 또는 `review` 리포트로 남긴다.
- [x] **[검증] slope/continuous 적재 후 DB 카운트와 품질 리포트를 추가한다.**
  - `segment_features` featureType별 count를 리포트한다.
  - `road_segments.avgSlopePercent IS NOT NULL`, `road_segments.widthMeter IS NOT NULL`, `widthState <> 'UNKNOWN'`, `surfaceState <> 'UNKNOWN'`, `stairsState = 'YES'` count를 리포트한다.
  - source/matched/unmatched/review/conflict/skipped count를 데이터셋별로 표 형태로 남긴다.
  - 샘플 edgeId 10개 이상에 대해 원본 geometry와 `road_segments.geom`의 실제 교차 여부를 검증한다.
  - **`post_load_validate()` 확장**: slope/continuous 적재 완료 후 `post_load_validate()`에 `segment_features.edgeId` FK 무결성 검사(`segment_features`에 존재하지 않는 `edgeId`가 없는지)와 `matchStatus IS NOT NULL` 비율 검사를 추가한다.

### 매칭 규칙

- 선형 레이어는 `road_segments.geom`과의 겹침 길이 기반 ranking을 우선 사용한다. 단, `N3L_A0033320`처럼 보도 선형이 도로 중심선과 나란히 떨어져 strict overlap이 성립하지 않는 레이어는 `<= 5m` 거리 후보 안에서 겹침 길이 우선, 거리 차순 ranking을 사용한다.
- polygon 레이어는 `ST_Intersects`와 겹침 비율 기준을 함께 사용한다.
- point 레이어를 이후 활성화할 경우에만 `ST_DWithin` 거리 제한을 사용한다.
- 어떤 레이어든 최종 업데이트와 외래키 연결은 `edgeId`로 마무리한다.

### 검증 게이트

- [x] 16개 구 manifest가 생성되고 레이어별 row 수가 기록된다.
- [x] `N3L_A0020000`의 번들 버전과 기존 정규 적재본 비교 리포트가 생성된다.
- [x] CSV 기반 `segment_features.featureType`별 source 수, 매칭 수, 미매칭 수, conflict 수가 기록된다.
- [x] `N3L_A0033320` 승격 시 `widthMeter` 업데이트 건수와 skip 이유가 리포트에 남는다.
- [x] `slope_analysis_staging.csv` 승격 시 `avgSlopePercent`, `widthMeter` 업데이트 건수와 skip 이유가 리포트에 남는다.

## 구현 결과

- 구현 파일:
  - `etl/common/reference_loader.py`
  - `etl/scripts/00b_diff_place_csvs.py`
  - `etl/scripts/02_reference_load.py`
  - `etl/tests/test_reference_loader.py`
- 리포트:
  - `runtime/etl/00b_place_csv_diff.json`
  - `runtime/etl/03-reference-load/dry_run_report.json`
  - `runtime/etl/03-reference-load/load_report.json`
  - `runtime/etl/03-reference-load/slope_analysis_load_report.json`
  - `runtime/etl/03-reference-load/slope_analysis_report.json`
  - `runtime/etl/03-reference-load/post_load_validate.json`
  - `runtime/etl/continuous-map-load/continuous_map_manifest.json`
  - `runtime/etl/continuous-map-load/continuous_centerline_compare_report.json`
  - `runtime/etl/continuous-map-load/continuous_width_surface_load_report.json`
  - `runtime/etl/continuous-map-load/continuous_stairs_load_report.json`
  - `runtime/etl/continuous-map-load/continuous_evidence_layers_load_report.json`
- DB 적재 결과:
  - `places`: 13,564
  - `place_accessibility_features`: 42,368
  - `road_nodes`: 229,129
  - `road_segments`: 248,458
  - `segment_features`: 172,823
  - `low_floor_bus_routes`: 146
  - `subway_station_elevators`: 231
- `segment_features` 상세:
  - `AUDIO_SIGNAL`: 210
  - `CONTINUOUS_MAP_N3A_A0063321`: 151
  - `CONTINUOUS_MAP_N3A_A0070000`: 1,291
  - `CONTINUOUS_MAP_N3A_A0080000`: 255
  - `CONTINUOUS_MAP_N3A_A0110020`: 122
  - `CONTINUOUS_MAP_N3L_A0123373`: 141
  - `CROSSWALK`: 2,078
  - `SLOPE_ANALYSIS`: 129,085
  - `STAIRS`: 902
  - `SUBWAY_ELEVATOR`: 126
  - `SURFACE`: 19,858
  - `WIDTH`: 18,604
- 매칭 리포트:
  - 음향신호기: source 3,060 / matched 210 / review 346 / unmatched 2,504
  - 횡단보도: source 3,815 / matched 2,078 / review 121 / unmatched 156 / conflict 1,457 / skipped 3
  - 지하철 엘리베이터: source 231 / loaded 231 / matched 126 / review 82 / unmatched 23 / duplicate 28
  - 저상버스: source 2,511 / route 146 / low-floor route 118 / encoding `cp949`
  - `slope_analysis_staging.csv`: source 163,008 / candidate 162,992 / matched 129,085 / unmatched 33,907 / skipped 16 / `avgSlopePercent` updated segments 119,298
  - `N3L_A0033320`: source 36,311 / matched 19,858 / unmatched 16,453 / width features 18,604 / surface features 19,858 / width updated segments 13,488 / surface updated segments 13,807
  - `N3A_C0390000`: source 3,939 / candidate 3,744 / matched 902 / review 372 / unmatched 2,470 / skipped 195 / `stairsState` updated segments 780
  - 연속수치지도 증적 우선 레이어: source 2,086 / matched 1,960 / review 32 / unmatched 94
  - `N3L_A0020000` 비교: 기존 정규 소스 `N3L_A0020000_26` 248,425 rows, 번들 `N3L_A0020000` 252,315 rows, 현 POC 정규 네트워크는 기존 `N3L_A0020000_26` 유지
- 보류:
  - BIMS routeId 치환은 정적 CSV 적재 이후 후속 보강으로 남겼다.
  - 연속수치지도 증적 우선 레이어는 상태값으로 승격하지 않고 `segment_features` 증적으로만 보존했다.

## 검증 계획

- [x] 각 CSV와 SHP 번들 레이어의 실제 헤더/필드와 적재 대상 컬럼을 대조한다.
- [x] point 기반 공간 매칭 규칙별 집계 검증을 수행한다.
- [x] `subway_station_elevators_erd_ready.csv`의 결측 및 중복 검증 결과를 남긴다.
- [!] 저상버스 적재 시 BIMS `routeId` 미매칭 노선을 별도 리포트로 남긴다.
- [x] `drive-download-20260423T114350Z-3-001` manifest 생성 시 레이어별 source row 수를 남긴다.
- [x] `slope_analysis_staging.csv`와 연속수치지도 번들의 실제 DB 적재 결과를 데이터셋별 source/matched/unmatched/review/conflict/skipped 표로 남긴다.

## 위험 및 열린 질문

- 증적 우선 레이어(`N3A_A0063321`, `N3A_A0070000`, `N3A_A0080000`, `N3A_A0110020`, `N3L_A0123373`)는 공식 코드 사전 없이 상태값으로 승격하지 않는다.
- 새 번들의 `N3L_A0020000`는 현재 03에서는 비교 전용으로만 남기고, 기존 정규 네트워크 `N3L_A0020000_26`을 유지한다. 대체 여부는 후속 별도 결정이 필요하다.
- 저상버스 CSV의 `인가노선`과 BIMS routeId를 후속 치환할 때 exact match가 깨질 경우 수동 alias 정책이 필요할 수 있다.
- point 기반 데이터와 polygon 기반 데이터의 공간 매칭 품질 차이를 같은 지표로 비교하면 오판 가능성이 있다.

## 결정 완료 사항

| 결정 항목 | 결정 내용 |
|---|---|
| CSV BOM 인코딩 | `utf-8-sig` 우선, `cp949`/`euc-kr` fallback, `subway_station_elevators` 첫 컬럼 `"elevatorId"` strip |
| `place` point 컬럼 형식 | WKT `POINT(lng lat)` → `ewkt()` 헬퍼로 EWKT 변환 후 적재 |
| INSERT 멱등성 | `places`/`place_accessibility_features`/`subway_station_elevators`: ON CONFLICT DO UPDATE |
| road_segments UPDATE 멱등성 | 실행 전 UNKNOWN 리셋 + 트랜잭션 |
| dry-run 플래그 | 모든 스크립트 기본 탑재 |
| 음향신호 매칭 임계값 | `<= 5m` 자동 / `5~10m` review / `> 10m` skip |
| 횡단보도 매칭 임계값 | `<= 5m` 자동 / `5~10m` review / `> 10m` skip |
| 횡단보도 2차 신뢰도 필터 | `lengthMeter` 대비 edge ST_Length 비율 `0.2~5.0` 범위 밖이면 conflict |
| 음향신호 좌표 소스 | `lat`/`lng` 컬럼 사용 (`point` WKT 미사용) |
| BIMS API | 이번 구현은 정적 버스 CSV 적재까지 완료, BIMS routeId 치환은 후속 보강 |
| `place_merged_final.csv` | diff 스크립트(`00b_diff_place_csvs.py`) 선행 실행 후 정규 입력 확정 |
| 리포트 저장 경로 | `runtime/etl/` (`.gitignore` 추가) |

## 의존성

- `02`에서 적재된 `road_segments`, 공간 인덱스, `edgeId`
- BIMS API 접속 정보는 routeId 치환을 구현할 때만 필요하다.
- PostGIS가 켜진 로컬 검증 DB

## 핸드오프

- Build skill: `implement-feature`
- Validation skill: `check`
- Ship readiness note: 이 워크스트림은 새 데이터셋을 포함한 모든 보강 적재를 `edgeId` 중심 규칙으로 묶어야 하며, 정규 네트워크 재정의는 `02`의 범위를 침범하지 않아야 한다.
