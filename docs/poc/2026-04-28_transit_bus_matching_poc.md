# 대중교통 후보 검증 PoC: 일반 경로와 휠체어 접근성 경로

> 작성일: 2026-04-28  
> 목적: ODsay가 생성한 대중교통 후보 전체를 대상으로 버스, 지하철, 버스+지하철 혼합 경로를 검증하고, 휠체어 사용자일 때만 추가되는 저상버스/엘리베이터/휠체어 보행 검증 차이를 정리한다.  
> 기준 테스트: 해운대역 근처 -> 센텀역 근처, ODsay + 부산 BIMS 실 API 호출

---

## 1. 핵심 결론

출발지와 목적지가 1km를 넘으면 ODsay로 대중교통 후보를 먼저 만든다. 후보에는 버스만, 지하철만, 버스+지하철 혼합, 환승 경로가 모두 포함될 수 있다.

우리 서버는 ODsay 후보를 그대로 반환하지 않고, 각 후보를 leg 단위로 분해한 뒤 보행/버스/지하철 구간을 우리 기준으로 검증하고 다시 점수화한다.

```text
origin, destination
-> 거리 기준 판단
-> ODsay 대중교통 후보 조회
-> leg parser: WALK / BUS / SUBWAY / TRANSFER
-> 일반 검증 또는 휠체어 접근성 검증
-> 후보 invalid/unknown/confirmed 판단
-> 비용 재계산과 ranking
-> 최종 안내
```

휠체어 사용자일 때만 추가되는 특수 검증은 세 가지다.

```text
BUS:
  일반 버스가 아니라 실제 탑승 가능한 저상버스인지 확인

SUBWAY:
  역 대표 좌표가 아니라 엘리베이터 위치로 보행 endpoint를 보정

WALK:
  일반 보행이 아니라 wheelchair GraphHopper profile로 재탐색
```

---

## 2. 전체 대중교통 후보 처리 관점

ODsay는 대중교통 조합을 만드는 역할을 맡는다. 우리 서버는 후보를 검증하고 보행 구간을 교체한다.

| 구간 유형 | 일반 대중교통 경로 | 휠체어 접근성 경로 |
| --- | --- | --- |
| WALK | ODsay 도보 leg를 우리 GraphHopper 보행 경로로 재계산 | wheelchair profile로 재계산. 계단, 급경사, 단절 구간은 제외 또는 penalty |
| BUS | ODsay BUS leg를 유지하고 BIMS 도착정보로 ETA 보강 | BIMS `lowplate1/lowplate2`로 실제 탑승 가능한 저상 차량 확인 |
| SUBWAY | ODsay 지하철 leg를 유지하고 시간/환승 정보를 사용 | 승차역/하차역/환승역의 엘리베이터 접근 가능 여부 확인. 보행 endpoint를 엘리베이터 좌표로 교체 |
| TRANSFER | ODsay 환승 구조를 사용하고 실외 환승 보행만 GraphHopper로 재계산 | 실외 환승은 wheelchair profile, 지하철 내부 환승은 엘리베이터/무장애 환승 가능 여부를 별도 검증 |

중요한 점은 버스만 보는 것이 아니다. ODsay 상위 후보 중 지하철-only가 가장 빠를 수도 있고, 휠체어 사용자는 지하철역 엘리베이터가 확인되면 저상버스보다 지하철 후보가 더 안정적인 추천이 될 수 있다.

---

## 3. 일반 경로와 휠체어 경로의 차이

### 3-1. 일반 대중교통 경로

일반 경로는 "대중교통으로 갈 수 있는가, 얼마나 빠른가"가 중심이다.

```text
1. ODsay 후보 N개 조회
2. 후보별 WALK / BUS / SUBWAY leg 분해
3. WALK leg를 우리 GraphHopper 일반 보행 경로로 재계산
4. BUS leg는 BIMS 도착정보가 있으면 ETA 보강
5. SUBWAY leg는 ODsay 시간/노선 정보를 사용
6. 후보별 총시간, 환승 수, 보행거리로 ranking
```

일반 경로에서는 저상버스 여부나 엘리베이터 여부가 필터 조건이 아니다. 다만 화면에 참고 정보로 표시할 수 있다.

### 3-2. 휠체어 접근성 경로

휠체어 경로는 "실제로 탈 수 있고 이동할 수 있는가"가 먼저다.

```text
1. ODsay 후보 N개 조회
2. 후보별 WALK / BUS / SUBWAY leg 분해
3. WALK leg를 wheelchair GraphHopper profile로 재계산
4. BUS leg는 사용자가 정류장 도착 후 탈 수 있는 저상버스가 있는지 검증
5. SUBWAY leg는 승차역/하차역/환승역 엘리베이터 접근성을 검증
6. 하나라도 접근성 핵심 조건이 깨지면 invalid 또는 unknown 처리
7. confirmed 후보를 우선 ranking
```

휠체어 경로에서는 시간 최단보다 확실한 접근 가능성이 우선이다.

```text
1. 모든 WALK leg wheelchair 검증 통과
2. 모든 BUS leg 저상버스 탑승 가능 confirmed
3. 모든 SUBWAY leg 엘리베이터 접근 가능 confirmed
4. 보행거리 짧음
5. 환승 횟수 적음
6. 총시간 짧음
7. unknown 구간 적음
```

---

## 4. PoC 재현 입력

실 구현에서도 아래 입력으로 같은 흐름을 재현한다. 실시간 버스 도착 분은 호출 시각에 따라 달라진다.

```text
출발지: 해운대역 근처
origin.lat = 35.1636
origin.lng = 129.1588

도착지: 센텀역 근처
destination.lat = 35.1736
destination.lng = 129.1246
```

환경변수:

```text
ODSAY_API_BASE_URL=https://api.odsay.com/v1/api
ODSAY_API_KEY=...
BUSAN_BIMS_API_BASE_URL=https://apis.data.go.kr/6260000/BusanBIMS
BUSAN_BIMS_SERVICE_KEY_DECODING=...
```

ODsay 호출:

```text
GET {ODSAY_API_BASE_URL}/searchPubTransPathT
  ?apiKey={ODSAY_API_KEY}
  &SX=129.1588
  &SY=35.1636
  &EX=129.1246
  &EY=35.1736
  &SearchType=0
```

PoC 호출 결과:

```text
ODsay path count = 13
상위 5개 중 버스 후보 4개, 지하철 후보 1개
```

---

## 5. ODsay 후보 파싱 기준

ODsay `subPath[].trafficType` 기준:

| trafficType | 의미 | 내부 leg |
| --- | --- | --- |
| `1` | 지하철 | `SUBWAY` |
| `2` | 버스 | `BUS` |
| `3` | 도보 | `WALK` |

후보 하나는 다음처럼 혼합될 수 있다.

```text
WALK -> BUS -> WALK
WALK -> SUBWAY -> WALK
WALK -> BUS -> WALK -> SUBWAY -> WALK
WALK -> SUBWAY -> WALK -> BUS -> WALK
```

따라서 구현은 "버스 후보", "지하철 후보"를 따로 만드는 방식보다, ODsay path를 공통 leg list로 변환한 뒤 leg별 verifier를 적용하는 방식이 좋다.

---

## 6. BUS leg 검증

### 6-1. ODsay BUS leg에서 파싱할 값

```json
{
  "trafficType": 2,
  "startName": "해운대도시철도역",
  "endName": "SK텔레콤",
  "startArsID": "09729",
  "endArsID": "09280",
  "startID": 623708,
  "endID": 627093,
  "sectionTime": 16,
  "lane": [
    {
      "busNo": "181",
      "busID": 71193,
      "busLocalBlID": "5200181000"
    }
  ],
  "passStopList": {
    "stations": [
      {
        "stationName": "해운대도시철도역",
        "localStationID": "505020000",
        "arsID": "09729",
        "x": "129.158648",
        "y": "35.163528"
      }
    ]
  }
}
```

필드 매핑:

| 목적 | 우선 사용 | fallback |
| --- | --- | --- |
| BIMS 승차 정류장 ID | `passStopList.stations[0].localStationID` | `busStopList(arsno=startArsID).bstopid` |
| BIMS 하차 정류장 ID | `passStopList.stations[last].localStationID` | `busStopList(arsno=endArsID).bstopid` |
| BIMS 노선 ID | `lane[].busLocalBlID` | `stopArrByBstopid` 전체 조회 후 `lineno == lane[].busNo` |
| 버스 번호 표시 | `lane[].busNo` | 없음 |
| 정류장 좌표 | `passStopList.stations[].x/y` | subPath `startX/startY`, `endX/endY` |

주의:

- ODsay `startID`는 BIMS `bstopid`로 직접 쓰지 않는다.
- 실제 테스트에서 `startID=623708`으로 BIMS 도착정보를 조회하면 결과가 비어 있었다.
- 실제 BIMS `bstopid`는 `localStationID=505020000`이었다.
- ODsay `lane[]`에는 대체 가능한 버스가 여러 개 들어올 수 있다. 반드시 전체를 평가한다.

### 6-2. BIMS 호출 순서

정류장 확인 fallback:

```text
GET {BUSAN_BIMS_API_BASE_URL}/busStopList
  ?serviceKey={BUSAN_BIMS_SERVICE_KEY_DECODING}
  &pageNo=1
  &numOfRows=10
  &arsno=09729
```

PoC 결과:

```text
arsno=09729
-> bstopid=505020000
-> bstopnm=해운대도시철도역
```

특정 노선 도착정보 조회:

```text
GET {BUSAN_BIMS_API_BASE_URL}/busStopArrByBstopidLineid
  ?serviceKey={BUSAN_BIMS_SERVICE_KEY_DECODING}
  &pageNo=1
  &numOfRows=10
  &bstopid=505020000
  &lineid=5200181000
```

정류장 전체 도착정보 fallback:

```text
GET {BUSAN_BIMS_API_BASE_URL}/stopArrByBstopid
  ?serviceKey={BUSAN_BIMS_SERVICE_KEY_DECODING}
  &pageNo=1
  &numOfRows=50
  &bstopid=505020000
```

그 다음 응답에서 `lineno == lane[].busNo`인 항목을 찾는다.

### 6-3. BIMS 저상버스 필드 해석

| BIMS 필드 | 의미 | 내부 필드 |
| --- | --- | --- |
| `min1` | 앞차 도착 예상 분 | `firstArrival.remainingMinutes` |
| `min2` | 뒷차 도착 예상 분 | `secondArrival.remainingMinutes` |
| `station1` | 앞차 남은 정류장 수 | `firstArrival.remainingStops` |
| `station2` | 뒷차 남은 정류장 수 | `secondArrival.remainingStops` |
| `lowplate1` | 앞차 저상 여부. `1`이면 저상 | `firstArrival.isLowFloor` |
| `lowplate2` | 뒷차 저상 여부. `1`이면 저상 | `secondArrival.isLowFloor` |
| `carno1` | 앞차 차량 번호 | `firstArrival.vehicleNo` |
| `carno2` | 뒷차 차량 번호 | `secondArrival.vehicleNo` |

```text
lowplate == "1" -> 저상버스
lowplate == "0" -> 일반버스
lowplate 없음 -> unknown
```

### 6-4. 일반 경로의 BUS 처리

일반 경로에서는 BIMS 도착정보가 있으면 대기시간을 보강하고, 없으면 ODsay 후보를 유지한다.

```text
BUS status:
- REALTIME_MATCHED: BIMS 도착정보 조회 성공
- ROUTE_MATCHED: 정류장/노선 ID는 있으나 현재 도착정보 없음
- MATCH_UNKNOWN: BIMS 매칭 실패
- INVALID: 정류장 해석 실패 또는 연결 불가
```

### 6-5. 휠체어 경로의 BUS 처리

휠체어 경로에서는 사용자가 정류장에 도착한 뒤 탈 수 있는 저상 차량만 확정 후보로 사용한다.

```text
reachableMinute =
  wheelchairWalkToBoardMinute
+ boardingBufferMinute

selectedLowFloorArrival =
  가장 작은 arrival.min
  where arrival.lowplate == 1
    and arrival.min >= reachableMinute
```

상태:

| 상태 | 조건 | 처리 |
| --- | --- | --- |
| `LOW_FLOOR_CONFIRMED` | 정류장 도착 가능 시각 이후 저상버스가 옴 | 확정 추천 |
| `LOW_FLOOR_TOO_EARLY` | 저상버스가 오지만 사용자가 도착하기 전에 지나감 | 다음 저상 정보 없으면 unknown 또는 제외 |
| `LOW_FLOOR_UNAVAILABLE` | 조회된 앞차/뒷차가 모두 일반버스 | confirmed 후보가 있으면 제외 |
| `LOW_FLOOR_UNKNOWN` | BIMS 응답 없음, 매칭 실패, 뒷차 이후 정보 없음 | confirmed 후보가 없을 때 별도 표시 |

---

## 7. SUBWAY leg 검증

### 7-1. 일반 경로의 SUBWAY 처리

일반 경로에서는 ODsay가 제공한 지하철 leg를 유지한다.

```text
사용 값:
- startName / endName
- startID / endID
- lane[].name
- sectionTime
- passStopList.stations[]
```

일반 경로의 지하철 보행 연결은 역 대표 좌표나 ODsay 도보 endpoint를 기준으로 GraphHopper 일반 보행 경로를 재계산한다.

### 7-2. 휠체어 경로의 SUBWAY 처리

휠체어 경로에서는 지하철역 대표 좌표로 안내하면 안 된다. 승차역/하차역/환승역의 엘리베이터 위치를 찾아 보행 endpoint를 교체해야 한다.

```text
1. ODsay SUBWAY leg에서 startID, endID 추출
2. subway_station_elevators에서 startID의 엘리베이터 후보 조회
3. subway_station_elevators에서 endID의 엘리베이터 후보 조회
4. 출발지 또는 이전 leg 위치에서 가장 적합한 승차역 엘리베이터 선택
5. 하차역에서는 목적지 또는 다음 leg 위치에 가장 적합한 엘리베이터 선택
6. WALK leg endpoint를 역 대표 좌표가 아니라 엘리베이터 좌표로 교체
7. 교체된 endpoint로 wheelchair GraphHopper 경로 재계산
```

휠체어 지하철 상태:

| 상태 | 조건 | 처리 |
| --- | --- | --- |
| `ELEVATOR_CONFIRMED` | 승차역/하차역 엘리베이터 확인 | 추천 가능 |
| `ELEVATOR_TRANSFER_CONFIRMED` | 환승역 내부 또는 외부 무장애 환승 가능 | 추천 가능 |
| `ELEVATOR_UNAVAILABLE` | 필요한 역에 엘리베이터 없음 | 후보 제외 |
| `ELEVATOR_UNKNOWN` | 역 ID 매칭 실패 또는 데이터 없음 | confirmed 후보가 없을 때 별도 표시 |

주의:

- 지하철 내부 환승 동선은 보행자도로 GraphHopper만으로 검증하기 어렵다.
- 내부 환승은 역 접근성 DB, 엘리베이터 위치, 환승 가능 여부 데이터를 별도로 둬야 한다.
- 실외 환승, 예를 들어 지하철 출구에서 버스 정류장까지 이동하는 구간은 wheelchair GraphHopper로 검증한다.

---

## 8. WALK leg 검증

### 8-1. 일반 경로의 WALK 처리

ODsay 도보 leg는 참고값으로만 사용한다. 최종 안내는 우리 보행자도로 GraphHopper로 재계산한다.

```text
origin -> 첫 승차 정류장/역
마지막 하차 정류장/역 -> destination
실외 환승 구간
```

### 8-2. 휠체어 경로의 WALK 처리

휠체어 경로에서는 wheelchair profile을 사용한다.

```text
검증 조건:
- 계단 없음
- 단절 구간 없음
- 급경사 penalty 또는 제외
- 너무 좁은 보도 penalty 또는 제외
- 횡단보도/보도 연결 가능
```

WALK leg가 실패하면 후보 전체를 invalid 처리한다. 대체 confirmed 후보가 없을 때만 partial 또는 unknown으로 표시할 수 있다.

---

## 9. 해운대역 -> 센텀역 PoC 결과

### 9-1. ODsay 상위 후보

| 후보 | 유형 | 승차 | 하차 | ODsay 노선 | ODsay 총시간 | ODsay 도보 |
| --- | --- | --- | --- | --- | ---: | ---: |
| 1 | 버스 | 해운대도시철도역 | SK텔레콤 | 181 | 21분 | 254m |
| 2 | 버스 | 해운대도시철도역 | 센텀고등학교 | 115-1, 31, 200, 100, 100-1 | 25분 | 555m |
| 3 | 지하철 | 해운대 | 민락 | 부산 2호선 | 20분 | 751m |
| 4 | 버스 | 해운대도시철도역 | 신세계센텀시티 | 141, 39, 63 | 27분 | 811m |
| 5 | 버스 | 해운대해수욕장 | SK텔레콤 | 307 | 28분 | 716m |

이 결과는 대중교통 전체 후보를 봐야 한다는 점을 보여준다. 상위 5개 안에 버스 후보뿐 아니라 지하철-only 후보도 포함되어 있다.

### 9-2. BIMS 저상 도착 확인

검증 시점의 해운대도시철도역 `bstopid=505020000` BIMS 도착정보:

| 노선 | lineid | 앞차 | 앞차 저상 | 뒷차 | 뒷차 저상 |
| --- | --- | ---: | --- | ---: | --- |
| 181 | 5200181000 | 8분 | Y | 29분 | N |
| 115-1 | 5200115100 | 6분 | N | 11분 | N |
| 31 | 5200031000 | 6분 | Y | 15분 | N |
| 200 | 5200200000 | 9분 | N | 22분 | N |
| 100 | 5200100000 | 14분 | N | 28분 | Y |
| 100-1 | 5200100100 | 13분 | N | 없음 | unknown |
| 141 | 5200141000 | 7분 | Y | 19분 | Y |
| 39 | 5200039000 | 5분 | Y | 17분 | Y |
| 63 | 5200063000 | 11분 | Y | 20분 | N |

검증 시점의 해운대해수욕장 `bstopid=185760201` BIMS 도착정보:

| 노선 | lineid | 앞차 | 앞차 저상 |
| --- | --- | ---: | --- |
| 307 | 5200307000 | 4분 | Y |

### 9-3. 임의 휠체어 보행시간 적용 결과

테스트에서는 GraphHopper 값을 대신해 임의 휠체어 보행시간을 적용했다.

```text
boardingBufferMinute = 2

후보 1: 해운대도시철도역까지 1분
후보 2: 해운대도시철도역까지 1분
후보 4: 해운대도시철도역까지 1분
후보 5: 해운대해수욕장까지 12분
```

버스 후보 판정:

| 후보 | 선택 노선 | 저상 도착 | reachableMinute | 상태 | 판단 |
| --- | --- | ---: | ---: | --- | --- |
| 1 | 181 | 8분 | 3분 | `LOW_FLOOR_CONFIRMED` | 추천 가능 |
| 2 | 31 | 6분 | 3분 | `LOW_FLOOR_CONFIRMED` | 추천 가능 |
| 4 | 39 | 5분 | 3분 | `LOW_FLOOR_CONFIRMED` | 추천 가능 |
| 5 | 307 | 4분 | 14분 | `LOW_FLOOR_TOO_EARLY` | 현재 앞차는 놓침 |

지하철 후보 판정은 별도 데이터가 필요하다.

```text
후보 3: 해운대 -> 민락, 부산 2호선
필요 검증:
- 해운대역 승차 엘리베이터 존재 여부
- 민락역 하차 엘리베이터 존재 여부
- 엘리베이터 좌표 기준 origin/destination 보행 재계산
```

따라서 최종 휠체어 추천은 저상버스 후보와 지하철 엘리베이터 confirmed 후보를 같은 ranking pool에 넣어 비교해야 한다.

### 9-4. 테스트에서 나온 구현 개선점

- ODsay 후보는 버스만이 아니라 지하철과 혼합 경로까지 모두 평가해야 한다.
- BUS leg는 `lane[]` 전체를 검증해야 한다.
- ODsay `startID`를 BIMS `bstopid`로 직접 쓰면 안 된다.
- 부산 BIMS 매칭의 우선 키는 `localStationID -> bstopid`, `busLocalBlID -> lineid`다.
- 휠체어 BUS 검증은 정적 노선 DB보다 실시간 `lowplate1/lowplate2`가 우선이다.
- 휠체어 SUBWAY 검증은 역 대표 좌표가 아니라 엘리베이터 좌표를 기준으로 해야 한다.
- 휠체어 WALK 검증은 모든 실외 이동 구간에 적용해야 한다.

---

## 10. 최종 후보 상태 모델

후보 전체 상태는 leg 상태를 종합해 결정한다.

| 후보 상태 | 의미 | 처리 |
| --- | --- | --- |
| `CONFIRMED` | 모든 필수 leg가 현재 프로필 기준 검증됨 | 추천 가능 |
| `PARTIAL` | 일부 leg가 검증되지 않았지만 대체 confirmed가 없음 | 별도 섹션 표시 |
| `UNKNOWN` | 외부 API 실패 또는 데이터 부재로 판단 불가 | 낮은 우선순위 |
| `INVALID` | 필수 접근성 조건 실패 | 제외 |

휠체어 후보의 invalid 조건:

```text
- WALK leg wheelchair 경로 없음
- BUS leg에서 탑승 가능 시각 이후 저상버스 없음
- SUBWAY 승차역/하차역 엘리베이터 없음
- 실외 환승 구간 wheelchair 경로 없음
- 지하철 내부 환승 접근성 검증 실패
```

---

## 11. DB와 캐시 판단

### 11-1. 저상버스 검증에 필수 DB는 아니다

이번 PoC에서는 ODsay 응답만으로 BIMS 조회에 필요한 값이 확보됐다.

```text
ODsay localStationID -> BIMS bstopid
ODsay busLocalBlID -> BIMS lineid
ODsay arsID -> BIMS busStopList fallback
ODsay busNo -> BIMS lineno fallback
```

따라서 저상버스 검증 자체를 위해 정류장 매핑 테이블을 선구축할 필요는 없다.

### 11-2. 그래도 snap cache는 필요해질 수 있다

정류장/역/엘리베이터와 우리 보행자 GraphHopper graph를 안정적으로 연결하려면 snap cache가 유용하다.

```text
transit_access_point_snap_cache
- provider
- provider_place_id
- local_station_id
- ars_id
- type: BUS_STOP | SUBWAY_STATION | SUBWAY_ELEVATOR
- name
- lat
- lng
- nearest_pedestrian_node_id
- wheelchair_snap_status
- snap_distance_meter
- updated_at
```

이 캐시는 대중교통 경로 생성용이 아니라 보행자 graph 연결 안정화용이다.

### 11-3. 실시간 도착정보는 TTL 캐시

BIMS 도착정보는 영구 저장하지 않는다.

```text
key = bims:arrival:{bstopid}:{lineid}
ttl = 20~60초
value = min1, min2, station1, station2, lowplate1, lowplate2, carno1, carno2, fetchedAt
```

---

## 12. 실 구현 체크리스트

- [ ] 1km 초과 시 ODsay `searchPubTransPathT`를 먼저 호출한다.
- [ ] ODsay path를 WALK / BUS / SUBWAY leg list로 변환한다.
- [ ] 버스만 따로 추천하지 말고 모든 ODsay 후보를 같은 candidate pool에서 평가한다.
- [ ] WALK leg는 ODsay 도보 안내를 그대로 쓰지 않고 GraphHopper로 재계산한다.
- [ ] 일반 경로의 WALK leg는 일반 보행 profile을 사용한다.
- [ ] 휠체어 경로의 WALK leg는 wheelchair profile을 사용한다.
- [ ] BUS leg의 `lane[]` 전체를 lane option으로 펼친다.
- [ ] BUS 승차 정류장 ID는 `passStopList.stations[0].localStationID`를 우선 사용한다.
- [ ] BUS 하차 정류장 ID는 `passStopList.stations[last].localStationID`를 우선 사용한다.
- [ ] BUS 노선 ID는 `lane[].busLocalBlID`를 우선 사용한다.
- [ ] ODsay `startID`를 BIMS `bstopid`로 사용하지 않는다.
- [ ] 휠체어 BUS 검증에서는 `lowplate == 1`이고 `arrival.min >= reachableMinute`인 차량만 confirmed 처리한다.
- [ ] SUBWAY leg는 `startID`, `endID`, `lane[].name`, `sectionTime`을 파싱한다.
- [ ] 휠체어 SUBWAY 검증에서는 승차역/하차역/환승역 엘리베이터를 확인한다.
- [ ] 휠체어 SUBWAY 연결 WALK leg의 endpoint를 엘리베이터 좌표로 교체한다.
- [ ] 환승 경로에서는 각 leg의 누적 도착 가능 시간을 다시 계산한다.
- [ ] confirmed 후보가 하나라도 있으면 invalid/unavailable 후보는 제외한다.
- [ ] confirmed 후보가 없으면 unknown/partial 후보를 별도 섹션으로 반환한다.

---

## 13. 구현 우선순위

1. ODsay path를 공통 leg list로 파싱한다.
2. WALK leg를 GraphHopper로 재계산한다.
3. BUS leg와 BIMS 식별자 매칭을 구현한다.
4. 일반 대중교통 후보 ranking을 먼저 완성한다.
5. 휠체어 BUS 저상버스 검증을 추가한다.
6. 휠체어 SUBWAY 엘리베이터 검증과 endpoint 교체를 추가한다.
7. 환승 경로의 누적 시간 계산과 partial/unknown 분리를 추가한다.
8. 마지막으로 BIMS TTL cache와 access point snap cache를 붙인다.

