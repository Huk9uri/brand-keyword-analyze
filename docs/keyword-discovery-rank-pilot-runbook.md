# Keyword Discovery Rank Collector Pilot Runbook

This runbook is for a controlled, manually reviewed pilot. Automated tests use
fixtures and fake browser/repository boundaries only; they never call Naver or a
database. Do not start the persistence pilot from CI or unattended automation.

## Environment and input preparation

1. Prepare `inputs/keyword_discovery_queries.xlsx` by copying
   `inputs/keyword_discovery_queries.example.xlsx`, then populate and validate its
   `검색작업` worksheet. Populate the separate `자사매장` worksheet with one
   authoritative identity per task store: `매장ID`, `매장명`,
   `네이버플레이스ID`, and optional `수동매핑플레이스ID`. Repeat a consistent
   store row when more than one manual place-ID mapping is required. Every
   `검색작업.기준매장ID` must be present in `자사매장`; task rows remain separate
   from identity/mapping data. The generic workbook is an input-format reference; create
   the scope-specific workbooks named in [Pilot datasets](#pilot-datasets) for any
   actual pilot stage.
   현재 운영 경로는 좌표를 사용하지 않는다. `검색작업`의 `위도`와 `경도`가
   비어 있어도 정상 입력이며, 값이 존재하더라도 브라우저 위치로 전달하지
   않는다. 기존 좌표 컬럼과 캐시 테이블은 스키마 호환을 위해 유지한다.
2. Set the collector database and browser configuration in the local `.env` only.
   Do not copy credentials into the workbook, this runbook, terminals captured for
   review, or Git.
3. From the repository root, create the isolated environment and install the
   collector requirements:

```powershell
& 'C:\Users\user1\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-keyword-discovery.txt
```

4. Validate the input before any live browser or database operation:

```powershell
.\.venv\Scripts\python.exe scripts\run_keyword_discovery_rank.py --input inputs\keyword_discovery_queries.xlsx --dry-run
```

The current release supports Excel input only. `--source database` always exits
with a safe error before configuration, database, or Chrome construction. The
`DatabaseTaskSource` code remains a future adapter, but it must not be enabled
until a separately provisioned read-only source principal and configuration have
been approved.

For every non-dry run, the collector connects to the configured database and,
before Chrome is created, runs read-only checks that `DB_NAME()` is `naverDB` and
that the two approved ranking tables expose exactly the required 33-column signature.
When any task needs automatic coordinates, it also verifies the exact six-column
`dbo.naver_place_location` contract before requesting the Place page.
Target, schema, authentication, authorization, or connection failures stop the
whole run. Only task-local insert/data failures may be counted and followed by the
next task.

## Mandatory generic command reference (syntax only)

The two commands below are retained verbatim as the required generic command
reference. The first validates the prepared generic workbook without live browser
or database activity. The second is **syntax reference only**: do not execute it
during environment setup or any pilot stage, because rollback mode still connects to
live Naver and the configured database. The first live rollback execution is
permitted only in controlled live-smoke stage 1; later rollback scopes are
permitted only after their preceding gates pass. Stage 1 uses the canonical
one-query/limit-5 command.

```powershell
.\.venv\Scripts\python.exe scripts\run_keyword_discovery_rank.py --input inputs\keyword_discovery_queries.xlsx --dry-run
.\.venv\Scripts\python.exe scripts\run_keyword_discovery_rank.py --input inputs\keyword_discovery_queries.xlsx --rollback-test
```

## Pilot datasets

Create these canonical, separate workbooks. Do not combine them with normal
production inputs or run a larger scope before its preceding gate has passed.

| File | Required contents | Use |
| --- | --- | --- |
| `inputs/keyword_discovery_smoke_one_query_limit5.xlsx` | One unique `MOBILE` task | live-smoke stage 1 |
| `inputs/keyword_discovery_smoke_three_queries_limit20.xlsx` | Three unique `MOBILE` tasks | live-smoke stage 2 |
| `inputs/keyword_discovery_one_store_five_keywords.xlsx` | One store × five unique `MOBILE` keywords (five tasks) | live-smoke stage 3 |
| `inputs/keyword_discovery_mobile_pilot_25.xlsx` | Five stores × five unique `MOBILE` keywords (exactly 25 tasks after deduplication) | expanded mobile pilot |
| `inputs/keyword_discovery_mobile_pc_comparison_20.xlsx` | Ten matched query/location/store combinations, each once as `MOBILE` and once as `PC` (exactly 20 tasks after deduplication) | expanded device comparison |

Every row needs target store ID/name, location name, device, and source ID. Latitude
and longitude may both be blank for Place-ID resolution. For the comparison workbook,
keep each mobile/PC pair adjacent and
use the same query, target store, and location/coordinates; only `기기` differs.

Record the input file hash, reviewer, date, browser version, configured result
limit, and generated run ID before every live run. The CLI emits and flushes the
run ID immediately before the first search; copy that first line into the review
record before evaluating any task. Keep workbook duplicates in the
input deliberately only when validating deduplication; remove accidental duplicates
from the pilot dataset.

## Manual review sheet

Rollback mode produces a deterministic, non-DB review bundle for every final
task attempt, including successful and no-result tasks:

```text
artifacts/keyword_discovery_rank/{run_id}/{task_key}/page.html
artifacts/keyword_discovery_rank/{run_id}/{task_key}/screenshot.png
artifacts/keyword_discovery_rank/{run_id}/{task_key}/snapshot-results.json
```

`snapshot-results.json` contains the final snapshot fields, ordered result-card
rows, and redacted retry history. Use it as the structured side of the manual
comparison and use the final HTML/screenshot as the visual side. If any of the
three files is absent, unreadable, mismatched to the run/task key, or contains an
unredacted configured secret, fail the stage. Do not substitute rolled-back DB
rows for the structured export.

For every reviewed task/result, capture the following fields from the rendered DOM
and the collector output:

- run ID, task key, source ID, query, target store ID/name, location, device, and
  final URL;
- requested limit, observed result count, end-marker state, collection status, and
  collection message;
- raw position, organic rank, place ID, place name, category, ad flag, detail URL,
  optional Naver distance text, own-store flag, target-store flag, matched store ID,
  and match method;
- DOM screenshot/HTML evidence path, manual DOM value, reviewer decision, reviewer,
  timestamp, and discrepancy notes.

`PARTIAL` outcomes are evidence for diagnosis only. Exclude `PARTIAL` rows and
tasks from all scoring denominators; resolve or rerun them before expansion.

`distance_text`는 화면에 존재할 때 보존하는 원문 증거일 뿐이다. 카드 문구로
검색 기준 위치를 추정하거나, 이를 경쟁 강도·빈집 여부·자사 노출 가능성 점수에
반영하지 않는다. 거리 원문이 없더라도 정상 결과로 인정한다.

## Acceptance gates

All gates below are hard criteria. Compute rates only from non-`PARTIAL`, manually
reviewed tasks/results and preserve the numerator and denominator with the review
sheet.

| Gate | Required result |
| --- | --- |
| Field parsing | ≥95% correct across required reviewed fields |
| Place ID and rank accuracy | 100% |
| Own-store false positives | 0 |
| Advertisement errors | 0 |
| Cross-task impact | 0 |
| Duplicate snapshots | 0 |
| Short-result end errors | 0 |

Stop expansion immediately if any hard criterion fails. Preserve the input,
run ID, evidence, and review sheet; fix the cause, rerun in rollback mode, and
repeat the failed gate before proceeding to the next scope.

## Controlled live-smoke sequence

Perform each stage only after the previous stage meets every acceptance gate.

1. **One query, limit 5, rollback.** Build a one-row mobile workbook, execute the
   collector only with the canonical one-row input below. Rollback mode connects to
   live Naver and the configured database even though it rolls persistence back;
   it is not an environment-setup command and must not be run against any larger
   workbook. Manually compare all five (or all end-confirmed short) rendered DOM
   cards with the review sheet. Confirm query, place ID, raw/organic rank,
   advertising, and own-store classification using every card in
   `snapshot-results.json` against its final HTML and screenshot.

   ```powershell
   .\.venv\Scripts\python.exe scripts\run_keyword_discovery_rank.py --input inputs\keyword_discovery_smoke_one_query_limit5.xlsx --limit 5 --rollback-test
   ```

2. **Three queries, limit 20, rollback.** Use three independent mobile queries,
   execute the exact command below, and review all result cards and every end
   marker. Confirm each task has all three review-bundle files, retry history is
   redacted, and no result from one task appears in another task's evidence or
   output.

   ```powershell
   .\.venv\Scripts\python.exe scripts\run_keyword_discovery_rank.py --input inputs\keyword_discovery_smoke_three_queries_limit20.xlsx --limit 20 --rollback-test
   ```

3. **One store, five keywords, rollback rehearsal.** Run the canonical five-task
   input with `--rollback-test` and evaluate the same card-level and artifact gates
   before authorizing writes.

   ```powershell
   .\.venv\Scripts\python.exe scripts\run_keyword_discovery_rank.py --input inputs\keyword_discovery_one_store_five_keywords.xlsx --limit 20 --rollback-test
   ```

4. **One store, five keywords, persistence.** After all three rollback stages pass,
   use the canonical five-task input and run without `--rollback-test`. This is the
   first permitted persistent write; do not expand to the 25-task pilot before its
   manual review passes.

   ```powershell
   .\.venv\Scripts\python.exe scripts\run_keyword_discovery_rank.py --input inputs\keyword_discovery_one_store_five_keywords.xlsx --limit 20
   ```

No live command in this runbook was executed as part of implementation. The
following persistence-stage queries and commands are staged acceptance steps for
an authorized operator. For the persistence stage, inspect only the two new tables:

```sql
SELECT *
FROM dbo.naver_keyword_discovery_snapshot
WHERE run_id = @run_id
ORDER BY snapshot_id;

SELECT r.*
FROM dbo.naver_keyword_discovery_result AS r
JOIN dbo.naver_keyword_discovery_snapshot AS s ON s.snapshot_id = r.snapshot_id
WHERE s.run_id = @run_id
ORDER BY r.snapshot_id, r.raw_position;
```

Confirm the reviewed snapshot/result rows are the only intended writes. Do not
query `naver_place_rank` from the pilot account or use exploratory queries against
unrelated tables.

### Write-scope audit for `naver_place_rank`

The approved independent mechanism is the DBA-managed SQL Server Audit database
audit specification **`KeywordDiscoveryPilotWriteScopeAudit`**, configured to emit
`INSERT`, `UPDATE`, and `DELETE` events for `dbo.naver_place_rank` by the collector
database principal. SQL Server Audit supports database-level actions; see
[Microsoft's SQL Server Audit specification guide](https://learn.microsoft.com/en-us/sql/relational-databases/security/auditing/create-a-server-audit-and-database-audit-specification?view=sql-server-ver17).
The DBA must confirm that this specification is enabled before the first persistent
stage. If it is not enabled, stop: persistence is not authorized.

1. Before the one-store/five-keywords persistent command, the DBA exports the
   audit entries for the collector principal and `dbo.naver_place_rank`, records a
   UTC `audit_window_start`, the audit target/sequence identifier, and the export
   checksum in the review sheet.
2. Immediately after the command completes, the DBA exports the same audit stream
   from `audit_window_start` through a recorded UTC `audit_window_end`, again
   recording its target/sequence identifier and checksum. Attach both exports to
   the review record; the collector operator still queries only the two new tables
   shown above.
3. The pass condition for `naver_place_rank` and the cross-task-impact gate is zero
   `INSERT`, `UPDATE`, or `DELETE` audit events on `dbo.naver_place_rank` in that
   inclusive window, plus the reviewed snapshots/results matching the intended run
   ID. Any event, missing export, untrusted timestamp, or checksum mismatch fails
   the hard gate and stops expansion.

## Expansion and closeout

Once the one-store persistence stage passes, execute each expanded scope in rollback
mode first, complete its review, then repeat it without `--rollback-test` only when
the DBA write-scope audit is enabled and every hard gate has passed. Do not batch
scopes together.

```powershell
# 25-task mobile pilot rehearsal, then (only after review) its persistent run
.\.venv\Scripts\python.exe scripts\run_keyword_discovery_rank.py --input inputs\keyword_discovery_mobile_pilot_25.xlsx --limit 20 --rollback-test
.\.venv\Scripts\python.exe scripts\run_keyword_discovery_rank.py --input inputs\keyword_discovery_mobile_pilot_25.xlsx --limit 20

# 20-task matched mobile/PC comparison rehearsal, then (only after review) its persistent run
.\.venv\Scripts\python.exe scripts\run_keyword_discovery_rank.py --input inputs\keyword_discovery_mobile_pc_comparison_20.xlsx --limit 20 --rollback-test
.\.venv\Scripts\python.exe scripts\run_keyword_discovery_rank.py --input inputs\keyword_discovery_mobile_pc_comparison_20.xlsx --limit 20
```

Archive only non-secret input metadata, run IDs, review sheets, audit-export
checksums, and evidence locations. Keep `.env`, browser profiles, screenshots
containing sensitive information, audit contents, and generated artifacts out of
Git.
