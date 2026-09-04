# Keyword Candidate Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 최근 12개월 네이버 원문 리뷰와 메뉴·운영팀·검색광고 연관어를 결합해 매장별 및 브랜드 공통 키워드 후보와 추적 가능한 리뷰 근거를 생성·저장한다.

**Architecture:** 순위 수집기와 독립된 `keyword_candidate_discovery` 패키지로 입력, 품질 필터, 표현 추출, 후보 집계, 저장을 분리한다. 각 실행은 `run_id`로 식별하고 원문 리뷰를 복제하지 않은 채 원천 PK와 최소 근거 문맥만 저장한다.

**Tech Stack:** Python 3, 표준 라이브러리, pymssql, pytest, SQL Server

**Spec:** `docs/2026-09-04_keyword_candidate_discovery_design.md`

## Global Constraints

- 기본 분석 기간은 실행일 이전 최근 12개월이다.
- 시간 가중치는 0~3개월 1.0, 4~6개월 0.8, 7~12개월 0.5다.
- 원문 리뷰는 `naverDB.dbo.naver_review_blog`, `naverDB.dbo.naver_review_visitor`에서 읽는다.
- 규칙 기반 분석이 LLM 없이 독립 실행되어야 한다.
- 기존 순위 수집기 코드를 수정하거나 후보 로직과 결합하지 않는다.
- 거리와 좌표는 후보 발굴의 입력 및 평가 기준으로 사용하지 않는다.
- 커밋 메시지는 한국어로 작성하고 커밋 전에 사용자에게 알린다.

---

### Task 1: 후보 발굴 테이블 계약

**Files:**
- Create: `sql/keyword_candidate_discovery/01_create_tables.sql`
- Create: `sql/keyword_candidate_discovery/02_verify_tables.sql`
- Create: `tests/test_keyword_candidate_schema_sql.py`

**Interfaces:**
- Produces: `dbo.naver_keyword_discovery_review_term`, `dbo.naver_keyword_discovery_candidate`
- Produces: 두 테이블을 검증하는 읽기 전용 SQL

- [ ] **Step 1: 실패하는 SQL 계약 테스트 작성**
  - 두 테이블, `run_id`, 원천 식별자, 후보 상태, 근거 집계 컬럼, PK/FK/고유키/체크 제약과 필수 인덱스를 문자열 계약으로 검증한다.
- [ ] **Step 2: 테스트 실패 확인**
  - Run: `.venv/Scripts/python.exe -m pytest tests/test_keyword_candidate_schema_sql.py -q`
  - Expected: SQL 파일 부재로 FAIL.
- [ ] **Step 3: 멱등 DDL과 검증 SQL 구현**
  - 리뷰 근거는 `(run_id, source_type, source_review_id, normalized_keyword)`를 중복 방지 키로 사용한다.
  - 후보는 `(run_id, brand_code, candidate_scope, place_id_key, normalized_keyword)`를 중복 방지 키로 사용한다.
  - `candidate_status`는 `READY`, `INSUFFICIENT_EVIDENCE`, `REVIEW_REQUIRED`, `EXCLUDED`만 허용한다.
- [ ] **Step 4: SQL 계약 테스트 통과 확인**
  - Run: `.venv/Scripts/python.exe -m pytest tests/test_keyword_candidate_schema_sql.py -q`
  - Expected: PASS.

### Task 2: 원문 리뷰 입력과 품질 필터

**Files:**
- Create: `scripts/keyword_candidate_discovery/__init__.py`
- Create: `scripts/keyword_candidate_discovery/models.py`
- Create: `scripts/keyword_candidate_discovery/review_source.py`
- Create: `tests/test_keyword_candidate_review_source.py`

**Interfaces:**
- Produces: `RawReview`, `ReviewSourceType`, `AnalysisWindow`
- Produces: `ReviewRepository.iter_reviews(brand_code, as_of, months=12)`
- Produces: `prepare_reviews(rows, window) -> tuple[RawReview, ...]`

- [ ] **Step 1: 필터·정규화·중복 제거 실패 테스트 작성**
  - 빈 본문, 비정상 날짜, 기간 밖 리뷰, `place_id` 없는 리뷰를 제외한다.
  - `01/1`, `02/2` 브랜드 코드를 동일 값으로 정규화한다.
  - `source_type + place_id + date + normalized_context` 중복은 하나만 남긴다.
- [ ] **Step 2: 테스트 실패 확인**
  - Run: `.venv/Scripts/python.exe -m pytest tests/test_keyword_candidate_review_source.py -q`
  - Expected: 모듈 부재로 FAIL.
- [ ] **Step 3: 공통 모델, SQL 조회 및 순수 품질 필터 구현**
  - SQL은 필요한 브랜드, 시작일, 종료일만 매개변수로 조회한다.
  - 방문자 `keyword`와 블로그 `title`은 보조 텍스트로 보존한다.
- [ ] **Step 4: 입력 계층 테스트 통과 확인**
  - Run: `.venv/Scripts/python.exe -m pytest tests/test_keyword_candidate_review_source.py -q`
  - Expected: PASS.

### Task 3: 규칙 기반 표현 추출과 정규화

**Files:**
- Create: `scripts/keyword_candidate_discovery/lexicon.py`
- Create: `scripts/keyword_candidate_discovery/extractor.py`
- Create: `tests/test_keyword_candidate_extractor.py`

**Interfaces:**
- Consumes: `RawReview`
- Produces: `ExtractedTerm`
- Produces: `RuleBasedExtractor.extract(review) -> tuple[ExtractedTerm, ...]`

- [ ] **Step 1: 메뉴·상황·방문 목적·이용 특성·비방문 의도 테스트 작성**
  - `혼자 먹기 편하다 -> 혼밥`, `해장하기 좋다 -> 해장`, `밀키트 주문 -> 밀키트/비방문 의도`를 검증한다.
  - 한 리뷰 안의 같은 정규화 키워드는 한 번만 생성한다.
- [ ] **Step 2: 테스트 실패 확인**
  - Run: `.venv/Scripts/python.exe -m pytest tests/test_keyword_candidate_extractor.py -q`
  - Expected: 모듈 부재로 FAIL.
- [ ] **Step 3: 명시적 사전과 문맥 규칙 구현**
  - 단순 감정어는 독립 후보로 생성하지 않는다.
  - 사전에 없는 반복 표현을 후속 확장할 수 있도록 추출기 인터페이스를 고정한다.
- [ ] **Step 4: 추출기 테스트 통과 확인**
  - Run: `.venv/Scripts/python.exe -m pytest tests/test_keyword_candidate_extractor.py -q`
  - Expected: PASS.

### Task 4: 후보 집계와 외부 원천 결합

**Files:**
- Create: `scripts/keyword_candidate_discovery/aggregator.py`
- Create: `scripts/keyword_candidate_discovery/external_source.py`
- Create: `tests/test_keyword_candidate_aggregator.py`
- Create: `tests/test_keyword_candidate_external_source.py`

**Interfaces:**
- Consumes: `ExtractedTerm`, `ExternalKeyword`
- Produces: `KeywordCandidate`
- Produces: `aggregate_candidates(terms, external_keywords) -> tuple[KeywordCandidate, ...]`

- [ ] **Step 1: 임계치·가중치·원천 병합 실패 테스트 작성**
  - 매장 3리뷰 이상은 `STORE/READY`, 브랜드 3매장 이상은 `BRAND/READY`가 된다.
  - 기준 미달은 `INSUFFICIENT_EVIDENCE`, 비방문 의도는 `EXCLUDED`가 된다 한다.
  - 메뉴·운영팀·검색광고·리뷰가 같은 키워드를 제공하면 하나로 합치고 모든 원천 플래그를 유지한다.
- [ ] **Step 2: 테스트 실패 확인**
  - Run: `.venv/Scripts/python.exe -m pytest tests/test_keyword_candidate_aggregator.py tests/test_keyword_candidate_external_source.py -q`
  - Expected: 모듈 부재로 FAIL.
- [ ] **Step 3: 순수 집계 함수와 외부 원천 공통 형식 구현**
  - 시간 가중 합계와 서로 다른 리뷰·매장 수를 따로 계산한다.
  - 외부 원천만 있는 키워드는 평가 대상으로 보존하되 리뷰 근거 수는 0으로 기록한다.
- [ ] **Step 4: 집계 테스트 통과 확인**
  - Run: `.venv/Scripts/python.exe -m pytest tests/test_keyword_candidate_aggregator.py tests/test_keyword_candidate_external_source.py -q`
  - Expected: PASS.

### Task 5: 원자적 DB 저장과 통합 실행

**Files:**
- Create: `scripts/keyword_candidate_discovery/repository.py`
- Create: `scripts/keyword_candidate_discovery/pipeline.py`
- Create: `scripts/keyword_candidate_discovery/cli.py`
- Create: `tests/test_keyword_candidate_repository.py`
- Create: `tests/test_keyword_candidate_pipeline.py`
- Create: `tests/test_keyword_candidate_cli.py`

**Interfaces:**
- Produces: `CandidateRepository.save_run(run_id, terms, candidates) -> SaveSummary`
- Produces: `run_discovery(...) -> DiscoverySummary`
- Produces: `python -m scripts.keyword_candidate_discovery.cli --brand-code ... --as-of YYYY-MM-DD [--dry-run]`

- [ ] **Step 1: 트랜잭션·파이프라인·CLI 실패 테스트 작성**
  - 근거와 후보를 한 트랜잭션으로 저장하고 일부 실패 시 전체 롤백한다.
  - `--dry-run`은 DB에 쓰지 않고 건수 요약만 반환한다.
  - 기본 실행은 LLM 없이 완료된다.
- [ ] **Step 2: 테스트 실패 확인**
  - Run: `.venv/Scripts/python.exe -m pytest tests/test_keyword_candidate_repository.py tests/test_keyword_candidate_pipeline.py tests/test_keyword_candidate_cli.py -q`
  - Expected: 모듈 부재로 FAIL.
- [ ] **Step 3: 저장소, 오케스트레이션 및 CLI 구현**
  - 자격정보는 기존 `KEYWORD_DISCOVERY_DB_*` 환경변수를 사용하고 로그에 출력하지 않는다.
  - 실행 요약에는 읽은 리뷰, 유효 리뷰, 중복 제거, 추출 근거, 후보 상태별 건수를 포함한다.
- [ ] **Step 4: 신규 모듈 테스트 통과 확인**
  - Run: `.venv/Scripts/python.exe -m pytest tests/test_keyword_candidate_*.py -q`
  - Expected: PASS.

### Task 6: 전체 회귀 검증과 운영 문서

**Files:**
- Create: `docs/keyword-candidate-discovery-runbook.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: Task 1~5의 CLI와 SQL
- Produces: DDL 실행, dry-run, 실제 적재, 검증 쿼리 절차

- [ ] **Step 1: 실행 문서와 안전 절차 작성**
  - DDL은 권한 계정이 실행하고 애플리케이션은 전용 계정으로 읽기·쓰기한다.
  - 최초 실행은 dry-run, 소량 실제 적재, 검증 SQL 순서로 안내한다.
- [ ] **Step 2: 전체 테스트 실행**
  - Run: `.venv/Scripts/python.exe -m pytest -q`
  - Expected: 기존 및 신규 테스트 전체 PASS.
- [ ] **Step 3: 변경 파일과 공백 오류 검사**
  - Run: `git diff --check`
  - Expected: 출력 없음.
- [ ] **Step 4: 사용자에게 한국어 커밋 메시지를 사전 고지**
  - 제안 메시지: `feat: 원문 리뷰 기반 키워드 후보 발굴 모듈 추가`
  - 사용자 확인 전에는 커밋하지 않는다.
