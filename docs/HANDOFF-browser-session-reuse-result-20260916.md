# HANDOFF — 매장별 순위 수집 브라우저 재시작 최소화 구현 결과

## 문서 목적

이 문서는 `docs/HANDOFF-browser-session-reuse-20260916.md`를 기준으로 진행한 구현 결과와 검증 상태를 다음 작업자에게 인계한다.

작업 브랜치는 `codex/browser-session-reuse`다. 기존 작업공간에 있던 미커밋 변경을 보존하기 위해 별도 worktree가 아니라 현재 작업공간에서 브랜치를 분기했다. 이 문서 작성 시점에는 변경 사항을 커밋하지 않았다.

## 구현 결과 요약

다음 두 가지를 구현했다.

1. 매장 경계에 맞춘 선택형 배치 정책
2. 단조 시계 기반 브라우저·검색·대기시간 계측과 배치별 집계

검색 요청 간격은 15초를 유지했다. 재시도 대기는 첫 재시도 60초, 다음 재시도 120초를 유지했다. 요청 병렬화, 요청 간격 단축, 자동화 및 메일 발송은 추가하지 않았다.

## 매장 경계 배치 정책

### 변경 내용

`scripts/brand_keyword_research/batch_collection.py`의 공용 `collect_in_batches`에 선택형 `group_key` 인자를 추가했다.

- `group_key`가 없으면 기존 고정 크기 슬라이싱을 그대로 사용한다.
- `group_key`가 있으면 입력 순서를 유지하면서 연속된 같은 그룹을 하나의 작업 묶음으로 취급한다.
- 다음 그룹을 넣을 때 배치 상한을 넘으면 현재 배치를 마감하고 다음 배치에서 새 그룹을 시작한다.
- 한 그룹 자체가 상한을 넘는 경우에만 상한 크기로 분할한다.
- 불가피하게 그룹을 분할한 횟수는 최상위 영수증의 `boundary_splits`에 기록한다.

`scripts/menu_keyword_pipeline/repository.py::Adapter.collect_rank`에서만 `target_place_id`를 그룹 키로 전달한다. 따라서 기존 공용 수집기 호출자의 기본 고정 배치 동작은 바뀌지 않는다.

### 검증 사례

- A매장 34건, B매장 34건, 상한 50: `[34, 34]`
- 한 매장 67건, 상한 50: `[50, 17]`, `boundary_splits=1`
- 작업 누락과 중복이 없음을 테스트했다.

## 단조 시계 기반 계측

### 목적

전체 실행시간 감소와 브라우저 재시작 감소의 직접 효과를 구분하기 위해 계측을 추가했다. DB 관측 시각과 경과시간 측정은 서로 다른 시계를 사용한다.

- 기존 `clock`: `collected_at` 등 DB 관측 시각
- 신규 `monotonic`: 생성·종료·검색·대기·전체 경과시간

단조 시계는 운영체제 시간 보정이나 시각 변경 때문에 경과시간이 역행하는 문제를 피한다.

### 수집되는 항목

`KeywordDiscoveryCollector.run()`의 `RunSummary.metrics`에 다음 필드를 기록한다.

| 필드 | 의미 |
|---|---|
| `browser_create_count` | 브라우저 세션 생성 성공 횟수 |
| `browser_close_count` | 브라우저 세션 종료 시도 횟수 |
| `search_attempt_count` | 실제 브라우저 검색 호출 횟수 |
| `retry_count` | 오류 뒤 실제로 다음 시도를 수행한 횟수 |
| `damaged_restart_count` | 세션 손상 때문에 종료 후 재생성한 횟수 |
| `profile_change_restart_count` | 좌표·기기 프로필 변경 때문에 교체한 횟수 |
| `browser_create_seconds` | 브라우저 생성 경과시간 합계 |
| `browser_close_seconds` | 브라우저 종료 경과시간 합계 |
| `search_seconds` | `session.search()` 호출 경과시간 합계 |
| `explicit_wait_seconds` | 15초 및 60/120초 명시적 대기의 실제 경과시간 합계 |
| `total_elapsed_seconds` | collector 실행 전체 경과시간 |

`search_seconds`는 브라우저의 `session.search()` 호출만 측정한다. 이후 파싱과 DB 저장 시간은 포함하지 않는다. `total_elapsed_seconds`에는 파싱·검증·증빙 저장·DB 저장·세션 정리를 포함한 전체 실행시간이 들어가므로 세부 항목의 합과 전체 시간이 다를 수 있다.

### 영수증 저장과 집계

`scripts/keyword_evaluation/collection.py::collect_ranks`가 `RunSummary.metrics`를 배치 영수증의 `metrics` 객체로 직렬화한다.

`scripts/brand_keyword_research/batch_collection.py::collect_in_batches`는 각 배치의 계측값을 최상위 `rank-receipt.json`에 합산한다. 계측값을 반환하지 않는 기존 테스트 대체물과 호출자도 0으로 집계되도록 호환성을 유지했다.

## 시간 단축 해석 방법

17개 키워드 전체 조사가 과거 약 10시간 걸렸다는 운영 정보가 있다. 매장 수가 약 99개라면 전체 검색은 약 1,683건이다.

- 15초 의무 대기만 단순 계산으로 약 7시간이다.
- 여기에 페이지 검색·로딩, 파싱·저장, 재시도, 브라우저 생성·종료 시간이 추가된다.
- 이번 변경은 15초 대기와 검색 요청 수를 줄이지 않는다.
- 따라서 이번 변경의 직접 효과는 주로 고정 배치 경계에서 사라진 브라우저 생성·종료 횟수와 시간이다.

향후 실제 수집 보고에서는 다음 값을 분리한다.

1. 전체 실행시간
2. 명시적 대기시간
3. 검색 호출시간
4. 브라우저 생성·종료시간
5. 세션 손상 및 프로필 변경에 따른 필수 재시작
6. 배치 경계 제거로 감소한 재시작 횟수와 직접 절감시간

기존 실행에 같은 계측값이 없으면 정확한 신·구 전체시간 비교는 할 수 없다. 이 경우 저장된 입력으로 구·신 정책의 배치 경계와 예상 재시작 횟수를 비교하고, 신규 실행부터 실측 기준선을 축적한다.

## 테스트 결과

handoff 원문에 기재된 회귀 테스트 명령을 실행했다.

```powershell
.venv/Scripts/python.exe -m pytest tests/test_brand_research_batches.py tests/test_keyword_discovery_collector.py tests/test_keyword_discovery_browser.py tests/test_keyword_discovery_uc.py tests/test_keyword_evaluation_shared_rank.py tests/test_menu_keyword_pipeline.py tests/test_menu_keyword_workflow.py tests/test_menu_keyword_cli.py -q
```

결과:

```text
129 passed in 6.21s
```

pytest 종료 후 작업공간 밖 `AppData/Local/Temp/pytest-of-user1/pytest-current` 정리 과정에서 `PermissionError` 경고가 출력됐다. 테스트 프로세스 종료 코드는 0이었고 테스트 실패는 없었다. 이 경고를 테스트 성공으로 숨기지 않으며, Windows 임시 디렉터리 권한 또는 잠금 문제로 별도 기록한다.

## 변경 파일

- `scripts/brand_keyword_research/batch_collection.py`
- `scripts/menu_keyword_pipeline/repository.py`
- `scripts/keyword_discovery_rank/collector.py`
- `scripts/keyword_evaluation/collection.py`
- `tests/test_brand_research_batches.py`
- `tests/test_keyword_discovery_collector.py`
- `docs/superpowers/plans/2026-09-16-browser-session-reuse.md`
- `docs/HANDOFF-browser-session-reuse-result-20260916.md`

기존 작업공간에는 위 목록 외의 미커밋 변경과 미추적 파일이 있다. 다음 작업자는 `git status --short`를 먼저 확인하고 기존 변경을 되돌리거나 덮어쓰지 않는다.

## 아직 수행하지 않은 작업

- 실제 네이버 검색 수집은 실행하지 않았다.
- 과거 10시간 실행에는 신규 계측이 없으므로 현재 단계에서 정확한 전체 단축시간을 산출하지 않았다.
- 저장된 `rank-plan.json`을 이용한 구·신 정책 오프라인 비교 수치는 아직 기록하지 않았다.
- 변경 사항을 커밋하거나 원격 저장소에 푸시하지 않았다.

## 다음 권장 작업

1. `outputs/hanchon-menu-pipeline-20260916-check/rank-plan.json`을 사용해 네트워크 없이 기존 고정 배치와 매장 경계 배치의 배치 수·동일 매장 분할 수를 비교한다.
2. 실제 미완료·만료 대상 중 작은 범위를 정해 15초 간격으로 한 번 수집한다.
3. `rank-receipt.json`의 `metrics`를 검토해 전체시간과 직접 절감시간을 분리해 보고한다.
4. 보안차단, 저장 실패, 프로필 정리 실패가 발생하면 즉시 중단하고 이후 검색이 없었는지 확인한다.
5. 검증 결과가 만족스러우면 사용자 소유 변경과 이번 변경을 구분해 스테이징한 뒤 커밋한다.

전체 34개 키워드 전량 수집, 같은 검색어 반복 벤치마크, 요청 간격 단축, 병렬 브라우저 실행은 사용자 승인 없이 시작하지 않는다.
