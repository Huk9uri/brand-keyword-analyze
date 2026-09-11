# 키워드 후보 평가 모듈 작업 인계

작성일: 2026-09-09, Asia/Seoul  
프로젝트: `C:\workspace\brand_analyze`  
브랜치: `feat/keyword-candidate-evaluation`  
HEAD: `198d73b` — 이후 변경은 미커밋 상태

## 1. 현재 상태

입력 계약, 평가 엔진, 읽기 전용 입력 어댑터, 검색량 저장, 수집 연결, 평가 저장 및 사람 검토 출력 코드를 구현했다. 운영자가 신규 DDL을 실행했고, 이 대화에서 스키마를 읽기 전용으로 검증했다. 실제 검색량은 공식 메뉴 5개만 확보했다.

수원파장점을 정상 운영이 확인된 신림역점으로 교체하여 5개 매장의 후보 3,850개와 리뷰 근거 760행을 동결했다. 저장된 평가 결과는 **3,850개 모두 REVIEW_REQUIRED(검토필요)**다. 경쟁점 판정 규칙과 필수 관측값이 부족한 상태로, 빈집·경쟁 판정이 완료된 것이 아니다.

순위 수집의 위치 대기 오류와 광고 포함 카드 수 기준을 수정했다.

브라우저를 UC 및 임시 독립 프로필 방식으로 수정했다. 수정된 브라우저로 재수집 후 안정성 검토를 진행해야 한다.

## 2. 사용자 요구와 승인 경계

- 목적: 검색수요와 자사 노출 가능성을 근거로 매장별 후보를 빈집·경쟁·제외·검토필요로 분류한다.
- 최종 대표키워드 5개 자동 선정은 후속 과제다. 먼저 사람 판정과 비교하여 임계치를 교정한다.
- 초기 조사만 요청했으나 이후 설계 문서 작성, 구현, DDL 이후 진행, 수집 및 필요한 적재를 순차적으로 승인했다. DDL은 사용자가 실행했다고 알려왔다.
- 좌표·거리, 운영팀 키워드, SKYPOS 매출은 평가에서 제외한다. 일부 매장에만 존재하는 불완전한 데이터로 비교 점수를 만들지 않는다.
- 결측·실패는 0점이나 미노출로 간주하지 않는다. PARTIAL·실패·STALE·판정 불확실은 품질 상태와 근거를 남긴다.
- LLM은 의도·동의어·설명 보조에만 사용한다. 검색량·순위·비율은 관측값으로 계산한다.
- 연관어 755개 전체의 고비용 순위 수집은 금지하고 저비용 평가로 축소한다.
- 설계·구현 문서는 한국어로 작성한다. 기존 미추적 파일·업무보고서를 수정하거나 일괄 정리하지 않는다.
- 커밋은 정확한 한국어 메시지와 대상 파일을 먼저 제시하여 승인을 받아야 한다. 커밋·push 승인은 아직 없다.
- 이번 인계 작업에서는 문서만 새로 만들며 DB 변경·재수집을 하지 않는다.

## 3. 파일럿 매장 및 후보 실행

| 매장       | Place ID | ERP 코드 | 순위 target_store_id | 후보 수 | candidate run_id                     |
| ---------- | -------- | -------- | -------------------- | ------: | ------------------------------------ |
| 부천본점   | 12012595 | 000042   | EVAL-12012595        |     773 | 72ed626c-072f-4003-8f3e-35b6d9fb8bcb |
| 강동점     | 11627699 | 000038   | EVAL-11627699        |     768 | d8e32c55-a8a0-4bac-9f5f-a3750853b5e1 |
| 천안쌍용점 | 17391216 | 000105   | EVAL-17391216        |     773 | 95ae9fb9-3d82-4621-920a-415a13477def |
| 선릉역점   | 31076466 | 000117   | IYN-000117           |     769 | 01d4745e-b193-49d1-a902-79131faa9c51 |
| 신림역점   | 31103591 | 000019   | IYN-000019           |     767 | a13fc6d3-c8ae-4428-bf6c-c238063f831b |

모두 입력 동결 시점에 운영 대상 뷰의 `CONSISTENT` 및 `operation_status=VERIFIED`를 확인했다. 후보의 brand_code는 `1`, 운영 뷰는 `001`이다. ERP 코드와 순위 target_store_id를 이름만 보고 자동 조합하지 않는다.

수원파장점(34883104)은 운영 상태 충돌로 대상에서 제외했으며 과거 후보·결과는 삭제하지 않았다. 신림역점은 기존 부천본점 실행의 연관어 755개를 동일하게 재사용하고 공식 메뉴 5개와 해당 매장 최근 12개월 리뷰 20건을 적용했다. 리뷰 추출 근거는 24행이며 후보는 767개다. 메뉴·연관어·리뷰는 중복 결합하므로 합산 개수가 후보 수와 같지 않다.

공식 메뉴: 설렁탕, 왕갈비탕, 얼큰설렁탕, 도가니탕, 소머리곰탕. 리뷰 기준일 2026-09-09, 조회 기간 2025-09-09~2026-09-09.

자사 목록에서 Place ID가 미확인인 아래 4곳은 사용자가 이번 범위에서 신경 쓰지 말라고 명시했다.

- 000272 가평휴게소 상행점
- 000273 가평휴게소 하행점
- 000517 매송휴게소점
- 000585 곤지암리조트점

동결된 자사 식별 목록은 확인된 136곳과 기존 파일럿 목록의 합집합 137개 Place ID다. 기존 수원파장점 ID는 자사 식별 목록에 남아 있지만 평가 대상은 아니다. `own_registry_complete=true`는 위 4곳을 제외한 승인 범위에 한정된다.

## 4. 코드와 문서 위치

| 위치                                                                             | 역할                                                   |
| -------------------------------------------------------------------------------- | ------------------------------------------------------ |
| scripts/keyword_evaluation/contracts.py                                          | 정규화, 시간대, 계산 버전, 임계치 초깃값, 수집 프로필  |
| scripts/keyword_evaluation/volume.py                                             | 공급자 검색량 원문·정확값·저검색량·결측·오류 해석      |
| scripts/keyword_evaluation/sources.py                                            | 기준 시점 이하 원천 선택, 최신 시도/성공, TTL          |
| scripts/keyword_evaluation/source_export.py                                      | 읽기 전용 DB 입력 동결 및 매장 식별 검증               |
| scripts/keyword_evaluation/engine.py                                             | 의도·적합성·수요·경쟁·keywordList·현재 노출 및 분류    |
| scripts/keyword_evaluation/pipeline.py                                           | 입력 검사, 재현 가능한 평가, 수집 후보 축소            |
| scripts/keyword_evaluation/collection.py                                         | 검색량·순위·keywordList 기존 수집기 연결               |
| scripts/keyword_evaluation/repository.py                                         | 원천 조회와 검색량·평가·근거·사람 검토 저장            |
| scripts/keyword_evaluation/review.py                                             | 블라인드 사람 검토 CSV 및 자동/사람 비교               |
| scripts/keyword_evaluation/cli.py                                                | 실행 명령, 네트워크·쓰기 명시 옵션, 출력 보호          |
| scripts/keyword_discovery_rank/browser.py                                        | 브라우저 생성·검색·확장·완료 감지; 사용자 UC 수정 포함 |
| scripts/keyword_discovery_rank/validation.py                                     | 자연순위 기준 깊이 및 카드 불변 조건 검증              |
| sql/keyword_evaluation/01_create_tables.sql                                      | 신규 테이블 DDL; 운영자가 실행한 파일                  |
| sql/keyword_evaluation/02_verify_tables.sql                                      | 스키마 검증                                            |
| docs/superpowers/specs/2026-09-09-keyword-candidate-evaluation-input-contract.md | 상세 입력 계약                                         |
| docs/superpowers/plans/2026-09-09-keyword-candidate-evaluation.md                | 초기 구현 계획                                         |
| docs/keyword-evaluation-runbook.md                                               | 명령 사용법                                            |
| docs/2026-09-09-keyword-rank-organic20-diagnosis.md                              | 순위 실패 조사 및 실제 검증                            |
| docs/2026-09-09-keyword-rank-uc.md                                               | 사용자 변경 후 추가로 발견된 UC 설명 문서              |

초기 runbook·계획의 ‘DB/API 실행 안 함’, 수원파장점 관련 문장은 작성 시점의 기록이다. 최신 실행 상태와 대상은 이 인계 문서 및 실행 영수증을 우선 확인한다. 기존 문서를 일괄 덮어쓰지 않았다.

## 5. DB 및 입력 연결 핵심

기존 원천은 `naverDB.dbo`의 아래 테이블이다.

- `naver_keyword_discovery_candidate`: candidate_id, run_id, brand_code, candidate_scope, place_id, normalized_keyword. 후보 실행·STORE·Place ID를 함께 고정한다.
- `naver_keyword_discovery_review_term`: candidate_id와 리뷰 원천 식별자로 연결한다. 원천 수집 상태와 인용 근거를 확인한다. 어댑터는 원문을 읽었다는 이유만으로 verified_support를 true로 만들지 않는다.
- `naver_keyword_discovery_snapshot` / `naver_keyword_discovery_result`: run_id→snapshot_id→카드 원본 순서·자연순위. target_store_id, 정규화 검색어, MOBILE, 수집 프로필과 기준 시점을 함께 검사한다.
- `naver_place_keyword_snapshot` 및 결과 테이블: Place ID의 최신 시도와 최신 성공/EMPTY를 구분하고 effective_snapshot_id로 실제 단어 목록을 읽는다. 실패 후 과거 성공을 재사용하면 STALE로 구분한다.
- `vw_naver_store_hours_targets`: 운영 대상과 ERP/Place ID 매핑 확인.

새 테이블은 `naver_keyword_search_volume_snapshot`, `naver_keyword_evaluation_run`, `naver_keyword_evaluation_result`, `naver_keyword_evaluation_evidence`, `naver_keyword_evaluation_review`다. 후보 원본에 평가 결과를 혼합하지 않는다. 운영자가 생성한 직후 컬럼·null·FK/CHECK를 대조했다. 실제 평가/사람 검토 저장의 운영 DB 완료 영수증은 아직 없다.

정규화는 평가 키의 NFKC·공백 축약·casefold와 검색광고 조회 키의 공백 제거를 구분한다. 유사한 문자열이나 run_id 이름만으로 서로 다른 원천을 결합하지 않는다.

입력 기준 시점 이하의 원천만 사용한다. 후보 시각은 +09:00, 이번 평가 경유 신규 순위/keywordList 수집은 기존 datetime2에 UTC 시각을 저장한다. rank_runs의 time_offset 및 keyword_run_time_offsets를 실제 실행별로 기록한다. 과거 시간대나 수집 프로필을 새 실행의 값으로 재명명하지 않는다.

## 6. 실제 검색량 확보

검색량 실행 ID: `3789c29f-54d0-4bc8-8c85-78f5fdfdfd8b`. 스냅샷 ID 1~5. 모두 EXACT.

| 메뉴       |    PC | 모바일 |   합계 |
| ---------- | ----: | -----: | -----: |
| 설렁탕     | 3,750 | 49,100 | 52,850 |
| 왕갈비탕   |   400 |  4,680 |  5,080 |
| 얼큰설렁탕 |    20 |    100 |    120 |
| 도가니탕   | 2,800 | 26,400 | 29,200 |
| 소머리곰탕 |   300 |  2,880 |  3,180 |

수집 시각: 2026-09-09 04:03:11.318 UTC. 공급자 월간검색수(최근 한달)이며 정확한 시작·종료 경계는 미제공이다. 임의의 정확한 최근 30일 구간으로 바꾸지 않는다. `period_type=PROVIDER_MONTHLY`와 검증된 공급자 기간 설명을 보존한다. 근거: https://ads.naver.com/help/faq/440.

산출물: `outputs/keyword-evaluation-menu-volume-20260909T040310840723Z/`의 observations.json, receipt.json, verification.json. 나머지 후보의 검색량까지 확보된 것은 아니다.

## 7. 현재 사용할 로컬 산출물

기준 디렉터리: `outputs/keyword-evaluation-pilot-20260909T041016Z/`.

| 경로                                           | 의미                                                 |
| ---------------------------------------------- | ---------------------------------------------------- |
| source-config-replaced.json                    | 신림역점 교체 후 최신 대상 설정                      |
| replacement-candidate-receipt.json             | 신림역점 후보 적재 영수증                            |
| input-replaced.json                            | 5개 매장 입력 동결: 후보 3,850개, 리뷰 근거 760행    |
| evaluation-replaced.json/evaluation.json       | 오프라인 평가 결과: 모두 REVIEW_REQUIRED             |
| evaluation-replaced.json/collection_queue.json | 현재 매장별 수집 큐 25건                             |
| evaluation-replaced.json/review.csv            | 사람 검토용 블라인드 CSV                             |
| rank-receipt.json                              | 교체 전 4개 정상 매장 큐에서 시작한 실패 실행 영수증 |

주의: `evaluation-replaced.json`은 확장자와 달리 **디렉터리**다. `evaluate --output`은 디렉터리를 만들고 그 안에 evaluation.json, collection_queue.json, review.csv를 생성한다. `--reviews`는 evaluate 출력 경로 지정용이 아니며 비교 입력용이다. 이전 안내의 별도 review-replaced.csv가 아니라 위 실제 파일을 사용한다.

source-config.json, source-config-own-scope.json, input-low-cost.json, evaluation-low-cost.json은 교체 전 이력이다. 최신 대상으로 착각하지 않는다. 동결 파일에는 과거 계산 당시 프로필/규칙이 포함되므로 현재 코드로 재평가할 때 반드시 새 출력 경로를 사용한다.

## 8. 순위 수집 결과 및 보완

### 최초 DB 저장 실행

- run_id: `f722e19d-cfbc-487b-a2b5-a9f4884b03b3`.
- 강동점 메뉴 5건 처리 후 동일 실패 5회로 자동 중단.
- 스냅샷 164~168: 모두 LOAD_TIMEOUT, 순위 결과 행 0개, 저장 실패 0개.
- 마지막 수집 13:18:39 KST, 영수증 생성 13:18:42 KST.
- 최초 큐는 4개 매장×5개 메뉴=20건이었다. 교체 후 새 큐는 25건이며 추가 20건은 시도되지 않았다.
- 실패 증거는 기준 디렉터리의 evaluation-artifacts-rank-receipt 아래 run_id/task_key별 HTML·스크린샷에 있다.

### 일반 Selenium에서 검증한 보완

- 좌표 없는 세션에서 ‘위치 정보 없음’을 대기 조건으로 사용하지 않는다.
- 평가 수집은 organic_limit=True, 프로필 `MOBILE_NO_LOCATION_ORGANIC20_V2`를 사용한다.
- 광고를 목표 개수에서 제외하고 자연순위 20번째까지의 카드 접두부를 보존한다.
- 20개 미만 비종결 결과는 제한 시간 후 PARTIAL. 버튼 소멸만으로 종결 판정하지 않는다.
- 자사 매장이 일찍 발견돼도 짧은 비종결 결과는 재수집한다.
- 일반 순위 CLI의 기본 카드 개수 기준과 평가용 자연순위 기준을 구분한다.

실제 통합검색 진단: `outputs/keyword-rank-organic20-smoke-3c0c4d47-31a4-46c1-b761-2aa12230c321/` — 자연순위 10개, 광고 6개, PARTIAL, DB 미적재.

별도 목록 진단: `outputs/keyword-place-list-diagnostic-80a83714-a1ba-493e-82b2-64327448fb62/` — 보안 확인 화면. 통합검색과 별도 목록의 순위를 이어 붙이지 않았다.

### 사용자 UC 변경 이후

현재 browser.py의 기본 드라이버는 일반 webdriver.Chrome에서 UC 생성 함수로 변경되어 있다. 세션마다 TemporaryDirectory로 독립 프로필을 만들며 종료 시 삭제한다. 영속 로그인 프로필은 아니다. 기존 Selenium 탐색·DOM 처리 로직은 유지한다.

requirements-keyword-discovery.txt, tests/test_keyword_discovery_browser.py 변경 및 tests/test_keyword_discovery_uc.py, UC 문서도 새로 발견됐다. 이들은 사용자의 후속 작업으로 취급하고 되돌리거나 덮어쓰지 않는다. 현재 패키지 설치 상태와 이 변경 이후 테스트 결과는 이 대화에서 재검증하지 않았다. UC 변경 이후 실제 재수집은 실행하지 않았으므로 성공했다고 인계하지 않는다.

## 9. 아직 남은 설계·데이터 공백

1. **메뉴별 5회 수집으로 중복 제거가 미구현이다.** 현재 build_rank_tasks는 매장×후보로 25개를 만든다. 동일 검색어·기기·좌표 없는 프로필의 관측 1개를 5개 매장에 연결하려면 공유 관측 식별자와 매장별 평가 연결을 함께 바꿔야 한다. 첫 매장 task만 남기면 나머지 매장은 select_rank에서 연결되지 않는다.
2. 별도 플레이스 목록을 원천으로 채택할지는 미확정이다. 통합검색과 다른 순위 표면이므로 별도 프로필·원천 구분 및 비교 검증이 필요하다. 현재 보안 확인 상태에서 자동 재시도를 확대하지 않는다.
3. knowledge.categories와 synonyms는 빈 객체다. 공식 메뉴 5개만 DINING이며 나머지 의도·적합성은 미확정이다. 근거를 검토한 규칙을 버전과 함께 추가해야 한다.
4. 리뷰를 읽는 것과 메뉴·서비스의 사실 근거로 승인하는 것은 다르다. verified_support를 임의로 올리지 않는다.
5. keywordList 수집 연결 코드는 있지만 실제 파일럿의 완전한 경쟁점 목록과 연결된 신규 성공 결과가 아직 없다.
6. 신규 V2 프로필의 실제 자연순위 20개 결과가 없고, 사람 판정 입력·자동 비교·임계치 교정도 미완료다.
7. 운영 DB 평가 결과 저장과 재조회 검증은 별도로 완료해야 한다. 코드/합성 테스트 통과를 실제 저장 완료와 혼동하지 않는다.

## 10. 검증 이력과 재개 순서

일반 Selenium 기반 보완 시점 관련 전체 테스트 **472개 통과**(91.89초). 무관한 기존 미추적 육수당 분석 SQL 테스트 5개 파일은 제외했다. 이후 타임아웃 메시지 정리 후 관련 72개도 통과했다. **이 기록은 사용자 UC 변경 전 결과이며 현재 작업 트리 전체의 통과 보증이 아니다.**

재개 시 권장 순서:

1. git diff로 사용자 변경과 이전 구현을 구분하고, 현재 의존성·오프라인 테스트 상태를 새로 확인한다. 이 인계의 오래된 테스트 수를 재사용하지 않는다.
2. 보안 확인을 우회하지 않는 접근과 수집 원천을 확정한다. 사용자 직접 확인이 필요한 경우 화면을 제공하고 대기하는 경로를 마련한다.
3. 메뉴별 공유 관측과 매장별 평가 참조를 구현·테스트한다. 25건 중복 수집을 그대로 시작하지 않는다.
4. 메뉴 1건에서 자연순위 20개 또는 명시적 짧은 결과 끝, 광고 분리, 누락 검증을 확인한다. 불완전한 결과는 PARTIAL로 유지한다.
5. 정상 경로 확인 후 메뉴 5개로 확대하고 원천 실행 ID·프로필·시간대를 동결한다.
6. 원천을 새 입력으로 재수출하고 경쟁점 규칙 및 keywordList 근거를 보완한다.
7. 평가 저장·재조회 재현성을 확인하고 5개 매장 사람 판정과 비교한다. 교정 전 임계치는 파일럿 초깃값으로 유지한다.

사람 검토 필드: 외식 의도, 매장 적합성, 경쟁 유형, 시장 유형, 추천 여부, 판정 확신도, 판정 사유. 최종 대표키워드 5개 자동 선정은 이 단계 이후 별도 구현한다.

## 11. 작업 트리 보존

이 문서 작성 시 git에는 브라우저·검증기·의존성·브라우저 테스트 수정, 평가 패키지·DDL·설계 문서·테스트 신규 파일이 있다. 그 외 기존 업무보고서, artifacts, backups, .tmp, 육수당 관련 SQL·테스트 등 미추적 파일이 다수 존재한다. `git add .`, 일괄 삭제, 일괄 포맷, 임의 커밋을 하지 않는다.

인계 내용은 현재 코드·로컬 산출물과 이 대화에서 확인한 DB 조회 기록을 결합한 것이다. 이번 문서 작성 시 DB를 재조회하지 않았으므로 다른 작업자가 이후 적재했을 가능성까지 배제하지 않는다. 실행 재개 직전에는 해당 run_id와 최신 상태를 읽기 전용으로 재확인한다.
