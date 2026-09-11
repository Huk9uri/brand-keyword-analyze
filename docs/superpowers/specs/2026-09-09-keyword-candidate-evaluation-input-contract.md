# 키워드 후보 평가 모듈 입력·출력 계약

- 작성일: 2026-09-09
- 조사 기준: `feat/keyword-candidate-evaluation`, `198d73b`
- 상태: 대화에서 승인한 설계 초안과 수정된 구현 순서를 문서화함. 구현 완료를 의미하지 않음.
- 승인 범위: 설계 문서 작성. DDL 실행·적재·커밋·push는 별도 승인 대상.
- 목적: 매장별 후보를 빈집·경쟁·제외·검토필요로 분류하고 관측 근거를 재현한다.
- 제외 범위: 최종 대표키워드 5개 자동 선정, 좌표·거리, 운영팀 키워드, SKYPOS 매출.

## 1. 조사 방법과 근거

현재 코드·SQL을 읽고, 기존 연결 설정으로 naverDB 및 매장 식별에 필요한 ERP 원장에 SELECT를 수행했다. 스키마는 INFORMATION_SCHEMA.COLUMNS, sys.indexes, sys.index_columns, sys.foreign_keys 및 대상 뷰 정의로 확인했다. 기존 미추적 파일·업무보고서는 수정하지 않았다.

| 근거 파일 | 확인 내용 |
|---|---|
| `scripts/keyword_candidate_discovery/batch.py` | 매장별 후보 실행, 공통 메뉴·연관어 적용 |
| `scripts/keyword_candidate_discovery/repository.py` | 후보·리뷰 FK 연결과 매장별 트랜잭션 |
| `scripts/keyword_candidate_discovery/review_source.py` | 브랜드·문자 정규화, 리뷰 조회 범위 |
| `scripts/keyword_candidate_discovery/aggregator.py` | 후보 상태·리뷰 수·가중 언급량 |
| `scripts/keyword_candidate_discovery/extractor.py` | 문자열 기반 추출과 발췌 방식 |
| `scripts/keyword_candidate_discovery/searchad_source.py` | 연관어만 반환하고 검색량은 저장하지 않음 |
| `scripts/yuksudang_volume/searchad.py` | 검색량 정규화·원문 값·저검색량 처리 |
| `scripts/yuksudang_volume/pipeline.py` | 파일 캐시, 월간 검색량과 일간 추정치의 구분 |
| `scripts/run_keyword_volume.py` | 출력 파일과 30일 배분 기간 |
| `scripts/keyword_discovery_rank/task_source.py` | 대상 식별 입력, 검색어 정규화, task_key |
| `scripts/keyword_discovery_rank/cli.py` | 현재 DB 입력 비활성화, 좌표 해석 경로 |
| `scripts/keyword_discovery_rank/validation.py` | 광고 포함 카드 수 기준 수집 상태 |
| `scripts/keyword_discovery_rank/matching.py` | 자사 목록 범위와 ID·이름 매칭 |
| `scripts/place_keyword_collector/rank_source.py` | 기존 수집기는 SUCCESS·PARTIAL에서 수집 대상을 추출 |
| `scripts/place_keyword_collector/repository.py` | effective_snapshot_id와 과거 버전 조회 |
| `scripts/place_keyword_collector/parser.py` | keywordList 정규화 |
| `sql/keyword_candidate_discovery/01_create_tables.sql` | 후보·리뷰 테이블 정의 |
| `sql/keyword_discovery_rank/01_create_tables.sql` | 순위 스냅샷·카드 정의 |
| `sql/place_keyword_collector/01_create_tables.sql` | keywordList 확인·내용 정의 |
| `inputs/hanchon_keyword_candidate_pilot.json` | 승인된 대상·공식 메뉴·리뷰 기준일 |

### 1.1 고정할 파일럿 후보 실행

| 매장 | place_id | 후보 수 | candidate run_id |
|---|---|---:|---|
| 부천본점 | 12012595 | 773 | 72ED626C-072F-4003-8F3E-35B6D9FB8BCB |
| 강동점 | 11627699 | 768 | D8E32C55-A8A0-4BAC-9F5F-A3750853B5E1 |
| 천안쌍용점 | 17391216 | 773 | 95AE9FB9-3D82-4621-920A-415A13477DEF |
| 선릉역점 | 31076466 | 769 | 01D4745E-B193-49D1-A902-79131FAA9C51 |
| 수원파장점 | 34883104 | 763 | F9753D07-B2E6-43A8-91E8-BC96534814FC |

합계 3,846개. 각 매장에 같은 검색광고 연관어 755개와 공식 메뉴 5개가 존재한다. 최신 배치의 운영팀 출처는 0개다. 공식 공통 메뉴는 `from_menu=1`이며 `from_brand_menu`는 모두 0이다. 메뉴는 설렁탕·왕갈비탕·얼큰설렁탕·도가니탕·소머리곰탕이다.

현재 후보 상태는 READY 3,825개, INSUFFICIENT_EVIDENCE 15개, EXCLUDED 6개다. READY는 외부 후보 병합으로도 설정되므로 평가 적합성 통과와 동의어가 아니다.

### 1.2 실제 스키마와 일관성

모든 아래 테이블은 `naverDB.dbo`에 존재한다.

| 테이블 | 핵심 형식·키 |
|---|---|
| naver_keyword_discovery_candidate | candidate_id bigint PK; run_id uniqueidentifier; brand_code varchar(10); candidate_scope varchar(10); place_id varchar(50); normalized_keyword nvarchar(255); 리뷰 집계·출처 플래그·상태; generated_at datetime2(0) |
| naver_keyword_discovery_review_term | review_term_id bigint PK; candidate_id bigint FK; run_id uniqueidentifier; source_type varchar(10); source_review_id bigint; brand_code·place_id·normalized_keyword; review_date date; raw_expression nvarchar(500); evidence_excerpt nvarchar(1000); time_weight decimal(3,2); analyzed_at datetime2(0) |
| naver_keyword_discovery_snapshot | snapshot_id bigint PK; run_id uniqueidentifier; task_key char(64); normalized_query nvarchar(255); target_store_id nvarchar(100); source_type·source_id·device_type; 수집 제한·관측 수·종료 여부·상태; collected_at datetime2(0) |
| naver_keyword_discovery_result | PK(snapshot_id, raw_position); organic_rank smallint NULL; place_id varchar(50); place_name·category; is_ad·is_own_store·is_target_store; matched_store_id·match_method |
| naver_place_keyword_snapshot | snapshot_id bigint PK; run_id·rank_run_id uniqueidentifier; place_id varchar(50); 상태·해시·keyword_count; effective_snapshot_id bigint NULL; checked_at datetime2(3) |
| naver_place_keyword_result | UNIQUE(snapshot_id, keyword_order); raw_keyword·normalized_keyword nvarchar(255) |

후보 유일키는 `(run_id, brand_code, candidate_scope, place_id, normalized_keyword)`, 리뷰 근거 유일키는 `(run_id, source_type, source_review_id, normalized_keyword)`다. 순위 실행 유일키는 `(run_id, task_key)`, 자연순위는 snapshot 내 NULL을 제외한 유일 인덱스가 있다. keywordList 확인 유일키는 `(run_id, place_id)`다.

문자 컬럼 collation은 Korean_Wansung_CI_AS다. 관련 FK는 활성화·신뢰 상태였다. 순위 자연 카드의 같은 snapshot 내 place_id 중복은 0그룹이었다. 최신 후보 리뷰 근거 741건에서 후보와 run·brand·place·keyword 불일치는 0건이었다. keywordList SUCCESS/EMPTY 77개 확인 행의 effective 연결 오류는 0건이었다. 이 값들은 조사 당시의 검증 결과이며 신규 실행에서도 다시 검사한다.

### 1.3 데이터 공백·사실 충돌

- 검색량 전용 테이블은 이번 naverDB 스키마 조사에서 확인되지 않았다. 기존 한촌 검색량 파일은 운영팀 최종 키워드 원천이므로 이번 입력에서 제외한다.
- smartplace_keyword_all의 유입 비중, smartplace_count_all의 유입 수는 검색광고 검색량이 아니다.
- 기존 naver_place_rank에는 place_id·광고 분리·경쟁점 카드·실행 연결이 부족하므로 평가 주 원천으로 사용하지 않는다.
- 5개 대상 중 순위 스냅샷은 선릉역점만 확인됐다. 다른 매장의 스냅샷으로 대체하지 않는다.
- 선릉역점의 snapshot 156은 설렁탕 자연 3위, 157은 도가니탕 자연 2위다. 2026-09-04 관측이며 현재 시점의 순위라는 의미가 아니다.
- 최근 선릉역점 순위 실행 D32FBDC3-3AF6-4D25-85E1-FE6970855DF1의 9개 검색어는 각각 자연 카드 10개와 그 카드들의 keywordList 유효 확인이 존재한다. 자연 20위 관측을 의미하지 않는다.
- 리뷰 근거는 부천 214건, 강동 100건, 천안 339건, 선릉 83건, 수원 5건이다. 원본 상태 NULL 225건(BLOG 142, VISITOR 83)은 자동 확정 근거에서 분리한다.
- 추출은 대부분 부분 문자열 검사이며 evidence_excerpt는 본문 앞 1,000자다. 부정·타 매장·과거 언급 또는 실제 일치 구간을 보장하지 않는다.
- 대상 뷰의 부천·강동·천안·선릉 ERP 코드는 각각 000042·000038·000105·000117이고 매핑 상태는 CONSISTENT다.
- 수원파장점은 store_hours_long에서 000071↔34883104로 확인되지만 ERP 원장에 DT_CLOSE=20260730, CD_OPERATION=004가 있어 정상 운영 뷰에서 빠져 있다. 실제 폐점을 단정하지 않는다. 운영 사실 확인 전 매장 전체를 STORE_OPERATION_CONFLICT로 보류한다.
- 5개 매장의 영업정보는 각각 7요일 행이 있지만 수원은 2026-08-06, 나머지는 2026-09-08 확인이다. 이번 매장 비교 점수에는 영업정보를 사용하지 않는다.
- 기존 자사 판별은 입력된 목록 안에서만 작동한다. 5개 파일럿 대상 목록을 전체 자사 브랜드 목록으로 취급하지 않는다.

## 2. 실행 입력과 연결 계약

### 2.1 실행 입력 동결

평가 실행은 as_of_at(datetimeoffset), 대상 5개, 위 후보 실행 5개, 메뉴 목록, 원천별 시간대, 정규화·판정 규칙 버전, 수집 프로필, 임계치 설정을 받는다. 모든 선택은 as_of_at 이하 관측으로 제한한다. 선택한 ID·실제 사용 값·모집단·해시를 동결한다. 다시 실행할 때 최신 원천을 다시 선택하지 않는다.

기존 datetime2에는 시간대가 없다. 코드가 datetime.now()를 사용하며 조사 당시 DB 서버 시각은 UTC였다. 원천 시간을 DB 시간대로 일괄 해석하지 않는다. 원천별 시간대 증거를 매핑하고 미확인 원천은 TIMEZONE_UNVERIFIED로 자동 판정을 차단한다. 파일럿 리뷰 기간은 기존 AnalysisWindow와 동일한 2025-09-09~2026-09-09 양끝 포함이다.

### 2.2 정규화

| 원천 | 현재 규칙 |
|---|---|
| 외부 후보 | NFKC, 공백 축약, trim; 소문자 변환 없음 |
| 리뷰 후보 | 사전에 정의된 대표 표현 |
| 순위 query | 공백 축약, trim; NFKC·casefold 없음 |
| 검색광고 | 모든 공백 제거, casefold; NFKC 없음 |
| keywordList | NFKC, 공백 축약, casefold |

평가의 `evaluation_keyword_key`는 NFKC→공백 축약→trim→casefold로 생성하며 공백을 보존한다. `searchad_lookup_key`는 기존 검색광고 함수와 동일하게 생성하며 검색량 연결에만 쓴다. 원문·원천 normalized 값은 별도로 보존한다. 동일 키로 합쳐지는 원천 값은 충돌 목록을 생성한다. 같은 검색광고 키의 검색량 공유는 허용하지만 이를 이유로 서로 다른 순위 query를 합치지 않는다.

Place ID는 ASCII 숫자 문자열을 trim하여 varchar(50) 범위로 검증한다. 숫자로 변환하지 않는다. 브랜드 01·1·001의 한촌 대응은 명시적인 원천 매핑으로 관리한다. 일반 브랜드 식별 전체를 정수 변환하는 방식으로 확장하지 않는다.

### 2.3 JOIN 규칙

1. 후보는 candidate_id로 식별하고 STORE scope 및 target_place_id 일치를 확인한다.
2. 리뷰는 candidate_id FK로 연결한 다음 run_id·brand·place·keyword를 검사한다. 원문은 source_type에 따라 BLOG/VISITOR를 선택하고 source_review_id로 조회한다.
3. 순위는 명시적인 target_store_id↔place_id 매핑, query 대응, device_type, 수집 프로필로 연결한다. 선릉 IYN-000117↔31076466은 기존 Excel 자사매장 시트와 DB 매핑에서 확인됐다. 다른 대상의 IYN 접두 식별자는 추정 생성하지 않는다.
4. 후보 run_id와 순위 run_id는 다른 실행이다. 순위 source_id는 candidate-IYN-000117-09 같은 문자열일 수 있어 candidate_id FK가 아니다. 현재 CLI DB 입력은 비활성화돼 있다.
5. task_key는 기존 구현에서 검색어·대상·기기·좌표를 해시한 값이다. 평가에는 불투명 식별자로만 저장하고 좌표 조회·계산·비교에 사용하지 않는다.
6. 순위 카드는 snapshot_id, keywordList는 카드 place_id로 연결한다. keywordList rank_run_id는 수집 출처일 뿐 동일 값만 JOIN하는 조건이 아니다.
7. keywordList 내용은 선택한 확인 행의 effective_snapshot_id로 조회한다. 같은 Place ID이고 유효 상태인지 확인한다.
8. SQL collation에 의존해 서로 다른 정규화 규칙을 동일시하지 않는다. 모호한 다대다 연결은 AMBIGUOUS_JOIN이다.

### 2.4 최신 선택

| 원천 | 선택·실패 처리 |
|---|---|
| 후보 | 파일럿은 명시된 5개 run_id. 실행 완료 테이블이 없으므로 MAX(generated_at)을 최신 성공 배치로 간주하지 않음. 매장별 예상 건수·공통 집합·출처를 검사 |
| 리뷰 | 고정 candidate의 같은 실행 근거만 사용. 날짜·원본 상태·실제 언급 검증 |
| 검색량 | 공급자·조회 키·기간 정의가 같은 집합에서 fetched_at DESC, volume_snapshot_id DESC. 최신 시도와 최신 유효 관측을 함께 보존. 최신 실패 후 과거 수치 재사용은 참고만 허용 |
| 순위 | 동일 대상·query·device·수집 프로필에서 collected_at DESC, snapshot_id DESC. 최신 시도가 PARTIAL/실패면 과거 성공으로 자동 판정 복구 금지 |
| keywordList | place_id별 checked_at DESC, snapshot_id DESC로 최신 시도와 최신 SUCCESS/EMPTY 확인을 각각 선택. 최신 실패 후 과거 버전 재사용은 STALE_FALLBACK |

keywordList 내용이 오래전에 만들어졌어도 최근 SUCCESS/EMPTY 재확인이 있으면 그 확인일로 신선도를 계산한다. 기존 get_previous SQL은 실패 확인일도 반환할 수 있어 평가용 선택기로 재사용하지 않는다. TTL은 as_of_at-유효확인시각 <= 설정값일 때 통과한다. 미래 데이터는 사용하지 않는다. 순위·keywordList 시차는 절댓값으로 검사한다.

## 3. 항목별 입력·계산 계약

공통 항목은 value, status, evidence_refs, rule_id, version을 갖는다. 상태는 VALID·UNKNOWN·MISSING·FAILED·STALE·CONFLICT·NOT_APPLICABLE이다. NULL과 0은 다르다. 연속 점수 없는 게이트를 임의 확률로 변환하지 않는다.

### A. 검색 의도

- 출력: DINING·MIXED·NON_DINING·UNKNOWN. 자동 통과는 DINING만 허용.
- 밀키트·택배·레시피·칼로리·식자재·프랜차이즈 창업 목적이 명백한 표현은 NON_DINING. 외식 목적과 섞이거나 전체 표현이 애매하면 MIXED/UNKNOWN.
- 단순 부분 문자열만으로 판정하지 않는다. 전체 표현을 규칙·사전에 대조한다.
- LLM은 의도·유사어·설명 보조만 허용. 모델·프롬프트·응답을 고정한다. LLM 단독 신규 해석이나 규칙 충돌은 검토필요.
- 표시용 게이트 값: 통과 1, 확정 실패 0, 불확실 NULL. 신뢰 확률이 아니다.

### B. 매장 적합성

- 출력: PASS·FAIL·UNKNOWN·CONFLICT.
- 공식 메뉴는 승인된 목록과 대조한다. from_menu 단독으로 공식 메뉴를 확정하지 않는다. 공식 5개 밖의 메뉴라는 이유로 미판매 판정을 내리지 않는다.
- 복합 키워드는 메뉴·방문 맥락·서비스·영업 조건의 모든 필수 조건이 충족돼야 PASS다. 24시간 설렁탕은 메뉴 근거만으로 통과하지 않는다.
- 리뷰는 자기 매장의 현재 경험을 지지하는 실제 구간을 확인한다. 수집 상태 success인 원본의 부정·타 매장·과거 언급이 아닌 독립 근거만 자동 확정 집계에 포함한다. NULL 상태는 따로 보존한다.
- review_count는 (source_type, source_review_id) 고유 수. weighted_mentions는 리뷰별 유효 time_weight 최댓값의 합. 최근 3개월 1.0, 3~6개월 0.8, 나머지 기간 0.5이며 기존 월 경계 함수를 따른다.
- 리뷰 수는 매장 간 비교 점수에 사용하지 않는다. 맥락 적합성은 파일럿 초기 검증 리뷰 3건 이상일 때만 자동 통과 가능하다. 메뉴 판매·서비스 제공은 단순 언급 수만으로 확정하지 않는다.
- 서비스·영업 조건은 이번 자동 적합성의 긍정 근거로 사용하지 않는다. 명확한 현재 사실 충돌은 보존한다. 불확실한 조건은 UNKNOWN이다.
- 자사 브랜드 전체 식별 근거가 부족하면 의심 카드를 외부 직접 경쟁점으로 강제 분류하지 않는다.

### C. 검색수요

검색광고는 매장별 관측이 아니라 고유 검색어 관측이다. 같은 키는 매장 간 공유하되 후보별 연결을 보존한다.

| 입력 상태 | 수치·분류 처리 |
|---|---|
| PC·모바일 비음수 정수 | total=PC+mobile, EXACT |
| 한 채널이라도 <10 | 해당 채널 정확값 NULL, 정수 구간 [0,9], CENSORED; 전체 구간은 채널 구간 합 |
| 정상 응답에서 키워드 미제공 | NOT_PROVIDED, 측정 불가로 제외 |
| 미조회 | MISSING, 검토필요 |
| API 실패 | FAILED, 검토필요 |
| 음수·bool·알 수 없는 문자열·필드 누락 | INVALID, 검토필요 |
| 정확한 합계 0 | ZERO_DEMAND, 제외 |

한 채널만 정확해도 그 숫자는 보존하되 전체 정확값은 NULL이다. <10을 0·5로 대체하지 않는다. 숫자 문자열을 암묵 변환하지 않는다. 같은 응답에서 같은 조회 키가 서로 다른 값을 가지면 DUPLICATE_RESPONSE_CONFLICT다.

현재 구현의 API 요청에는 날짜 구간이 없고 월간 값을 가져온다. 임의 기준일의 최근 30일 실측이라고 표기하지 않는다. 공급자의 기간 정의가 검증되지 않으면 기간 유형 UNVERIFIED, 자동 수요 게이트 UNKNOWN이다. 검증된 제공 월간 값은 PROVIDER_MONTHLY로 명시하며 임의 일별 실측으로 바꾸지 않는다. 정확한 기간을 제공하지 않는 API의 시작·종료일은 NULL로 남긴다. DataLab 일별 배분 추정치는 사용하지 않는다.

후보 내 분위수는 P(x)=(x보다 작은 관측 수+0.5×동일 관측 수)/N이다. 매장별 고정 후보 중 의도·적합성 통과 및 EXACT 검색량 보유 집합에서 검색광고 키당 한 번 센다. 수집 대상을 축소하기 전에 모집단을 고정한다. N<5 또는 모두 동점이면 percentile은 NULL, POPULATION_UNINFORMATIVE다. 모집단 크기·구성원·제외 사유를 저장한다. 매장 내 분위수는 매장 간 우열 비교에 쓰지 않는다. 공통 비교 분위수는 5개 매장 모두 저비용 자격을 통과한 공통 키 집합에서 별도로 계산하며 동일한 공식·최소 크기 조건을 적용한다.

### D. 직접 경쟁점 점유율

기준은 자연순위 상위 10개다. 광고는 분자·분모에서 제외하고 별도 개수를 제공한다. SUCCESS이고 자연순위가 1부터 연속이며 최소 10개 또는 확인된 결과 종료를 만족해야 한다. 광고 포함 20카드 SUCCESS를 자연 20위 확인으로 보지 않는다. NO_RESULT의 분모 0을 경쟁점 점유율 0으로 만들지 않는다.

카드별 유형은 DIRECT·INDIRECT·NON_COMPETITOR·OWN_BRAND·UNKNOWN이다. DIRECT는 방문형 외식 업장, 자사 외부, 후보 핵심 음식·목적에 일치하는 버전 있는 업종/확인 규칙을 모두 만족한다. 넓은 '한식' 분류나 상호명에 대한 LLM 추정만으로 DIRECT를 확정하지 않는다. 승인된 세부 업종 규칙에 없으면 UNKNOWN이다.

direct_share=direct_count/organic_count. 자사 브랜드 카드는 전체 검색면 분모에 남고 분자에는 들어가지 않는다. 미확정 카드가 있으면 확정 비율은 NULL, 참고 구간은 [direct_count/N,(direct_count+unknown_count)/N]이다. 자연 카드 place_id 중복은 조용히 제거하지 않고 품질 오류다. PARTIAL·실패·깊이 부족·미확정 카드가 있으면 자동 시장 분류를 금지한다.

### E. keywordList 동일 의도 포함 비율

전문 최적화 비율은 keywordList에 후보 의도가 포함되는 관측 대리지표이며 실제 전문성이나 최적화 성과를 증명하지 않는다. 분모는 D의 확정 직접 경쟁점이다.

- exact_count: 평가 정규화 후 후보 전체 표현과 완전 일치하는 매장 수.
- synonym_only_count: 완전 일치는 없고 승인된 동일 의도 사전으로 일치하는 매장 수.
- exact_ratio=exact_count/direct_count.
- intent_ratio=(exact_count+synonym_only_count)/direct_count.
- 같은 매장은 한 번만 센다. 단순 부분 문자열이나 공통 메뉴 단어는 동의어가 아니다.
- 일치 근거에 Place ID, 확인 snapshot, effective snapshot, keyword_order, 원문, 일치 유형, 사전 규칙 ID를 저장한다.
- SUCCESS/EMPTY 최신 유효 확인을 사용한다. EMPTY는 정상 빈 목록이며 불일치다. 누락·실패·STALE은 불일치로 변환하지 않는다.
- 직접 경쟁점 중 한 곳이라도 필수 목록이 없으면 비율은 NULL. coverage_count/direct_count를 별도 제공한다.
- direct_count=0이면 비율 NULL, NOT_APPLICABLE이다. D 전체 분류가 완전할 때만 E 게이트를 적용 대상 없음으로 통과시킨다.

### F. 자사 현재 노출

카드 place_id와 target_place_id 정확 일치만 주 근거다. 이름 매칭은 참고 또는 검토 사유다.

| 상태 | 조건 |
|---|---|
| OBSERVED | 유효 목록에서 실제 자연순위 확인 |
| NOT_IN_TOP20 | 자연순위 20개 확인, 대상 없음 |
| NOT_OBSERVED_IN_COMPLETE_LIST | 20개 미만이지만 실제 종료 확인, 대상 없음 |
| DEPTH_INSUFFICIENT | 대상 없음, 깊이 부족, 종료 미확인 |
| UNKNOWN | 실패·누락·식별 충돌 |

미노출은 순위 NULL이며 21·999·0으로 대체하지 않는다. 확인한 1~20위의 보조 점수는 (21-rank)/20이다. 다른 상태는 NULL이다. 동일 의도 유사 키워드의 노출은 설명용으로만 남기며 필수 결측이나 진입 게이트를 대체하지 않는다. 빈집의 자동 진입 근거는 OBSERVED만 허용한다. 경쟁은 관측 완료된 미노출 상태도 허용하되 DEPTH_INSUFFICIENT/UNKNOWN은 금지한다.

## 4. 분류·품질·교정 설정

가중합 총점은 만들지 않는다. 검색량·비율·게이트를 분리한다. 한 항목의 높은 점수가 다른 항목 실패를 상쇄하지 않는다.

판정 순서:

1. 식별 오류·매장 운영 사실 충돌·규칙 충돌이면 REVIEW_REQUIRED.
2. 확정 NON_DINING, 확정 무관 업종 또는 명백한 적합성 FAIL이면 EXCLUDED. 후속 수집은 NOT_APPLICABLE이다.
3. 정상 검색량 NOT_PROVIDED 또는 정확한 0이면 EXCLUDED.
4. 의도·적합성 불확실, 필요한 입력 누락·실패·STALE·기간/시간대 미확인이면 REVIEW_REQUIRED.
5. 공통 자격과 빈집 조건을 모두 만족하면 VACANT.
6. 공통 자격과 경쟁 조건을 모두 만족하면 COMPETITIVE.
7. 나머지는 REVIEW_REQUIRED. 규칙이 동시에 충족되면 RULE_CONFLICT이며 REVIEW_REQUIRED.

공통 자격은 검색량 측정 가능·기간 검증·DINING·적합성 PASS·사실 충돌 없음·모든 필수 관측 정상이다. VACANT는 수요 존재, 직접 경쟁 비율 낮음, keywordList 의도 비율 낮음 또는 적법한 적용 대상 없음, 자사 진입 OBSERVED를 요구한다. COMPETITIVE는 수요 높음, 직접 경쟁 비율 또는 keywordList 의도 비율 높음을 요구한다. 둘 모두 F 관측 완전성이 필요하다.

| 파일럿 설정 | 초깃값; 확정 성능 기준 아님 |
|---|---|
| 수요 존재 | EXACT total >=10 |
| 수요 높음 | EXACT total >=100 AND 매장 내 percentile >=0.75 |
| 직접 경쟁 낮음 / 높음 | <=0.30 / >=0.60 |
| keywordList 의도 비율 낮음 / 높음 | <=0.20 / >=0.50 |
| 맥락 리뷰 충분성 | 검증된 독립 리뷰 >=3 |
| 검색량·순위·keywordList TTL | 각각 7일 |
| 순위↔keywordList 관측 시차 | 최대 7일 |
| 경쟁 집계 범위 | 자연 상위 10개 |
| 고비용 수집 예산 | 매장당 최대 20 query |

정확한 total 1~9는 LOW_DEMAND_THRESHOLD로 검토필요다. 비율의 상대 분위수는 같은 매장의 완비 수집 표본 내에서 같은 중간순위 공식으로 계산하되 파일럿 교정 참고값으로만 사용한다. 적은 표본에서 비율 상대 분위수까지 자동 분류 조건으로 추가하지 않는다. 결측을 모집단에 0으로 넣지 않는다.

주요 사유 코드는 STORE_OPERATION_CONFLICT, AMBIGUOUS_JOIN, TIMEZONE_UNVERIFIED, PERIOD_UNVERIFIED, INTENT_NON_DINING, INTENT_UNCERTAIN, FIT_CONFLICT, FIT_UNCERTAIN, DEMAND_NOT_PROVIDED, ZERO_DEMAND, LOW_DEMAND_THRESHOLD, RANK_PARTIAL, RANK_FAILED, DEPTH_INSUFFICIENT, COMPETITOR_UNKNOWN, KEYWORDLIST_MISSING, STALE, STALE_FALLBACK, RULE_CONFLICT, NOT_COLLECTED_BUDGET이다. 원천별 상태와 모든 사유를 배열로 보존하며 최종 분류 한 값으로 품질을 대체하지 않는다.

## 5. 저장 계약

후보 원본은 수정하지 않는다. 테이블은 생성 제안이며 이 문서로 실행하지 않는다. 검색량 저장소는 평가 전용 테이블과 분리하여 파일럿 전에 준비한다.

### 5.1 naver_keyword_search_volume_snapshot

| 컬럼 | 형식·의미 |
|---|---|
| volume_snapshot_id | bigint PK, 관측 식별자 |
| collection_run_id | uniqueidentifier, 동일 수집 실행 |
| request_keyword / response_keyword | nvarchar(255), 응답 표현은 미제공 시 NULL |
| searchad_lookup_key | nvarchar(255), 버전 고정 조회 키 |
| provider | varchar(30), NAVER_SEARCHAD |
| fetched_at | datetimeoffset(3), 실제 응답/실패 시각 |
| period_type | varchar(30), PROVIDER_MONTHLY·EXACT_30D·UNVERIFIED |
| period_start / period_end | date NULL, 제공자가 보장할 때만 입력 |
| period_definition | nvarchar(1000), 기간 근거·명세 식별 포함 |
| raw_pc / raw_mobile | nvarchar(100) NULL, 공급자 원문; 원문 JSON에서 타입 보존 |
| pc_count / mobile_count / total_count | bigint NULL, 정확한 비음수 정수만 |
| observation_status | varchar(30), EXACT·CENSORED·NOT_PROVIDED·FAILED·INVALID |
| response_json | nvarchar(max) NULL, 재현에 필요한 해당 응답 항목과 타입; 인증정보 제외 |
| response_hash | char(64) NULL, 고정 직렬화 UTF-8 SHA-256 |
| failure_code | varchar(50) NULL, 실패 구분; 인증정보 포함 오류 원문 금지 |
| parser_version | varchar(50), 정규화·숫자 파서 버전 |

유일키는 (collection_run_id, provider, searchad_lookup_key)다. 여러 API 시도 중 실행의 최종 결과만 저장하고 재수집은 새 실행으로 남긴다. 중복 응답 충돌은 INVALID다. 응답 타입은 JSON으로 보존하며 구간은 raw 값과 parser_version으로 재현하고 평가 근거에도 저장한다. 정확한 합계는 두 채널 모두 정확할 때만 허용한다. 공급자 미제공 날짜를 fetched_at-29로 만들어 저장하지 않는다. 날짜 없는 PROVIDER_MONTHLY를 EXACT_30D로 바꾸지 않는다.

### 5.2 평가 실행·결과

| 테이블 | 최소 컬럼 |
|---|---|
| naver_keyword_evaluation_run | evaluation_run_id uniqueidentifier PK; as_of_at datetimeoffset(3); calculation_version varchar(50); input_manifest_json nvarchar(max); rules_json nvarchar(max); input_hash char(64); created_at datetimeoffset(3) |
| naver_keyword_evaluation_result | evaluation_result_id bigint PK; evaluation_run_id FK; candidate_id bigint FK; target_place_id varchar(50); normalized_keyword nvarchar(255); volume_snapshot_id bigint NULL FK; rank_snapshot_id bigint NULL FK; raw_scores_json·normalized_scores_json·gate_results_json·reason_codes_json·quality_json nvarchar(max); final_class varchar(20); created_at datetimeoffset(3) |
| naver_keyword_evaluation_evidence | evaluation_result_id FK; evidence_no int; evidence_type varchar(30); source_refs_json·observed_values_json·decision_json nvarchar(max); PK(evaluation_result_id,evidence_no) |
| naver_keyword_evaluation_review | review_id bigint PK; evaluation_result_id FK; reviewer nvarchar(100); reviewed_at datetimeoffset(3); dining_intent·store_fit·competition_type·market_type·recommendation·confidence varchar(30); reason nvarchar(max) |

결과 유일키는 (evaluation_run_id,candidate_id)다. 재평가는 새 실행으로 저장하고 사람 판정도 덮어쓰지 않고 이력 행을 추가한다. 비교 시 reviewed_at DESC, review_id DESC를 쓰되 교정 실행에서 사용한 review_id 목록을 고정한다. 계산 버전은 실행 FK로 참조하므로 결과마다 중복 컬럼을 만들지 않는다. 평가 실행·결과·근거는 한 트랜잭션으로 저장하여 불완전 실행 노출을 막는다. 실패 로그는 실행 결과로 위장하지 않는다.

input_manifest_json의 필수 키는 schema_version, targets, candidate_runs, official_menus, source_timezones, normalization_versions, identity_mapping, collection_profile, demand_populations, source_manifest이다. source_manifest는 선택한 관측 ID와 실제 사용 값의 근거 해시를 포함한다. 대상별 원천 없음도 명시하여 입력 전체를 재현한다.

raw_scores_json의 고정 키:

- pc_count, mobile_count, total_count, pc_interval, mobile_interval, total_interval.
- review_count, weighted_mentions.
- organic_count, ad_count, direct_count, unknown_competitor_count, direct_share.
- keyword_exact_count, keyword_synonym_only_count, keyword_coverage_count, keyword_exact_ratio, keyword_intent_ratio.
- own_organic_rank, own_visibility_state.

normalized_scores_json은 demand_percentile, common_demand_percentile, intent_gate_value, fit_gate_value, own_rank_score, direct_share, keyword_exact_ratio, keyword_intent_ratio를 갖는다. 모든 적용 불가·결측은 NULL이다. gate_results_json은 A~F 각각의 값·상태·규칙 ID·근거 번호를 갖는다. JSON 형식은 schema_version으로 고정하고 알 수 없는 키·타입은 입력 검증에서 거절한다.

source_refs_json은 근거 종류별로 다음을 요구한다.

- CANDIDATE: candidate_id, candidate_run_id.
- REVIEW: review_term_id, source_type, source_review_id, candidate_run_id.
- VOLUME: volume_snapshot_id, parser_version.
- RANK: rank_run_id, task_key, snapshot_id; 카드 근거이면 raw_position.
- KEYWORDLIST: place_id, latest_attempt_snapshot_id, selected_check_snapshot_id, effective_snapshot_id; 일치 근거이면 keyword_order.
- RULE: rule_id, rule_version; LLM 보조이면 모델·프롬프트 해시·응답.

observed_values_json에 당시 사용한 값과 시각을 남긴다. ID만으로는 원천 수정 뒤 재현되지 않으므로 값도 동결한다. 원문 전체의 불필요한 복제는 피하고 실제 사용 구간·수치·판정 근거를 보존한다.

## 6. 저비용 축소와 수집 계약

명백한 비외식·무관 후보를 먼저 제외하고, 매장별 적합성 판정 후 남은 고유 검색광고 키의 검색량을 한 번씩 수집한다. 분위수 모집단을 먼저 동결한 뒤 고비용 수집을 줄인다. 수집하지 않은 후보도 결과를 남긴다.

매장당 최대 20개 초깃값은 다음 순서로 채운다. 중복 query는 첫 그룹에만 배정한다.

1. 공통 메뉴 중 수집 가능 후보 최대 5개.
2. 확정 의도·적합성·검색량 보유 후보를 total DESC, evaluation_keyword_key ASC, candidate_id ASC 순으로 최대 10개.
3. 그 외 확정 후보 중 수요 하한 100에 가까운 순(abs(total-100), keyword key, candidate_id)으로 최대 3개.
4. 불확실 후보 중 정확한 수요 보유 후보를 total DESC, keyword key, candidate_id 순으로 최대 2개. 수집해도 게이트 불확실성은 유지.

그룹이 미달하면 남은 예산을 2번 순서의 미선택 후보로 채운다. 대상 매장 운영 충돌이 있으면 자동 수집 대상에서 보류한다. 후보가 적으면 20개를 채우려고 무관 후보를 추가하지 않는다. 선택 그룹·순번·미선택 사유를 실행 입력에 보존한다.

평가 수집 프로필은 MOBILE, 좌표·geolocation override 없음, 거리 미사용, 동일 브라우저·로그인 정책으로 고정한다. 기존 CLI는 자동 좌표 해석을 하므로 그대로 호출하면 이 계약을 만족하지 않는다. 구현 시 기존 경로를 우회하는 명시적 프로필이 필요하다. IP 등 통제할 수 없는 영향은 수집 한계로 기록하며 좌표로 교정하지 않는다. 기존 좌표 기반 스냅샷은 참고 근거로만 분리하고 새 프로필 모집단과 합치지 않는다.

keywordList는 유효 순위의 필요한 직접 경쟁점 Place ID를 중복 제거해 수집한다. 직접 경쟁점 확인에 keywordList가 필요한 UNKNOWN 카드는 확인용으로 추가할 수 있으나 확정 전에는 비율에 포함하지 않는다. 755개 전체 또는 모든 검색 카드 전체에 상세 수집을 시작하지 않는다.

## 7. 사람 검토와 임계치 교정

검토 한 행은 evaluation_result_id에 대응한다. 자동값은 실행·후보·매장 식별, A/B 게이트와 리뷰 구간, PC·모바일·합계/구간, 분위수와 N, 자연 깊이·광고 수, 직접 수/분모·미확정 수, keywordList 일치 유형·커버리지·신선도, 자사 순위/상태, 자동 분류·사유·품질이다.

| 사람 필드 | 허용값 |
|---|---|
| 외식 의도 | 외식·혼합·비외식·불확실 |
| 매장 적합성 | 적합·부적합·불확실 |
| 경쟁 유형 | 직접·간접·혼합·없음·불확실 |
| 시장 유형 | 빈집·경쟁·제외·검토필요 |
| 추천 여부 | 추천·비추천·보류 |
| 확신도 | 높음·보통·낮음 |
| 사유 | 필수 자유문 |

추천 여부는 시장 유형과 독립이다. 첫 검토는 자동 분류를 숨겨 편향을 줄인다. 5개 매장의 상태를 모두 출력하되 수원파장점은 운영 충돌 해소 전 자동 판정 성능 분모에서 분리한다. 조정 표본과 확인 표본은 키워드 단위로 분리하여 같은 키워드가 매장을 바꾸어 양쪽에 들어가지 않게 한다. 분할 목록을 고정한다. 매장별 혼동행렬·빈집/경쟁 오판·전체 자동판정률·필수 데이터 완비 후보 내 정확도·품질 보류율을 각각 보고한다. 표본이 없는 항목은 0%가 아니라 산정 불가다.

## 8. 출력 예시와 불변 조건

snapshot 156의 설렁탕 3위는 관측 사실로 제공할 수 있지만, 현재 평가용 검색량 스냅샷·기간 검증·수집 프로필이 없으면 REVIEW_REQUIRED다. 수원파장점은 메뉴가 공식 목록과 일치해도 STORE_OPERATION_CONFLICT로 REVIEW_REQUIRED다. 다음 예시는 계산 계약을 설명하는 합성 사례이며 실제 파일럿 판정이 아니다.

| 합성 입력 | 기대 출력 |
|---|---|
| total=200, DINING/PASS, 모든 품질 정상, 직접 2/10, 의도 포함 0/2, 자사 3위 | VACANT |
| total=1000, percentile=.8, DINING/PASS, 모든 품질 정상, 직접 7/10, 의도 포함 4/7, 자사 미노출·목록 완결 | COMPETITIVE |
| 설렁탕 레시피, NON_DINING 확정, 순위 미수집 | EXCLUDED, 후속 수집 NOT_APPLICABLE |
| 최신 순위 PARTIAL, 과거 성공, 나머지 정상 | REVIEW_REQUIRED/RANK_PARTIAL |
| 직접 0/10, 카드 유형 전체 확정, 자사 관측, 수요·게이트 정상 | E는 NULL/NOT_APPLICABLE, VACANT 가능 |
| 직접 0/10이지만 UNKNOWN 카드 존재 | REVIEW_REQUIRED/COMPETITOR_UNKNOWN |

불변 조건: VACANT/COMPETITIVE 결과에 필수 MISSING·FAILED·STALE·CONFLICT가 존재하면 안 된다. 광고는 자연순위 비율에 들어가지 않는다. LLM 출력은 검색량·순위·비율 값을 만들지 않는다. 같은 입력 해시와 계산 버전은 실행 ID·생성시각 외 동일한 결과·근거를 만든다.

## 9. 구현 순서와 테스트 전략

1. 조사 결과와 입력 계약을 한국어 문서로 확정한다. 검색량 저장 계약과 연결 키·최신 선택을 포함한다.
2. `naver_keyword_search_volume_snapshot` DDL을 작성·검토한다. 원문·숫자·품질·기간·시각·응답 근거를 포함한다. 실행은 별도 승인을 받는다.
3. 승인된 검색량 테이블을 생성하고 읽기 전용 후보·리뷰·순위·keywordList 어댑터를 구현한다. 대상 매장·후보 실행 목록을 고정한다.
4. 식별·정규화·시간대·품질 검사를 구현한다. 수원파장점 운영 충돌을 자동 판정 보류한다.
5. 의도·적합성 저비용 평가 후 고유 검색어의 검색량을 수집·저장한다. 적재 승인 후 수행하며 매장 간 관측을 공유한다. 검색량 스냅샷 선택 뒤 평가 입력을 동결한다.
6. 검색수요·고정 후보군 분위수를 계산하고 매장별 고비용 수집 대상을 축소한다.
7. 좌표 없는 순위 수집 프로필과 필요한 keywordList 수집을 연결한다. 실패·PARTIAL·STALE을 보존한다.
8. 경쟁·keywordList·자사 노출 지표를 계산한다. 필수 데이터 부족은 자동 시장 판정을 금지한다.
9. 분류·평가 저장·사람 검토 출력을 구현한다. 평가 테이블도 DDL 검토·실행 승인 후 생성한다. 먼저 저장 없는 평가로 검증하고 승인된 적재를 수행한다.
10. 5개 매장 파일럿과 임계치 교정을 수행한다. 대표키워드 5개 자동 선정은 후속 과제다.

### 9.1 최소 테스트 사례

| 사례 | 기대 결과 |
|---|---|
| 01·1·001, 미등록 브랜드 대응 | 한촌 명시 대응만 연결; 미등록은 오류 |
| 전각·공백·대소문자 및 같은 검색광고 키 | 원천 차이 보존, 검색량 공유, 순위 자동 병합 금지 |
| 리뷰 run/place/brand/keyword 불일치 | 입력 오류·자동 판정 차단 |
| 같은 숫자 BLOG/VISITOR ID | 서로 다른 리뷰로 집계 |
| 부정·과거·타 매장·발췌 밖 일치·원본 상태 NULL | 검증 근거와 분리 |
| 원문 <10, PC=10/MOBILE=<10 | 전체 정확값 NULL, 전체 구간 [10,19] |
| 원문 숫자 0, bool, 음수, 숫자 문자열, 키워드 미제공 | 각각 정확 0·INVALID·INVALID·INVALID·NOT_PROVIDED |
| API 실패 뒤 과거 EXACT | 자동 분류 금지, 과거값은 참고 |
| 같은 수집 실행의 같은 키 충돌 | INVALID; 덮어쓰기 금지 |
| 여러 매장의 같은 검색어 | 동일 volume_snapshot_id 공유 가능 |
| 기준일만 임의 지정한 월간 값 | EXACT_30D로 저장·표기 금지 |
| 분위수 [10,10,20,30,40] | 10의 P=.2; N<5·전부 동점은 NULL |
| 수집 축소 전후 | 수요 모집단·분위수 불변 |
| 최신 순위 실패/PARTIAL + 과거 SUCCESS | REVIEW_REQUIRED |
| 광고 포함 20카드, 자연 14개 | 깊이 14; 미발견을 20위 밖으로 바꾸지 않음 |
| 정상 종료 8카드, 자연 8개, 대상 없음 | NOT_OBSERVED_IN_COMPLETE_LIST; NO_RESULT와 구분 |
| 자연 place 중복·광고 organic_rank 존재 | 무결성 오류 |
| 넓은 한식 카테고리·미등록 업종 규칙 | UNKNOWN, 비율 확정 금지 |
| 오래된 effective 내용, 최근 성공 재확인 | 최근 확인 기준 신선도 |
| keywordList EMPTY vs MISSING | 정상 불일치 vs NULL·검토필요 |
| 완전일치와 동의어 동시 존재 | 완전일치 1회, 동의어 추가 집계 없음 |
| 실패 후 effective 재사용 | STALE_FALLBACK |
| 기준시각 미래·TTL 경계·시간대 미확인 | 미래 제외·경계 이하 허용·미확인 보류 |
| 일부 매장만 완전한 서비스 자료 | 비교 점수 사용 금지 |
| 수원 운영 충돌 | 매장 전체 자동 시장 분류 보류 |
| 같은 입력·버전 재실행 | ID·생성시각 외 결과·근거 동일 |
| 평가 저장 중 실패 | 실행·결과·근거 전체 rollback |
| 검토 이력 추가 | 이전 판정 보존, 교정 참조 review_id 고정 |

### 9.2 검증 환경과 승인 경계

단위 테스트는 고정 합성 데이터로 수행한다. 실제 네이버 호출을 테스트 성공 조건으로 삼지 않는다. 스키마·트랜잭션·FK 테스트는 승인된 테스트 DB에서 수행한다. 운영 DB에는 승인 전 SELECT만 허용한다. 신규 구현의 기본 모드는 저장 없는 평가이며 네트워크 수집·적재는 명시적으로 분리한다. 기존 미추적 파일과 업무보고서를 테스트 준비 과정에서도 수정하지 않는다.

조사 당시 프로젝트 .venv에서 Python 실행 파일을 찾지 못했고 번들 Python에는 pymssql·dotenv가 없었다. 구현 단계에서 프로젝트 실행 환경을 먼저 확인해야 하며 문서만으로 테스트가 실행됐다고 간주하지 않는다. 연결 비밀 값은 문서·로그·테스트 fixture에 복제하지 않는다.

커밋이 필요하면 정확한 한국어 메시지와 대상 파일을 사용자에게 먼저 제시하고 승인받는다. 이 설계 승인은 커밋·push 또는 운영 DB 변경 승인이 아니다.

## 10. 현재 불필요하거나 고비용인 항목

755개 전체 선제 순위 수집, PC/MOBILE 이중 수집, 경쟁점 전체 메뉴·리뷰 상세 수집, 좌표·거리 보정, 운영팀 키워드·SKYPOS 매출, 일별 검색량 배분 재계산, 모든 후보 LLM 호출, 임의 종합 점수·진입 확률 예측은 수행하지 않는다. 최종 5개 자동 선정은 사람 검토와 임계치 교정 이후 별도 설계·구현한다.
