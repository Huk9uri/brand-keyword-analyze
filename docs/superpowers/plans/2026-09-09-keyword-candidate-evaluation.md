# 키워드 후보 평가 구현 계획

> 실행 담당자는 `superpowers:executing-plans`의 단계별 검증 방식을 따른다. 이 계획은 현재 작업에서 순차 실행한다.

**목표:** 고정한 입력으로 후보를 분류하고 검색량·평가 저장 계약과 사람 검토 출력을 구현한다.

**구조:** 원천 어댑터 → 입력 검증·동결 → 저비용 게이트·분위수 → 관측 지표 → 분류 → 출력·선택적 저장. 순수 계산은 네트워크와 DB에서 분리한다.

**기술:** Python 3.12, pytest, pymssql, SQL Server, 기존 검색광고·순위·keywordList 수집 모듈.

**설계:** `docs/superpowers/specs/2026-09-09-keyword-candidate-evaluation-input-contract.md`

## 공통 제약

- 현재 브랜치에서 작업한다. 기존 미추적 파일·업무보고서는 수정하지 않는다.
- 운영 DB DDL·수집·적재를 실행하지 않는다. 커밋·push하지 않는다.
- 좌표·거리·운영팀 키워드·SKYPOS 매출은 평가 입력에서 배제한다.
- 결측은 NULL과 품질 상태로 보존한다. 자동 5개 선정은 구현하지 않는다.

## 작업 1. 입력 및 검색량 계약

- [x] `tests/test_keyword_evaluation_contract.py`에 정규화, 숫자·구간, 충돌, 시각 테스트 작성 후 실패 확인.
- [x] `scripts/keyword_evaluation/contracts.py`, `volume.py` 구현.
- [x] `python -m pytest tests/test_keyword_evaluation_contract.py -q` 통과 확인.

입력은 원천 JSON 객체와 시간대 명시 ISO 시각이다. 출력은 검증된 사전과 원문을 보존한 검색량 관측이다. UUID·식별자는 경계에서 검증한다.

## 작업 2. 원천 선택 및 평가

- [x] `tests/test_keyword_evaluation_engine.py`에 정상 빈집·경쟁과 필수 결측 차단 사례 작성 후 실패 확인.
- [x] `sources.py`, `engine.py`에 최신 선택·게이트·비율·노출 계산 구현.
- [x] 광고 포함 깊이, 최신 실패, EMPTY/effective, 미확정 업종 테스트 통과 확인.

계산 API는 `evaluate_bundle(bundle: dict) -> dict`다. 동일 입력으로 같은 해시·결과를 만들며 생성시각·실행 ID는 저장 단계에서 주입한다.

## 작업 3. 파이프라인 및 검토 출력

- [x] 분위수 모집단, 예산 축소, 재현성·CSV 테스트 작성 후 실패 확인.
- [x] `pipeline.py`, `review.py` 구현. `evaluate_bundle`은 후보별 결과와 고정 모집단·수집 대상을 반환.
- [x] 합성 파일럿 입력으로 JSON·CSV 결과 검증. 예시는 합성임을 명시.

## 작업 4. DDL·저장·읽기 어댑터

- [x] `tests/test_keyword_evaluation_repository.py`에 읽기 전용 조회, 원자적 저장·rollback 테스트 작성 후 실패 확인.
- [x] `sql/keyword_evaluation/01_create_tables.sql`, `02_verify_tables.sql` 작성. 실행하지 않음.
- [x] `repository.py` 구현. 런타임 DDL 금지, 매개변수 SQL, 명시적 저장 API, 원천 FK·JSON 근거 보존.

## 작업 5. 실행 CLI 및 수집 연결

- [x] CLI 기본 모드에서 네트워크·DB 쓰기 없음, 좌표 해석 없음 테스트 작성 후 실패 확인.
- [x] `cli.py`, `collection.py` 구현. evaluate/export-source/collect-volume/collect-rank/collect-keywords/save를 분리.
- [x] 기존 수집기 초기 동작을 바꾸지 않고 새 평가용 경로만 연결.

## 작업 6. 검증·인수 문서

- [x] 신규 테스트 전체와 기존 키워드 관련 회귀 테스트 실행.
- [x] `docs/keyword-evaluation-runbook.md`에 실제 명령·승인 경계·알려진 제약 기록.
- [x] DB 통합 테스트와 실제 네이버 수집은 미실행임을 명시. 작업 파일 목록과 검증 결과 확인.

## 실행 결과

- 신규 Python 모듈 11개, 검색량·평가 DDL 및 검증 SQL, 원천 설정·합성 입력, 운영 안내서를 추가했다.
- 실패 테스트 확인 후 구현하여 신규 테스트와 기존 회귀 테스트를 실행했다. 최종 결과는 작업 응답에 보고한다.
- 합성 CLI 출력 5행, A~F 게이트, 자동 분류를 숨긴 검토 CSV를 확인했다.
- 운영 DB DDL·실제 수집·적재·커밋·push는 실행하지 않았다. DB 저장 테스트는 fake 연결의 원자성·rollback 검증이며 실제 SQL Server 통합 검증을 대신하지 않는다.
- 기존 미추적 분석 SQL 테스트 5개는 업무 범위 밖으로 회귀 실행에서 제외했다.
