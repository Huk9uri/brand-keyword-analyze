# 브라우저 세션 재시작 최소화 구현 계획

> **에이전트 작업자용:** 필수 하위 스킬은 `superpowers:executing-plans`이며, 아래 체크박스를 작업 단위로 실행한다.

**목표:** 매장별 순위 수집 큐가 고정 배치 경계에서 불필요하게 분할되지 않도록 하고, 브라우저 수명과 수집 시간을 영수증으로 측정한다.

**아키텍처:** 공용 배치 수집기의 기본 고정 크기 동작은 유지하면서 선택형 `group_key` 정책을 추가한다. 메뉴 키워드 파이프라인만 Place ID 기반 그룹 정책을 사용하고, collector에는 DB 관측 시각과 독립적인 단조 시계 및 수명 계측을 주입해 배치 영수증에서 합산한다.

**기술 스택:** Python 3, pytest, dataclass, JSON 영수증

**명세:** `docs/HANDOFF-browser-session-reuse-20260916.md`

## 전역 제약

- 검색 요청 간격은 15초, 재시도 대기는 60/120초를 유지한다.
- 병렬 브라우저, 요청 빈도 증가, 자동화 및 메일 발송은 추가하지 않는다.
- 보안차단·저장 실패 시 중단하고 성공·예외·중단 경로에서 세션을 정리한다.
- 공용 수집기의 기존 고정 배치 기본 동작과 기존 영수증 필드 의미를 유지한다.
- 설계·구현·운영 문서는 한국어로 작성한다.

---

### 작업 1: 매장 경계 배치 정책

**파일:**
- 수정: `scripts/brand_keyword_research/batch_collection.py`
- 수정: `scripts/menu_keyword_pipeline/repository.py`
- 테스트: `tests/test_brand_research_batches.py`

**인터페이스:**
- 입력: `collect_in_batches(..., batch_size=100, *, collect_fn=None, group_key=None)`
- 출력: 기존 영수증에 `boundary_splits`를 추가하며, `group_key`가 없으면 기존 슬라이싱 결과를 그대로 유지한다.

- [ ] 같은 Place ID의 연속 작업 34건씩 두 그룹이 상한 50에서 `[34, 34]`로 계획되는 실패 테스트를 작성한다.
- [ ] 한 그룹이 상한을 넘으면 `[50, 나머지]`로만 분할되고 누락·중복이 없는 실패 테스트를 작성한다.
- [ ] 기존 고정 배치 테스트와 새 테스트를 실행해 새 인자 부재로 실패하는지 확인한다.
- [ ] 연속 그룹을 상한 안에서 포장하는 순수 배치 계획 함수를 최소 구현한다.
- [ ] 메뉴 파이프라인의 `Adapter.collect_rank`에서 `target_place_id` 그룹 키를 전달한다.
- [ ] 관련 테스트를 다시 실행해 기존 기본 동작과 새 정책이 모두 통과하는지 확인한다.

### 작업 2: collector 단조 시계 계측

**파일:**
- 수정: `scripts/keyword_discovery_rank/collector.py`
- 수정: `scripts/keyword_evaluation/collection.py`
- 테스트: `tests/test_keyword_discovery_collector.py`

**인터페이스:**
- 입력: `KeywordDiscoveryCollector(..., monotonic=time.monotonic)`
- 출력: `RunSummary`에 시도·재시도·브라우저 생성/종료/복구, 검색·대기·생성·종료·전체 경과 초를 담은 불변 측정값을 추가한다.

- [ ] 가짜 단조 시계와 세션으로 알려진 생성·검색·대기·종료 시간이 집계되는 실패 테스트를 작성한다.
- [ ] 손상 복구 재시작과 프로필 변경 재시작이 구분되는 실패 테스트를 작성한다.
- [ ] 실패 테스트가 누락된 계측 필드 때문에 실패하는지 확인한다.
- [ ] 기존 `clock`은 관측 시각 전용으로 유지하고 단조 시계 호출만으로 계측하는 최소 구현을 추가한다.
- [ ] `collect_ranks` 반환 영수증에 계측값을 직렬화한다.
- [ ] 성공·예외·보안차단·저장 실패·요청 간격 테스트를 실행한다.

### 작업 3: 배치 집계와 오프라인 비교

**파일:**
- 수정: `scripts/brand_keyword_research/batch_collection.py`
- 수정: `tests/test_brand_research_batches.py`
- 수정: `docs/2026-09-16-menu-keyword-pipeline.md`

**인터페이스:**
- 입력: 각 배치의 기존 수집 영수증과 선택형 `metrics`
- 출력: 최상위 `rank-receipt.json`의 합산 `metrics`, `boundary_splits`, 정책 이름

- [ ] 여러 배치의 횟수·시간 합계와 경계 분할 수가 정확한 실패 테스트를 작성한다.
- [ ] 계측값이 없는 기존 `collect_fn` 영수증도 정상 합산되는 실패 테스트를 작성한다.
- [ ] 집계 최소 구현 후 배치 테스트를 통과시킨다.
- [ ] 저장 입력 `outputs/hanchon-menu-pipeline-20260916-check/rank-plan.json`으로 구/신 정책의 배치 수와 동일 매장 경계 분할 수를 네트워크 없이 비교한다.
- [ ] 실제 비교 수치와 검색 시간의 포함 범위를 한국어 운영 문서에 기록한다.
- [ ] handoff에 기재된 전체 회귀 테스트를 실행하고 결과를 기록한다.
