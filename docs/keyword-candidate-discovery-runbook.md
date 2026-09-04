# 키워드 후보 발굴 실행 가이드

## 목적

네이버 원문 리뷰와 메뉴·운영팀·검색광고 연관어를 결합해 검색량 및 순위 평가 전의
매장별 키워드 후보를 생성한다. 좌표와 거리는 사용하지 않는다.

## 사전 준비

프로젝트 루트 `.env`에 다음 값이 필요하다.

- `DB_SERVER`
- `DB_PORT`
- `KEYWORD_DISCOVERY_DB_DATABASE=naverDB`
- `KEYWORD_DISCOVERY_DB_USER`
- `KEYWORD_DISCOVERY_DB_PASSWORD`
- `DB_ENCRYPT`

검색광고 연관어 확장 시에는 다음 값도 필요하다.

- `NAVER_SEARCHAD_CUSTOMER_ID`
- `NAVER_SEARCHAD_API_KEY`
- `NAVER_SEARCHAD_SECRET_KEY`

실제 값은 출력하거나 Git에 커밋하지 않는다.

## 신규 테이블 생성

권한 계정으로 다음 파일을 순서대로 실행한다.

1. `sql/keyword_candidate_discovery/01_create_tables.sql`
2. `sql/keyword_candidate_discovery/02_verify_tables.sql`

검증 결과는 테이블 2개, 컬럼 34개, 제약조건 14개 이상, 인덱스 6개 이상이어야 한다.

## Dry-run

프로젝트 루트의 `.env`를 명시하고 실행한다. 기본값이 dry-run이므로 DB에 후보를
기록하지 않는다.

```powershell
.\.venv\Scripts\python.exe -m scripts.keyword_candidate_discovery.cli `
  --brand-code 01 `
  --as-of 2026-09-04 `
  --env-file C:\workspace\brand_analyze\.env
```

실행 결과 JSON에서 다음 값을 확인한다.

- `source_review_count`: 기간 조건으로 읽은 원천 행 수
- `valid_review_count`: 품질 필터와 중복 제거 후 리뷰 수
- `extracted_term_count`: 리뷰에서 추출된 근거 수
- `candidate_count`: 매장별·브랜드 공통 후보 수
- `status_counts`: `READY`, `INSUFFICIENT_EVIDENCE`, `REVIEW_REQUIRED`, `EXCLUDED`별 수
- `dry_run`: `true`

## 메뉴·운영팀 키워드 결합

매장 메뉴와 운영팀 키워드는 `--place-id` 대상 매장 후보로 들어간다. 브랜드 대표
메뉴는 브랜드 공통 후보로 들어간다.

```powershell
.\.venv\Scripts\python.exe -m scripts.keyword_candidate_discovery.cli `
  --brand-code 01 `
  --place-id 31076466 `
  --as-of 2026-09-04 `
  --menu 설렁탕 `
  --brand-menu 수육 `
  --operation-keyword 혼밥 `
  --env-file C:\workspace\brand_analyze\.env
```

## 검색광고 연관어 확장

메뉴·브랜드 메뉴·운영팀 키워드를 최대 5개의 힌트 키워드로 사용한다.

```powershell
.\.venv\Scripts\python.exe -m scripts.keyword_candidate_discovery.cli `
  --brand-code 01 `
  --place-id 31076466 `
  --as-of 2026-09-04 `
  --menu 설렁탕 `
  --operation-keyword 혼밥 `
  --expand-searchad `
  --env-file C:\workspace\brand_analyze\.env
```

## 실제 적재

DDL 검증과 dry-run 결과 검토 후에만 `--write`를 추가한다.

```powershell
.\.venv\Scripts\python.exe -m scripts.keyword_candidate_discovery.cli `
  --brand-code 01 `
  --place-id 31076466 `
  --as-of 2026-09-04 `
  --menu 설렁탕 `
  --operation-keyword 혼밥 `
  --env-file C:\workspace\brand_analyze\.env `
  --write
```

`run_id` 단위로 후보와 리뷰 근거가 한 트랜잭션에 저장된다. 어느 한쪽 적재가
실패하면 해당 실행 전체가 롤백된다.

## 판정 기준

- 같은 매장의 서로 다른 유효 리뷰 3건 이상: 매장 후보 `READY`
- 서로 다른 자사 매장 3곳 이상: 브랜드 공통 후보 `READY`
- 기준 미달: `INSUFFICIENT_EVIDENCE`
- 불확실한 분류: `REVIEW_REQUIRED`
- 밀키트·택배·레시피 등 비방문 의도: `EXCLUDED`

외부 원천에서 명시적으로 제공된 후보는 검색량·순위 평가 대상으로 넘기기 위해
`READY`로 기록한다. `READY`는 최종 대표키워드 선정이 아니라 후속 평가 준비 완료를
의미한다.
