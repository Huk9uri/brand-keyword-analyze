# 후보 선별 및 확대 수집 실행 방법

## 적용 범위

2026-09-10 승인된 네 단계를 실행한다. 기존 후보 3,850행은 수정하지 않고 후보 ID별 선별 결과를 파일로 분리한다. 고유 검색어는 776개다. 기존 최종 평가 엔진의 검색량 하한과 경쟁 판정 임계치를 선별에 사용하지 않는다.

선별 규칙은 `inputs/keyword_screening_policy.json`에 버전과 근거를 보관한다. 공식 메뉴 5개 및 명시적인 상위 표현 관계를 사용한다. 예를 들어 왕갈비탕 판매 근거를 갈비탕 후보의 파생 근거로 기록하지만 두 검색어를 병합하지 않는다. `맛집`은 방문 목적 수식어로만 인식하며 다른 수식어를 임의 제거하지 않는다.

창업·가맹·밀키트·조리법·택배·납품 등 명확한 비방문 패턴은 해당 일치 표현을 기록해 제외한다. 메뉴 포함 여부만으로 한우·24시간·배달 등의 조건을 승인하지 않는다. 그 밖의 표현은 정보 부족으로 보류한다. 리뷰 추출 근거 760행도 연결하지만, 단순 추출 사실을 매장 적합성 검증 완료로 바꾸지 않는다.

현재 입력에는 검증된 지역·서비스별 검색어 판정이 없으므로 `store_facts`는 비어 있다. 향후 해당 Place ID에만 적용되는 주소·매장 정보 근거를 추가할 수 있다. 필요한 항목은 `keyword`, `verified`, `source`, `evidence`, `verified_at`이며 `decision`은 PASS/FAIL, `category`는 REGION_MENU 또는 STORE_INFO 등으로 기록한다. 상충된 근거는 보류한다. 타 매장 근거는 공유하지 않는다.

## 오프라인 선별

```powershell
.venv/Scripts/python.exe -m scripts.keyword_evaluation.screening_cli --input outputs/search-exposure-20260909T072031Z/input-final.json --output outputs/screening-offline-new
```

`screening.json`에 원본 표현·정리된 검색어·후보 ID·출처·근거·분류·검색량 상태를 기록한다. `collection-plan.json`에 검색량 조회 키와 순위 큐를 기록한다. `exposure.json` 및 `report.md`에 관측 결과를 출력한다.

공백은 연속 공백 축약과 양끝 제거만 수행한다. NFKC·casefold를 기존 키 계약과 동일하게 적용한다. 검색광고 조회 키만 공백을 제거하여 공유하며, 순위 검색에는 정리된 공백을 유지한다.

## 실제 수집 및 적재

```powershell
.venv/Scripts/python.exe -m scripts.keyword_evaluation.screening_cli --source-config outputs/search-exposure-20260909T072031Z/source-config-final.json --output outputs/candidate-screening-live-20260910 --collect --allow-write --allow-network
```

1. DB 원천을 현재 시각 기준으로 재수출하고 식별·좌표 계약을 확인한다.
2. 우선 후보 중 유효 검색량이 없는 조회 키만 공통 수집·저장한다.
3. 다시 DB를 읽고 공식 메뉴·지역 메뉴, 메뉴 관련 표현, 기타 매장 근거 순서로 순위 큐를 작성한다. 같은 단계는 정확 검색량 내림차순이며 저검색량 구간과 미제공도 큐에 남긴다. 실패·기간 미검증은 검색량 재확인 대상으로 남긴다.
4. 유효한 동일 매장 좌표 V4 순위가 있으면 재사용한다. 나머지는 UC와 독립 프로필로 일반 TOP20을 수집하고 기존 스냅샷·결과 테이블에 저장한다.
5. 일반 TOP10 내 자사 브랜드를 제외한 모든 매장을 노출 경쟁점으로 보고한다. 업종 필터 및 거리 점수는 사용하지 않는다. 자사 미노출은 관측 상태이며 제외 사유가 아니다.

단계별 산출물은 `01-screened`, `02-volume`, `03-final`에 있다. 검색량 원문과 저장 영수증, 순위 계획 및 영수증도 별도로 기록한다. 완료 영수증이 있는 실행을 재개할 때는 최신 `source-config.json`을 입력으로 새 출력 경로를 사용한다. 프로세스 강제 종료로 영수증이 없으면 DB 실행 ID와 저장 범위를 먼저 확인해야 한다.

기존 keywordList 수집 URL·수집기는 변경하지 않는다. 이번 네 단계는 후보·검색량·순위·노출 경쟁점 목록까지이며, 새 경쟁점 keywordList 보강 및 최종 추천 기준 교정은 별도 후속 단계다.

## 검증

```powershell
.venv/Scripts/python.exe -m pytest tests -k 'keyword_discovery or keyword_evaluation or place_keyword' --basetemp=tmp/screening-final-tests -q
```

실제 DB 검증에서는 계획과 저장 task_key 일치, 매장별 좌표·프로필, 일반 순위 연속성, 광고 순위 NULL, Place ID 중복 여부, 성공 시 일반20 또는 명시적 끝표시를 확인한다. 선별 원본과 정책의 해시를 보존한다.

## 2026-09-10 최종 확인

55건 신규 순위와 25건 기존 순위를 연결한 최종 결과는 `outputs/candidate-screening-live-20260910/04-verified`다. 최초 `03-final`의 초 단위 시각 경계 문제는 재수집 없이 재수출로 해결했다. `verification-04.json`에서 유효 순위 80건 및 남은 수집 0건을 확인할 수 있다. 신규 스냅샷 저장 시각은 초 단위 절삭을 적용한다.
