# 키워드 발굴용 네이버 플레이스 순위 수집기 설계

- 작성일: 2026-09-02
- 대상 저장소: `C:\workspace\brand_analyze`
- 대상 DB: 기존 `naverDB`의 신규 독립 테이블 2개
- 상태: 설계 승인 완료, 구현 전

## 1. 목적

외식업 매장의 빈집 키워드와 핵심 경쟁 키워드를 판정하려면 검색어별 자사 순위만이 아니라 상위·비교 그룹의 전체 매장 구성이 필요하다. 신규 수집기는 네이버 플레이스 검색 결과를 검색어·위치·기기 조건별 스냅샷으로 수집하고, 화면에 노출된 매장 1~20위를 구조화해 저장한다.

신규 수집기는 기존 `C:\workspace\naver_crawling`의 자사 순위 수집기를 수정하거나 import하지 않는다. 기존 수집기에서 검증된 검색 상태 판정 개념만 새 모듈과 테스트로 이식한다.

## 2. 범위

### 2.1 포함

- 초기 엑셀 입력과 향후 DB 입력을 동일한 `SearchTask` 계약으로 변환
- 검색어·매장 좌표·기기 조건별 네이버 플레이스 검색
- 검색 URL과 요청 검색어 일치 검증
- 결과·결과 없음·오류·타임아웃 상태 구분
- DOM 카드 기반 검색 결과 1~20위 수집
- 플레이스 ID, 매장명, 카테고리, 광고 여부, 상세 URL, 거리 수집
- 자사 매장 식별
- 신규 스냅샷·결과 테이블 저장
- 작업별 재시도, 부분 결과, 트랜잭션 및 실패 산출물 보관
- 모바일 기본 수집과 일부 PC 교차검증

### 2.2 제외

- 기존 `naver_place_rank` 스키마 또는 기존 수집기 변경
- 경쟁점 `keywordList`, 메뉴, 리뷰 상세 수집
- 빈집·핵심 경쟁 최종 점수 계산
- 후보 키워드 자동 생성
- 정기 스케줄러 등록
- 구조화 JSON과 DOM 결과의 이중 파싱

후속 단계는 신규 결과 테이블의 `place_id`와 `detail_url`을 입력으로 사용한다.

## 3. 독립성 원칙

- 신규 코드는 `brand_analyze`에만 둔다.
- 기존 `naver_crawling` 코드를 직접 import하지 않는다.
- 기존 입력 엑셀과 기존 DB 테이블에 의존하지 않는다.
- 신규 `.env` 설정과 신규 로그·산출물 경로를 사용한다.
- 기존 `naverDB`에는 신규 테이블 2개만 생성한다.
- 신규 수집기 장애는 기존 자사 순위 수집에 영향을 주지 않는다.

## 4. 아키텍처

```text
TaskSource
├─ ExcelTaskSource       초기 파일럿
└─ DatabaseTaskSource    후속 자동화

          ↓ SearchTask

SearchExecutor
└─ 모바일·PC 브라우저 검색과 상태 검증

          ↓ SearchPage

DomResultParser
└─ 검색 결과 카드 전체 구조화

          ↓ ParsedSearch

ResultValidator
└─ 순위·필수필드·중복·종료 상태 검증

          ↓ SearchSnapshot + SearchResult[]

SnapshotRepository
└─ 신규 테이블 2개에 작업 단위 트랜잭션 저장
```

### 4.1 모듈 구성

```text
scripts/
  keyword_discovery_rank/
    config.py
    models.py
    task_source.py
    browser.py
    parser.py
    validation.py
    collector.py
    repository.py
    cli.py
```

| 모듈 | 책임 |
|---|---|
| `config.py` | `.env`, 조회 기기, 결과 한도, 경로 설정 |
| `models.py` | 입력·페이지·스냅샷·결과 데이터 모델 |
| `task_source.py` | 엑셀·DB 입력을 `SearchTask`로 변환 |
| `browser.py` | 브라우저 생성, 위치·기기 설정, 검색 상태 대기 |
| `parser.py` | DOM 결과 카드 구조화 |
| `validation.py` | 결과 순서, 필수필드, 종료 여부 검증 |
| `collector.py` | 중복 제거, 재시도, 세션 복구, 작업 오케스트레이션 |
| `repository.py` | 신규 테이블 저장과 작업별 트랜잭션 |
| `cli.py` | 명령행 진입점과 실행 요약 |

## 5. 입력 인터페이스

### 5.1 공통 검색 작업

```text
SearchTask
- task_id
- query
- target_store_id
- target_store_name
- location_name
- latitude
- longitude
- device_type
- source_type
- source_id
```

`TaskSource`는 입력 매체와 관계없이 `SearchTask` 목록을 반환한다. 수집기와 파서는 엑셀 열이나 DB 스키마를 알지 못한다.

### 5.2 초기 엑셀

```text
inputs/keyword_discovery_queries.xlsx
```

필수 열:

| 열 | 설명 |
|---|---|
| `검색어` | 조회할 후보 키워드 |
| `기준매장ID` | 내부 자사 매장 ID |
| `기준매장명` | 사람이 확인할 매장명 |
| `조회위치명` | 좌표 설명 |
| `위도` | 조회 위도 |
| `경도` | 조회 경도 |

선택 열:

| 열 | 기본값 |
|---|---|
| `기기` | `MOBILE` |
| `소스ID` | 엑셀 행 번호 기반 값 |

### 5.3 향후 DB 입력

`DatabaseTaskSource`는 내부 후보 테이블에서 순위 수집 대상 후보를 조회해 동일한 `SearchTask`로 변환한다. 이 전환 시 브라우저, 파서, 검증, 저장 로직은 변경하지 않는다.

## 6. 조회 조건

### 6.1 고유 검색 작업

```text
normalized_query
+ target_store_id
+ latitude
+ longitude
+ device_type
```

이 조합을 SHA-256으로 해시해 `task_key`를 만든다. 동일 `run_id + task_key`는 한 번만 실행한다. 다른 실행에서는 순위 변화를 기록해야 하므로 새 스냅샷을 생성한다.

### 6.2 기기

- 기본값은 `MOBILE`이다.
- 모바일 User-Agent, 모바일 화면 크기, 모바일 검색 화면을 함께 적용한다.
- DB의 `device_type`은 `MOBILE` 또는 `PC`이며 `NULL`을 허용하지 않는다.
- 파일럿 검색어 일부만 동일 위치·유사 시간대에 PC와 교차검증한다.

### 6.3 위치

- 초기 기준 위치는 분석 대상 자사 매장 좌표다.
- 위도·경도를 입력 단계에서 필수 검증한다.
- 위치명과 좌표를 스냅샷에 저장해 반복 측정 조건을 재현한다.

### 6.4 검색 범위

- 초기 목표는 화면 기준 최대 20개 결과다.
- 20개 미만이어도 페이지 끝이 확인되면 정상 성공이다.
- 광고 결과는 화면 위치에는 포함하지만 자연순위에는 포함하지 않는다.

## 7. 검색 상태 검증

기존 수집기의 다음 개념을 신규 코드와 테스트로 이식한다.

- 현재 URL의 query와 요청 검색어 일치 확인
- 검색 결과 카드 존재 확인
- `검색결과가 없습니다` 상태 확인
- 오류 페이지 문구 확인
- 일치하는 검색어 페이지가 나타나지 않으면 `QUERY_MISMATCH`
- 제한 시간 내 결과 상태가 확정되지 않으면 `LOAD_TIMEOUT`

이전 검색 결과를 신규 결과로 오인하지 않도록 URL 일치가 선행 조건이다.

## 8. DOM 결과 파싱

### 8.1 선택한 방식

초기 구현은 DOM 단일 파서를 사용한다. 구조화 JSON 파서와의 완전 대조는 초기 범위에서 제외한다.

DOM 결과 카드에서 다음을 추출한다.

- 화면 전체 순서
- 광고 제외 자연순위
- 플레이스 ID
- 매장명
- 카테고리
- 광고 여부
- 상세 URL
- 거리 원문

### 8.2 로딩 완료

다음 중 하나를 만족할 때 결과 로딩을 완료로 본다.

1. 요청 결과 수 20개에 도달
2. 추가 로딩을 시도해도 카드 수가 더 증가하지 않고 페이지 끝 요소를 확인

카드 수가 증가하지 않았지만 페이지 끝을 확인하지 못하면 `PARTIAL` 또는 `LOAD_TIMEOUT`으로 처리한다.

### 8.3 자동 검증

- `raw_position`이 1부터 연속인지 확인
- 자연 결과의 `organic_rank`가 1부터 연속인지 확인
- 광고 결과의 `organic_rank`가 `NULL`인지 확인
- 플레이스 ID와 매장명이 존재하는지 확인
- 상세 URL과 플레이스 ID가 일치하는지 확인
- 화면 카드 수와 저장 가능한 결과 수를 비교
- 결과가 20개 미만이면 페이지 끝 확인 여부를 검사

정상 결과만 있으면 `SUCCESS`, 일부 카드의 필수필드가 누락되면 `PARTIAL`이다.

## 9. 자사 매장 판정

자사 판정 우선순위:

```text
1. PLACE_ID
2. MANUAL_MAPPING
3. EXACT_NAME
4. NORMALIZED_NAME
5. NONE
```

`PLACE_ID`와 `MANUAL_MAPPING`은 높은 신뢰도로 사용한다. `NORMALIZED_NAME` 판정은 파일럿 검토 대상이다. 결과 테이블에는 `is_own_store`, `matched_store_id`, `match_method`를 함께 저장한다.

## 10. DB 설계

### 10.1 스냅샷 테이블

```text
dbo.naver_keyword_discovery_snapshot
```

| 컬럼 | SQL Server 형식 | 설명 |
|---|---|---|
| `snapshot_id` | `bigint IDENTITY` | 기본키 |
| `run_id` | `uniqueidentifier` | 실행 묶음 |
| `task_key` | `char(64)` | 검색 작업 해시 |
| `query` | `nvarchar(255)` | 원본 검색어 |
| `normalized_query` | `nvarchar(255)` | 수집 당시 정규화 검색어 |
| `target_store_id` | `nvarchar(100)` | 기준 자사 매장 ID |
| `target_store_name` | `nvarchar(200)` | 기준 자사 매장명 |
| `location_name` | `nvarchar(200)` | 조회 위치 설명 |
| `latitude` | `decimal(10,7)` | 조회 위도 |
| `longitude` | `decimal(10,7)` | 조회 경도 |
| `device_type` | `varchar(10)` | `MOBILE` 또는 `PC` |
| `source_type` | `varchar(20)` | `EXCEL` 또는 `DATABASE` |
| `source_id` | `nvarchar(100)` | 입력 원본 식별자 |
| `requested_result_limit` | `smallint` | 목표 결과 수 |
| `observed_result_count` | `smallint` | 화면에서 발견한 카드 수 |
| `result_end_reached` | `bit` | 실제 결과 끝 확인 여부 |
| `collect_status` | `varchar(30)` | 최종 수집 상태 |
| `collect_msg` | `nvarchar(1000)` | 오류·진단 요약 |
| `parser_version` | `varchar(30)` | 파서 버전 |
| `final_url` | `nvarchar(2000)` | 실제 검색 완료 URL |
| `collected_at` | `datetime2(0)` | 수집 시점 |

수집 상태:

```text
SUCCESS
NO_RESULT
PARTIAL
LOAD_TIMEOUT
QUERY_MISMATCH
PARSER_ERROR
SEARCH_ERROR
VALIDATION_ERROR
```

테이블 주요 제약:

```text
PRIMARY KEY (snapshot_id)
UNIQUE (run_id, task_key)
CHECK device_type IN ('MOBILE', 'PC')
CHECK source_type IN ('EXCEL', 'DATABASE')
CHECK latitude BETWEEN -90 AND 90
CHECK longitude BETWEEN -180 AND 180
CHECK observed_result_count >= 0
```

### 10.2 결과 테이블

```text
dbo.naver_keyword_discovery_result
```

| 컬럼 | SQL Server 형식 | 설명 |
|---|---|---|
| `snapshot_id` | `bigint` | 부모 스냅샷 |
| `raw_position` | `smallint` | 광고 포함 화면 전체 순서 |
| `organic_rank` | `smallint NULL` | 광고 제외 자연순위 |
| `place_id` | `varchar(50)` | 네이버 플레이스 ID |
| `place_name` | `nvarchar(300)` | 매장명 |
| `category` | `nvarchar(300) NULL` | 표시 카테고리 |
| `is_ad` | `bit` | 광고 여부 |
| `detail_url` | `nvarchar(2000)` | 상세 페이지 URL |
| `distance_text` | `nvarchar(100) NULL` | 화면의 거리 원문 |
| `is_own_store` | `bit` | 자사 여부 |
| `matched_store_id` | `nvarchar(100) NULL` | 내부 자사 매장 ID |
| `match_method` | `varchar(30)` | 자사 판정 방법 |

주요 제약:

```text
PRIMARY KEY (snapshot_id, raw_position)
FOREIGN KEY (snapshot_id)
  REFERENCES dbo.naver_keyword_discovery_snapshot(snapshot_id)
CHECK raw_position >= 1
CHECK organic_rank IS NULL OR organic_rank >= 1
```

자연순위 중복 방지를 위한 SQL Server 필터 인덱스:

```sql
CREATE UNIQUE INDEX UX_naver_keyword_discovery_result_snapshot_organic_rank
ON dbo.naver_keyword_discovery_result(snapshot_id, organic_rank)
WHERE organic_rank IS NOT NULL;
```

동일 플레이스가 광고와 자연 결과에 모두 등장할 수 있으므로 `(snapshot_id, place_id)` 고유 제약은 두지 않는다.

### 10.3 인덱스

```text
snapshot(query, collected_at)
snapshot(target_store_id, collected_at)
snapshot(collect_status, collected_at)
snapshot(run_id)
result(place_id, snapshot_id)
result(snapshot_id, is_ad, organic_rank)
result(is_own_store, matched_store_id)
```

## 11. 재시도와 실패 처리

### 11.1 재시도 대상

- 페이지 로딩 실패
- 검색 상태 대기 초과
- 검색어 URL 불일치
- 브라우저 세션 오류
- 결과 카드 로딩 중단

최초 시도 후 최대 2회 재시도한다. 재시도 내역은 로그에 기록하고 DB에는 최종 결과만 저장한다.

### 11.2 재시도하지 않는 상태

- 입력 검증 실패
- 위도·경도 누락 또는 범위 오류
- 지원하지 않는 기기
- 명시적인 검색 결과 없음
- 필수 DOM 구조 변경에 따른 파서 오류

### 11.3 부분 결과

화면 카드 수보다 정상 파싱 결과가 적으면 `PARTIAL`로 기록하고 검증을 통과한 결과만 저장한다. 자동 빈집·경쟁 판정에서는 `PARTIAL`을 기본 제외한다.

### 11.4 실행 지속

- 개별 작업 실패는 스냅샷으로 기록하고 다음 작업을 계속한다.
- 브라우저 세션 손상 시 브라우저를 재생성한다.
- 인증 또는 DB 연결 자체가 불가능하면 전체 실행을 중단한다.
- 동일 오류가 연속 5회 발생하면 전체 실행을 중단한다. 이 값은 설정으로 관리한다.

## 12. 실패 산출물

다음 상태에서만 HTML과 스크린샷을 저장한다.

```text
PARTIAL
LOAD_TIMEOUT
QUERY_MISMATCH
PARSER_ERROR
SEARCH_ERROR
```

표준 경로:

```text
artifacts/keyword_discovery_rank/{run_id}/{task_key}/page.html
artifacts/keyword_discovery_rank/{run_id}/{task_key}/screenshot.png
```

DB 경로 컬럼은 두지 않고 `run_id + task_key`로 계산한다.

## 13. 저장 트랜잭션

검색 작업 하나가 독립 저장 단위다.

```text
BEGIN TRANSACTION
→ 스냅샷 INSERT
→ 정상 결과 일괄 INSERT
→ 제약조건과 행 수 검증
→ COMMIT
```

결과 INSERT 실패 시 해당 작업만 롤백하고 다음 작업을 계속한다. `NO_RESULT`와 최종 파싱 실패는 결과 행 없이 스냅샷만 저장한다.

## 14. 테스트 전략

### 14.1 단위 테스트

- 엑셀 필수 시트·헤더·좌표 검증
- 기기 생략 시 `MOBILE` 기본값
- 동일 `task_key` 중복 제거
- URL query 일치와 이전 검색 결과 차단
- 결과·결과 없음·오류·타임아웃 판정
- 자연 결과·광고 혼합 DOM 파싱
- 플레이스 ID·카테고리·거리 추출
- `raw_position`과 `organic_rank` 연속성
- 20개 미만 결과의 페이지 끝 판정
- 필수 필드 누락 시 `PARTIAL`
- 작업별 트랜잭션과 롤백
- 동일 `run_id + task_key` 중복 저장 방지

### 14.2 라이브 스모크 테스트

1. 검색어 1개, 결과 5개, DB 롤백, 화면·HTML 수동 대조
2. 검색어 3개, 결과 20개, DB 롤백, 순위·ID·광고·거리 대조
3. 매장 1개, 후보 5개, 신규 테이블 실제 저장 및 재조회

## 15. 파일럿

### 15.1 범위

```text
상권 유형이 다른 육수당 매장 5개
× 매장당 후보 5개
× 후보당 최대 20개 결과
= 기본 검색 작업 25개, 최대 결과 500행
```

대표 검색어 10개는 동일 위치·유사 시간대에서 모바일과 PC를 각각 한 번 수집해 상위 결과 일치율과 순위 차이를 확인한다. 정기 수집 기본값은 모바일로 유지한다.

### 15.2 사람 검토

- 화면과 저장 순위 일치
- 광고·자연 결과 구분
- 플레이스 ID와 상세 URL 일치
- 카테고리와 거리 원문 정확성
- 동일 경쟁점의 플레이스 ID 일관성
- 자사 매장 판정과 `match_method`
- 20개 미만 결과의 실제 페이지 끝 확인
- `PARTIAL` 판정 적절성

### 15.3 성공 기준

```text
자동 테스트 전체 통과
필수 필드 파싱 성공률 95% 이상
플레이스 ID 정확도 100%
순위 정확도 100%
자사 매장 오인 0건
광고·자연 결과 구분 오류 0건
작업 실패의 다른 작업 영향 0건
동일 실행 내 중복 스냅샷 0건
20개 미만 종료 판정 오류 0건
```

카테고리와 거리 원문은 화면에 표시된 경우의 정확도를 평가하며 존재율 자체를 성공 기준으로 삼지 않는다.

## 16. 후속 확장

수집기가 파일럿 성공 기준을 통과한 뒤 다음 순서로 확장한다.

```text
경쟁점 place_id 확보
→ 경쟁점 keywordList 수집
→ 메뉴·영업·시설 연결
→ 방문자·블로그 리뷰 연결
→ 상위·비교 그룹 지표 계산
→ 빈집·핵심 경쟁 판정
→ ExcelTaskSource를 DatabaseTaskSource로 전환
```

## 17. 확정 요약

기존 자사 순위 수집기는 변경하지 않는다. 신규 수집기는 `brand_analyze`에서 독립적으로 실행하고 기존 `naverDB`의 신규 스냅샷·결과 테이블 두 개에만 적재한다. 초기 입력은 엑셀이며 향후 DB 입력으로 교체하되 `SearchTask` 이후의 수집 흐름은 동일하게 유지한다. 모바일·매장 좌표를 기본 검색 조건으로 사용하고, DOM 단일 파서와 강한 자동 검증으로 예외 건만 재검토한다.
