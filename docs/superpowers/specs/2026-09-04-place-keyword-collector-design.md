# 네이버 플레이스 대표키워드 수집기 설계

## 1. 목적

네이버 검색 결과의 상위 경쟁 매장이 설정한 `keywordList`를 수집하여 후속 키워드 평가 모듈이 전문 최적화 매장 비율을 계산할 수 있게 한다.

이 모듈은 대표키워드 원문을 수집하고 최소한으로 정규화하는 책임만 가진다. 동의어·유사어 판정, 경쟁도 계산, 빈집·경쟁·제외 분류는 후속 평가 모듈의 책임이다.

## 2. 범위

### 포함

- 순위 수집 실행에서 검색어별 자연순위 상위 매장 추출
- Place ID 중복 제거
- 네이버 플레이스 상세 페이지의 직렬화 데이터에서 `keywordList` 추출
- 월별 재확인 정책
- 변경 감지와 버전 이력 보존
- 실패 시 직전 성공 결과 보존
- 스냅샷 및 키워드 결과 DB 적재
- dry-run, rollback-test, 강제 갱신 지원

### 제외

- 동의어·유사어 통합
- 후보 검색어와 대표키워드의 의미 유사도 계산
- 전문 최적화 매장 비율 계산
- 빈집·경쟁·제외 판정
- 광고 카드의 경쟁도 반영
- 비공개 내부 API 의존

## 3. 입력

기본 입력은 기존 `dbo.naver_keyword_discovery_snapshot` 및 `dbo.naver_keyword_discovery_result`이다. CLI가 `rank_run_id`를 받아 해당 실행의 `SUCCESS` 또는 `PARTIAL` 검색 결과에서 다음 조건으로 대상을 선택한다.

- `organic_rank IS NOT NULL`
- `is_ad = 0`
- `organic_rank <= top_n`
- `place_id`가 비어 있지 않음

기본 `top_n`은 10이다. 여러 검색어에 같은 Place ID가 나타나도 한 실행에서 한 번만 수집한다. 검색어와 당시 순위는 기존 순위 결과 테이블에서 역추적하며 대표키워드 테이블에 중복 저장하지 않는다.

## 4. 수집 방식

### 4.1 URL

```text
https://m.place.naver.com/restaurant/{place_id}/home
```

`view-source:`는 브라우저 표시 기능이므로 자동화 URL에 붙이지 않는다. Selenium으로 일반 URL을 열고 브라우저가 받은 페이지 원문을 사용한다.

### 4.2 파싱

1. HTML의 `<script>` 및 직렬화 데이터 영역을 탐색한다.
2. JSON 또는 JavaScript 문자열 이스케이프를 해제한다.
3. 객체 트리를 재귀 순회하여 `keywordList`를 찾는다.
4. 같은 매장 객체의 `id`가 요청한 Place ID와 일치하는지 확인한다.
5. 일치하는 배열의 순서와 원문을 보존한다.

단순 정규식만으로 배열을 확정하지 않는다. 정규식은 직렬화 데이터 후보 영역 탐색에만 사용할 수 있다.

### 4.3 최소 정규화

- `raw_keyword`: 네이버 원문 그대로 저장
- `normalized_keyword`: 앞뒤 공백 제거, 연속 공백 통합, 유니코드 NFKC 정규화, 영문 casefold
- 빈 문자열 제거
- 동일 배열 안의 완전 중복 제거
- 원문 배열 순서는 `keyword_order`로 보존

`순대국`과 `순댓국`처럼 의미가 유사한 표현은 합치지 않는다.

## 5. 수집 상태

| 상태 | 의미 |
|---|---|
| `SUCCESS` | 하나 이상의 대표키워드를 정상 추출 |
| `EMPTY` | 대상 매장 객체를 확인했으나 배열이 비어 있음 |
| `BLOCKED` | 네이버 접근 제한 페이지 확인 |
| `LOAD_TIMEOUT` | 제한 시간 안에 페이지 원문 확보 실패 |
| `PLACE_MISMATCH` | 발견한 객체의 Place ID가 요청 대상과 불일치 |
| `PARSE_ERROR` | 정상 페이지로 보이나 구조를 해석하지 못함 |

`EMPTY`는 실패가 아니라 대표키워드 미설정이라는 정상 관측값이다.

## 6. 갱신 정책

기본 정책은 `MONTHLY`이며 마지막 확인 시각으로부터 한 달이 지난 Place ID만 다시 확인한다.

- `--refresh-policy monthly`: 기본, 한 달 경과 후 재확인
- `--refresh-policy weekly`: 7일 경과 후 재확인
- `--force-refresh`: 경과 기간과 무관하게 재확인

각 재확인에서 정규화한 배열의 순서를 포함해 결정적 해시를 만든다. 직전 유효 배열과 해시가 같으면 확인 이력만 남기고 키워드 결과 행을 중복 저장하지 않는다. 해시가 다르면 새 유효 버전과 키워드 결과를 저장한다.

## 7. 실패 정책

- 매장별 최대 3회 시도
- `BLOCKED`와 `LOAD_TIMEOUT`은 간격을 두고 재시도
- `PARSE_ERROR`와 `PLACE_MISMATCH`는 증거를 저장하고 동일 실행에서 재시도하지 않음
- 동일 실패가 연속 5개 매장에서 발생하면 실행 중단
- 실패 스냅샷이 직전 성공 결과를 삭제하거나 덮어쓰지 않음
- 직전 성공 또는 `EMPTY` 결과가 있으면 `effective_snapshot_id`로 유지하고 후속 평가에서 `STALE`로 식별 가능하게 함

## 8. 저장 구조

### 8.1 `dbo.naver_place_keyword_snapshot`

매번 확인한 사실을 기록한다.

| 컬럼 | 역할 |
|---|---|
| `snapshot_id` | 스냅샷 식별자 |
| `run_id` | 대표키워드 수집 실행 식별자 |
| `rank_run_id` | 입력이 된 순위 수집 실행 식별자 |
| `place_id` | 대상 네이버 Place ID |
| `place_name` | 순위 결과에서 확인한 매장명 |
| `source_url` | 상세 페이지 URL |
| `collect_status` | 수집 상태 |
| `collect_method` | 초기값 `BROWSER` |
| `content_hash` | 정상 관측 배열의 결정적 해시 |
| `is_changed` | 직전 유효 버전 대비 변경 여부 |
| `effective_snapshot_id` | 현재 유효 배열이 저장된 스냅샷 |
| `keyword_count` | 유효 배열 키워드 수 |
| `parser_version` | 파서 버전 |
| `collect_msg` | 제한된 길이의 오류 또는 진단 메시지 |
| `checked_at` | 확인 시각 |

변경이 없는 성공 확인과 실패도 새 스냅샷으로 기록한다. `effective_snapshot_id`는 키워드 결과가 실제 저장된 최신 유효 스냅샷을 가리킨다.

### 8.2 `dbo.naver_place_keyword_result`

배열이 변경된 `SUCCESS` 또는 `EMPTY` 버전에 귀속된다. `EMPTY` 버전은 결과 행이 0개다.

| 컬럼 | 역할 |
|---|---|
| `snapshot_id` | 유효 스냅샷 FK |
| `keyword_order` | 원문 배열 순서 |
| `raw_keyword` | 원문 대표키워드 |
| `normalized_keyword` | 최소 정규화 키워드 |

동일 스냅샷에서 `keyword_order`는 유일해야 한다.

## 9. 데이터 흐름과 구성요소

```text
RankResultSource
  → TargetSelector(top_n=10, organic only, deduplicate)
  → RefreshPolicy(monthly default)
  → PlacePageBrowser
  → KeywordListParser
  → ChangeDetector
  → PlaceKeywordRepository
```

- `RankResultSource`: `rank_run_id`로 수집 대상 조회
- `TargetSelector`: 광고 제외, 자연순위 상위 N개, Place ID 중복 제거
- `RefreshPolicy`: 마지막 확인 시각과 실행 옵션으로 재수집 여부 판정
- `PlacePageBrowser`: 페이지 이동, 상태 판정, 원문 및 실패 증거 확보
- `KeywordListParser`: 대상 매장 객체 검증과 배열 추출
- `ChangeDetector`: 최소 정규화 배열 해시 및 변경 여부 계산
- `PlaceKeywordRepository`: 두 테이블을 한 트랜잭션으로 저장

각 구성요소는 입력 방식, 브라우저, 파싱 및 저장을 서로 교체할 수 있도록 독립 인터페이스로 둔다.

## 10. CLI

```powershell
python scripts/run_place_keyword_collector.py `
  --rank-run-id d32fbdc3-3af6-4d25-85e1-fe6970855df1
```

지원 옵션:

```text
--top-n 10
--refresh-policy monthly|weekly
--include-place-id PLACE_ID
--force-refresh
--dry-run
--rollback-test
```

기본값은 `--top-n 10 --refresh-policy monthly`이다.
`--include-place-id`는 반복 지정할 수 있으며, 지정된 경우 순위 실행의 수집 대상 중
해당 Place ID만 남긴다. 순위 실행에 존재하지 않는 Place ID가 하나라도 있으면 입력
오류로 종료한다. 이 옵션은 소량 검증과 특정 매장 장애 재수집에 사용한다.

## 11. 검증 기준

### 자동 테스트

- 사용자 제공 원문 fixture에서 `순대`, `순댓국`, `국밥`, `수육`을 순서대로 추출
- 빈 배열과 키 미발견 구분
- 다른 객체의 `keywordList` 오인 방지
- 접근 제한 페이지 상태 판정
- 광고 제외 및 자연순위 상위 10개 선택
- 여러 검색어의 동일 Place ID 중복 제거
- 월별 주기 이내 대상은 브라우저 미호출
- 동일 해시는 결과 행 미생성 및 이전 유효 버전 연결
- 변경 해시는 신규 결과 생성
- 실패 시 이전 유효 버전 유지
- 트랜잭션 오류 시 전체 매장 단위 롤백
- 비밀정보가 로그와 증거에 노출되지 않음

### 실제 소량 검증

다음 3개 Place ID로 시작한다.

- `13149768`: 농민백암순대 본점
- `12006259`: 선릉설렁탕
- `31076466`: 한촌설렁탕 선릉역점

소량 검증에서 원문 대조, DB 적재, 같은 실행 재수행 시 재사용, 강제 갱신 시 변경 감지를 확인한 뒤 현재 순위 실행의 전체 고유 Place ID로 확대한다.

## 12. 운영 및 확장

- 초기 운영은 월 1회 전체 활성 분석 범위에 실행한다.
- 키워드 변경 실험 대상은 선택적으로 주 1회 실행할 수 있다.
- 분기 분석 시작 시 `--force-refresh`로 대상 전체를 재확인할 수 있다.
- 향후 HTTP 수집이 안정적으로 검증되면 `collect_method=HTTP` 어댑터를 추가할 수 있지만 초기 구현은 브라우저만 사용한다.
- 후속 평가 모듈은 `effective_snapshot_id`의 키워드를 읽고 수집 상태가 실패이면 `STALE`을 함께 표시한다.

## 13. 완료 조건

- 신규 테이블 DDL과 검증 SQL이 제공됨
- 전체 자동 테스트 통과
- 실제 3개 매장 keywordList 원문 대조 성공
- 실제 DB 적재 및 rollback-test 성공
- 동일 결과 재확인 시 키워드 결과가 중복 저장되지 않음
- 월별 기본 정책과 강제 갱신 동작 검증
- 실행 절차와 장애 대응 runbook 제공
