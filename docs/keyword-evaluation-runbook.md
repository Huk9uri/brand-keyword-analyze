# 키워드 후보 평가 실행 안내

최신 설계 결정은 [매장 좌표 기준 플레이스 목록](2026-09-09-place-list-source-decision.md)이다.
V4 목록 수집 구현을 완료했다. 최신 실수집 입력은 `rank_profile=MOBILE_PLACE_LIST_STORE_LOCATION_ORGANIC20_V4`와
매장별 `search_location`이 필요하다. 아래 과거 V1 설명은 이전 구현 기록이며 새 프로필과 혼합하지 않는다.

## 범위와 승인

평가 코드는 오프라인 입력으로 빈집·경쟁·제외·검토필요를 계산한다. 검색량 스냅샷과 평가 결과를 분리한다. 최종 5개 선정은 제공하지 않는다. 이번 구현에서 운영 DB DDL·실제 API 수집·적재·커밋·push는 실행하지 않았다.

DDL 파일은 `sql/keyword_evaluation/01_create_tables.sql`이다. 운영자가 검토·승인 후 naverDB에서 별도로 실행한다. 기존 테이블이 존재하면 생성이 생략되므로 `02_verify_tables.sql`로 컬럼·제약을 대조해야 한다. 애플리케이션은 DDL을 자동 실행하지 않는다. 실제 SQL Server 생성·트랜잭션 통합 검증은 별도 승인된 테스트 DB에서 수행한다.

## 환경

프로젝트 루트 PowerShell 기준:

```powershell
uv venv .venv --python 3.12
uv pip install --python .venv/Scripts/python.exe -r requirements-keyword-discovery.txt
.venv/Scripts/python.exe -m scripts.keyword_evaluation.cli --help
```

연결 설정은 기존 `.env`의 DB_SERVER·DB_PORT·KEYWORD_DISCOVERY_DB_DATABASE·KEYWORD_DISCOVERY_DB_USER·KEYWORD_DISCOVERY_DB_PASSWORD를 사용한다. 대상 DB는 naverDB로 제한한다. 검색광고는 NAVER_SEARCHAD_CUSTOMER_ID·NAVER_SEARCHAD_API_KEY·NAVER_SEARCHAD_SECRET_KEY만 필요하며 DataLab 키는 요구하지 않는다. 비밀을 입력 JSON·출력·fixture에 넣지 않는다.

## 1. 오프라인 동작 확인

`inputs/keyword_evaluation.synthetic.json`은 실제 매장이 아닌 합성 테스트 사례다. 실제 검색량·현재 순위로 해석하지 않는다.

```powershell
.venv/Scripts/python.exe -m scripts.keyword_evaluation.cli evaluate --input inputs/keyword_evaluation.synthetic.json --output tmp/evaluation-demo
```

출력은 evaluation.json, collection_queue.json, review.csv다. 출력 디렉터리는 새 경로여야 한다. 기존 파일을 덮어쓰지 않는다. review.csv는 기본적으로 자동 분류를 숨긴다. 비교용 자동 분류가 필요하면 `--show-automatic`을 추가한다. CSV의 수식 형태 문자열은 텍스트로 이스케이프한다.

## 2. 실제 DB 원천을 읽기 전용으로 동결

`inputs/keyword_evaluation.source.example.json`은 조사 당시 후보 run_id 5개를 지정한 설정 예제다. 복사본에서 as_of_at, 시간대 근거, 매장 매핑, 수집 실행 목록을 검토한다. 기존 스냅샷을 좌표 없는 새 프로필로 재명명해서는 안 된다. 예제는 기존 좌표 기반 rank run을 넣지 않는다.

```powershell
.venv/Scripts/python.exe -m scripts.keyword_evaluation.cli export-source --input inputs/keyword_evaluation.source.example.json --output tmp/evaluation-input.json
```

검색량 테이블은 이 명령 전에 승인된 DDL로 준비해야 한다. 후보는 지정 run_id·place_id·STORE로 읽는다. 후보 건수는 예제에 고정된 기대값으로 검사한다. 리뷰는 원본 수집 상태·본문을 함께 읽지만 verified_support를 자동으로 true로 만들지 않는다. 순위·keywordList·검색량은 관측 이력을 읽고 평가 시점 이하에서 선택한다. 좌표·거리 컬럼은 조회하지 않는다.

매장별 operation_status는 정상 운영 뷰와 대조한다. 명시적 CONFLICT는 뷰 조회만으로 해제하지 않는다. 수원파장점은 운영 상태 확인 전 CONFLICT를 유지한다. 새 수집의 대상 식별자는 예제에서 EVAL-PlaceID로 명시한 별도 네임스페이스이며 ERP 매장코드에서 자동 유추한 값이 아니다. 선릉역점 기존 식별자는 근거가 확인된 IYN-000117이다.

원천 datetime2의 offset은 원천 실행의 실제 시간대 증거로 지정한다. 기존 keywordList와 새 수집 결과의 저장 시간대가 다르면 같은 기본 offset을 적용할 수 없다. `keyword_run_time_offsets`에 run_id별 offset을 지정한다. 새 평가 수집기는 UTC를 timezone 없는 기존 datetime2에 저장하고 영수증에 +00:00을 반환한다. 수집 시간대 매핑을 반드시 보존한다.

## 3. 의도·적합성·경쟁점 규칙

bundle.knowledge는 version, evidence, intent, categories, synonyms, own_place_ids, own_registry_complete를 갖는다. 키워드 키는 NFKC·공백축약·casefold 결과로 작성한다.

```json
{
  "version": "사람검토-1",
  "evidence": "검토한 규칙의 문서 또는 판정 식별자",
  "intent": {"설렁탕": "DINING", "설렁탕 레시피": "NON_DINING"},
  "categories": {"설렁탕": {"곰탕,설렁탕": "DIRECT", "카페": "NON_COMPETITOR"}},
  "synonyms": {},
  "own_place_ids": ["31076466"],
  "own_registry_complete": false
}
```

이 코드 블록은 규칙 구조 예시이며 모든 업종 분류를 승인한 기본값이 아니다. categories는 후보별 정확한 원천 category 값의 매핑이다. 미등록 업종은 UNKNOWN이다. 자사 전체 목록의 완전성을 확인하기 전 own_registry_complete=true로 바꾸지 않는다. 동의어는 전체 방문 의도가 동일한 승인 표현만 등록한다. LLM 신규 제안은 자동 등록하지 않는다.

공식 메뉴는 official_menus 및 menu_evidence로 지정한다. 서비스·영업 조건을 요구하는 표현은 fit_constraints에 decision=UNKNOWN, requires_service=true 및 근거를 기록한다. 현재 근거로 명백한 충돌이 있으면 FAIL 또는 CONFLICT다. 단순 부분 문자열 일치로 메뉴 판매를 확정하지 않는다.

리뷰 맥락을 자동 근거로 사용하려면 해당 원본의 검토 후 verified_support=true, support_kind=CONTEXT, verification_evidence, support_excerpt를 입력한다. support_excerpt는 source_context 원문에 실제 존재해야 한다. 원본 수집 상태 success, 기간·가중치·키 일관성을 모두 검사한다. 초기 DB 내보내기는 이 값을 false로 둔다. 리뷰 3건 규칙은 맥락에만 적용하며 실제 판매·서비스 제공을 대신하지 않는다.

## 4. 검색량 수집·저장

후보 저비용 게이트를 먼저 실행하고 통과한 고유 검색어만 수집한다. 같은 검색광고 키는 5개 매장이 공유한다. 네트워크와 DB 쓰기는 아래 두 플래그를 모두 명시해야 한다. 운영 승인 전에 실행하지 않는다.

수집 입력은 `{"bundle": <내보낸 입력>, "period": {"period_type":"UNVERIFIED", "period_definition":""}}` 형태다. 검증된 공급자 월간 정의가 있으면 PROVIDER_MONTHLY와 그 근거 문자열을 사용한다. 공급자가 보장하지 않는 30일 시작·종료일을 만들지 않는다. period 메타데이터는 수치·수집시각을 덮어쓸 수 없다.

```powershell
.venv/Scripts/python.exe -m scripts.keyword_evaluation.cli collect-volume --input tmp/volume-request.json --output tmp/volume-receipt.json --allow-network --allow-write
```

검색광고 요청은 기존 인증·재시도 구현을 사용하되 원문 응답을 새 파서로 처리한다. <10은 구간 [0,9], 미제공은 NOT_PROVIDED, 호출 실패는 FAILED로 저장한다. 인증 실패는 수집을 중단한다. period_definition의 검증된 문자열을 원천 설정의 verified_volume_periods에 등록해야 자동 수요 게이트가 통과한다. 기간 정의가 없는 관측도 저장할 수 있지만 자동 시장 판정에는 쓰지 않는다.

수집 후 export-source를 새 파일로 실행하여 영구 volume_snapshot_id가 포함된 입력을 만든다. 저비용 모집단을 고정하고 evaluate를 다시 실행한다. 기존 evaluation.json을 수정해 새 검색량을 끼워 넣지 않는다.

## 5. 제한된 순위·keywordList 수집

evaluate 결과의 collection_queue는 메뉴·고수요·경계·불확실 표본을 매장당 최대 20개로 제한한다. 확정 제외·운영 충돌은 수집하지 않는다. 수집하지 않은 후보도 평가 결과에 남는다.

```powershell
.venv/Scripts/python.exe -m scripts.keyword_evaluation.cli collect-rank --input tmp/evaluation-demand/evaluation.json --output tmp/rank-receipt.json --allow-network --allow-write
```

평가 전용 경로는 PlaceLocationResolver를 호출하지 않으며 latitude/longitude=None으로 브라우저를 생성한다. 기존 수집기의 기본 동작은 변경하지 않는다. 장치 MOBILE, 프로필 MOBILE_NO_LOCATION_V1이다. 기존 20카드 제한을 사용하므로 광고가 있으면 자연 20위가 확보되지 않을 수 있다. 평가기는 이를 DEPTH_INSUFFICIENT 등으로 구분한다. 반환 run_id·profile·source_timezone을 원천 설정 rank_runs에 추가한다.

다시 export-source/evaluate 후 keywordList가 필요한 직접 경쟁점에만 아래를 실행한다.

```powershell
.venv/Scripts/python.exe -m scripts.keyword_evaluation.cli collect-keywords --input tmp/evaluation-rank/evaluation.json --output tmp/keyword-receipt.json --allow-network --allow-write
```

직접 경쟁점 유형이 UNKNOWN이면 먼저 규칙을 검토해야 한다. 이 명령은 무작정 모든 미확정 카드의 상세정보를 수집하지 않는다. 정상·신선한 keywordList는 재사용하고 누락·오류·STALE 대상만 고유 Place ID별로 수집한다. 새 keywordList run_id의 시간대 +00:00을 keyword_run_time_offsets에 추가한다.

## 6. 평가 저장과 사람 검토

```powershell
.venv/Scripts/python.exe -m scripts.keyword_evaluation.cli save --input tmp/evaluation-final/evaluation.json --output tmp/evaluation-receipt.json --allow-write
```

save는 동결 입력을 재평가하여 전달받은 결과가 동일한지 확인한다. 실행·후보 결과·모든 근거를 한 트랜잭션으로 저장한다. 실패 시 전체 rollback한다. 저장 영수증에 candidate_id→evaluation_result_id가 들어 있다.

사람 판정은 JSON 배열로 저장한다. 행 필드는 evaluation_result_id, reviewer, reviewed_at, dining_intent, store_fit, competition_type, market_type, recommendation, confidence, reason이다. 허용 ENUM은 설계 및 DDL을 따른다. reviewed_at은 offset이 있는 ISO 시각이다. 새 판정은 기존 판정을 덮어쓰지 않는다.

```powershell
.venv/Scripts/python.exe -m scripts.keyword_evaluation.cli save-reviews --input tmp/human-reviews.json --output tmp/review-receipt.json --allow-write
.venv/Scripts/python.exe -m scripts.keyword_evaluation.cli compare --input tmp/evaluation-final/evaluation.json --reviews tmp/comparison-reviews.json --output tmp/comparison.json
```

compare 입력은 candidate_id, input_hash, market_type를 가진 고정 판정 배열이다. 같은 후보의 중복 판정은 거절하므로 비교할 review_id의 최종 버전을 먼저 선택한다. 매장별 혼동행렬·일치율·자동 판정 수를 출력한다. 운영 충돌은 성능 분모에서 분리한다. 표본이 없으면 정확도 NULL이다. 임계치 변경은 새 rules·새 평가 입력으로 실행한다.

## 검증과 남은 운영 단계

```powershell
.venv/Scripts/python.exe -m pytest tests/test_keyword_evaluation_contract.py tests/test_keyword_evaluation_engine.py tests/test_keyword_evaluation_repository.py tests/test_keyword_evaluation_cli.py tests/test_keyword_evaluation_source_export.py -q --basetemp tmp/evaluation-verification
```

단위·회귀 테스트는 합성 데이터와 fake DB로 실행한다. 실제 DB의 외래키·datetimeoffset 전송·권한·DDL 재실행 여부, 실제 검색광고 기간 정의, 실제 브라우저 페이지 변화는 승인된 통합 검증에서 확인한다. 운영 상태 충돌·기간 미확인·자사 목록 불완전·미등록 업종은 코드 오류로 숨기지 않고 검토필요로 남긴다. 이 단계의 성공은 자동 판정 수를 늘리는 것이 아니라 근거가 부족한 후보를 자동 통과시키지 않는 것이다.
