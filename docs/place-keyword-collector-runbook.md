# 플레이스 대표키워드 수집 운영 런북

## 사전 준비

저장소 루트의 환경 파일에 DB_SERVER, DB_PORT, KEYWORD_DISCOVERY_DB_DATABASE, KEYWORD_DISCOVERY_DB_USER, KEYWORD_DISCOVERY_DB_PASSWORD를 설정한다. 대상 DB는 naverDB다. 비밀번호, 브라우저 프로필, 원본 HTML·스크린샷은 출력하거나 커밋하지 않는다. 수집기는 DB 이름과 대상 테이블 19개 컬럼 계약을 확인한 뒤에만 브라우저를 연다.

SUCCESS와 EMPTY만 유효 스냅샷이다. 실패 상태는 직전 유효 결과를 보존한다. 같은 실패 상태와 메시지가 5회 연속이면 중단하고 진단한다.

## 1. DDL 생성·검증

다음 SQL을 순서대로 실행한다. 두 번째 SQL 성공 전에는 라이브 저장을 하지 않는다.

1. sql/place_keyword_collector/01_create_tables.sql
2. sql/place_keyword_collector/02_verify_tables.sql

검증값은 테이블 2개, 컬럼 19개, 제약조건 8개, 인덱스 7개다. 확정된 DDL 검증 결과도 2/19/8/7이다.

## 2. dry-run

기준 순위 실행 ID는 d32fbdc3-3af6-4d25-85e1-fe6970855df1이다. SUCCESS·PARTIAL 순위 스냅샷 중 광고 제외, 자연순위 상위 10위의 고유 Place ID 수를 먼저 확인한다.

\`\`\`sql
DECLARE @rank_run_id uniqueidentifier = 'd32fbdc3-3af6-4d25-85e1-fe6970855df1';
SELECT COUNT(DISTINCT r.place_id) AS unique_target_count
FROM dbo.naver_keyword_discovery_result AS r
JOIN dbo.naver_keyword_discovery_snapshot AS s ON s.snapshot_id = r.snapshot_id
WHERE s.run_id = @rank_run_id
  AND s.collect_status IN ('SUCCESS', 'PARTIAL')
  AND r.organic_rank IS NOT NULL AND r.organic_rank <= 10 AND r.is_ad = 0;
\`\`\`

\`\`\`powershell
.\.venv\Scripts\python.exe scripts\run_place_keyword_collector.py --rank-run-id d32fbdc3-3af6-4d25-85e1-fe6970855df1 --dry-run
\`\`\`

출력 targets가 SQL 수와 같아야 한다. 확정값은 74개다. dry-run은 브라우저 수집·저장을 하지 않는다.

## 3. 승인된 3개 Place ID 롤백 검증

아래 명령은 실 DB와 브라우저를 사용하지만 저장 커밋을 롤백한다. 세 승인 ID 외에는 실행하지 않는다.

\`\`\`powershell
.\.venv\Scripts\python.exe scripts\run_place_keyword_collector.py --rank-run-id d32fbdc3-3af6-4d25-85e1-fe6970855df1 --include-place-id 13149768 --include-place-id 12006259 --include-place-id 31076466 --force-refresh --rollback-test
\`\`\`

페이지 원문의 keywordList 배열과 raw_keyword 순서·문구를 비교한다. 출력 run_id에 대해 두 행 수는 모두 0이어야 한다.

\`\`\`sql
DECLARE @run_id uniqueidentifier = '<롤백 run_id>';
SELECT 'snapshot' AS item, COUNT(*) AS row_count FROM dbo.naver_place_keyword_snapshot WHERE run_id = @run_id
UNION ALL
SELECT 'result', COUNT(*) FROM dbo.naver_place_keyword_result AS r
JOIN dbo.naver_place_keyword_snapshot AS s ON s.snapshot_id = r.snapshot_id
WHERE s.run_id = @run_id;
\`\`\`

## 4. 3개 Place ID 라이브 저장

롤백 비교 통과 뒤 rollback-test만 제거한다.

\`\`\`powershell
.\.venv\Scripts\python.exe scripts\run_place_keyword_collector.py --rank-run-id d32fbdc3-3af6-4d25-85e1-fe6970855df1 --include-place-id 13149768 --include-place-id 12006259 --include-place-id 31076466 --force-refresh
\`\`\`

\`\`\`sql
DECLARE @run_id uniqueidentifier = '<라이브 run_id>';
SELECT snapshot_id, place_id, collect_status, keyword_count, content_hash, is_changed, effective_snapshot_id, source_url
FROM dbo.naver_place_keyword_snapshot WHERE run_id = @run_id ORDER BY place_id;
SELECT s.place_id, r.keyword_order, r.raw_keyword, r.normalized_keyword
FROM dbo.naver_place_keyword_result AS r
JOIN dbo.naver_place_keyword_snapshot AS s ON s.snapshot_id = r.snapshot_id
WHERE s.run_id = @run_id ORDER BY s.place_id, r.keyword_order;
\`\`\`

세 최종 스냅샷, 상태, 해시, 유효 링크를 확인한다. SUCCESS는 양수 키워드 수·동일한 결과 행 수·64자 해시를, EMPTY는 0개 키워드와 유효 링크를 가져야 한다.

## 5. 재사용과 강제 갱신

월간 기한 전 정상 실행은 reused=3, processed=0이어야 한다.

\`\`\`powershell
.\.venv\Scripts\python.exe scripts\run_place_keyword_collector.py --rank-run-id d32fbdc3-3af6-4d25-85e1-fe6970855df1 --include-place-id 13149768 --include-place-id 12006259 --include-place-id 31076466
\`\`\`

그 뒤 force-refresh를 붙여 실행한다. 동일 배열이면 is_changed=0, 새 키워드 결과 행은 0개, effective_snapshot_id는 이전 변경 버전을 가리켜야 한다.

\`\`\`sql
DECLARE @run_id uniqueidentifier = '<강제 갱신 run_id>';
SELECT s.place_id, s.is_changed, s.effective_snapshot_id, s.keyword_count, COUNT(r.snapshot_id) AS result_rows
FROM dbo.naver_place_keyword_snapshot AS s LEFT JOIN dbo.naver_place_keyword_result AS r ON r.snapshot_id = s.snapshot_id
WHERE s.run_id = @run_id GROUP BY s.place_id, s.is_changed, s.effective_snapshot_id, s.keyword_count ORDER BY s.place_id;
SELECT snapshot_id, keyword_order, COUNT(*) AS duplicate_count
FROM dbo.naver_place_keyword_result GROUP BY snapshot_id, keyword_order HAVING COUNT(*) > 1;
\`\`\`

두 번째 쿼리는 0행이어야 한다.

## 6. 전체 실행·재실행

\`\`\`powershell
.\.venv\Scripts\python.exe scripts\run_place_keyword_collector.py --rank-run-id d32fbdc3-3af6-4d25-85e1-fe6970855df1
\`\`\`

targets, processed, reused, SUCCESS, EMPTY, failed, aborted를 기록한다. 확정 전체 실행 a00c904c-91a6-4cf2-b1f5-ddb3d9ab4c3e은 캐시 3, 신규 71, SUCCESS 63, 키워드 309이다. keywordList:null 8건은 수정 후 재실행 7e7ef0d4-9353-4f48-9f69-d2411e75ed5a에서 EMPTY 8, 실패 0이었다. 최종 74개 모두 SUCCESS 또는 EMPTY 유효 스냅샷을 보유한다.

실패·미확정 대상만 include-place-id와 force-refresh로 제한 재실행한다. 정상 월간 재사용 대상에는 강제 갱신을 붙이지 않는다.

## 7. 진단 SQL

\`\`\`sql
DECLARE @run_id uniqueidentifier = '<진단 run_id>';
SELECT collect_status, collect_msg, COUNT(*) AS snapshot_count
FROM dbo.naver_place_keyword_snapshot WHERE run_id = @run_id
GROUP BY collect_status, collect_msg ORDER BY snapshot_count DESC;
SELECT s.place_id, s.collect_status, s.effective_snapshot_id, e.collect_status AS effective_status, e.keyword_count AS effective_keyword_count, s.collect_msg
FROM dbo.naver_place_keyword_snapshot AS s
LEFT JOIN dbo.naver_place_keyword_snapshot AS e ON e.snapshot_id = s.effective_snapshot_id
WHERE s.run_id = @run_id ORDER BY s.place_id;
\`\`\`

BLOCKED·LOAD_TIMEOUT은 네트워크·브라우저·차단 증거, PLACE_MISMATCH는 페이지 Place ID, PARSE_ERROR는 keywordList 구조를 확인한다. keywordList:null은 정상 EMPTY다. 증거 기본 경로 artifacts/place_keyword_collector/run_id/place_id는 Git에 추가하지 않는다.

## 8. 최종 확인·PR

\`\`\`powershell
.\.venv\Scripts\python.exe -m pytest -q
git diff --check
git status --short
git add -- docs/place-keyword-collector-runbook.md
git commit -m "docs: 대표키워드 수집 운영 절차 정리"
git push origin feat/place-keyword-collector
\`\`\`

커밋 대상은 런북뿐이다. 사용자 소유 .t, artifacts, inputs xlsx 미추적 파일은 추가·커밋하지 않는다. PR 제목·본문은 한국어로 작성하고 자동 테스트 수, 3개 Place ID 검증, 전체 실행 수치, DDL 2/19/8/7, PR #5가 병합되었거나 main에 포함되어야 한다는 선행 조건을 포함한다.
