# Keyword Discovery Rank Collector Pilot Runbook

This runbook is for a controlled, manually reviewed pilot. Automated tests use
fixtures and fake browser/repository boundaries only; they never call Naver or a
database. Do not start the persistence pilot from CI or unattended automation.

## Environment and input preparation

1. Create `inputs/keyword_discovery_queries.xlsx` from
   `inputs/keyword_discovery_queries.example.xlsx`. Use the `검색작업` worksheet
   and its required columns. Keep the first pilot input to the scope stated below.
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

5. Use rollback mode for a pre-persistence exercise. It connects to the configured
   services, but converts repository commits to rollbacks, so record the run ID and
   terminal summary for review:

```powershell
.\.venv\Scripts\python.exe scripts\run_keyword_discovery_rank.py --input inputs\keyword_discovery_queries.xlsx --rollback-test
```

## Pilot datasets

Prepare two explicitly labelled worksheets/files; do not combine these with normal
production inputs.

- **Mobile pilot:** 5 stores × 5 keywords, all `MOBILE`, for exactly 25 unique
  tasks after deduplication. Each row must have a target store ID, target store
  name, location name, latitude, longitude, and source ID.
- **Device comparison:** select 10 of those query/location/store combinations and
  make one `MOBILE` and one `PC` task for each. This is a matched 10-query
  mobile/PC comparison (20 tasks), not a substitute for the 25-task mobile pilot.

Record the input file hash, reviewer, date, browser version, configured result
limit, and generated run ID before every live run. Keep workbook duplicates in the
input deliberately only when validating deduplication; remove accidental duplicates
from the pilot dataset.

## Manual review sheet

For every reviewed task/result, capture the following fields from the rendered DOM
and the collector output:

- run ID, task key, source ID, query, target store ID/name, location, device, and
  final URL;
- requested limit, observed result count, end-marker state, collection status, and
  collection message;
- raw position, organic rank, place ID, place name, category, ad flag, detail URL,
  distance, own-store flag, matched store ID, and match method;
- DOM screenshot/HTML evidence path, manual DOM value, reviewer decision, reviewer,
  timestamp, and discrepancy notes.

`PARTIAL` outcomes are evidence for diagnosis only. Exclude `PARTIAL` rows and
tasks from all scoring denominators; resolve or rerun them before expansion.

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
   collector with `--limit 5 --rollback-test`, and manually compare all five (or all
   end-confirmed short) rendered DOM cards with the review sheet. Confirm query,
   place ID, raw/organic rank, advertising, and own-store classification.
2. **Three queries, limit 20, rollback.** Use three independent mobile queries,
   execute with `--limit 20 --rollback-test`, and review all result cards and every
   end marker. Confirm no result from one task appears in another task's evidence or
   output.
3. **One store, five keywords, persistence.** After the two rollback stages pass,
   use five mobile keywords for one store and run without `--rollback-test`. This is
   the first permitted persistent write; do not expand to the 25-task pilot before
   its manual review passes.

For the persistence stage, inspect only the two new tables:

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

Confirm the reviewed snapshot/result rows are the only intended writes and that
`naver_place_rank` is unchanged. Use the approved database change/audit comparison
for that confirmation; do not run exploratory queries against unrelated tables.

## Expansion and closeout

Once the one-store persistence stage passes, run the 25-task mobile pilot, then the
matched 10-query mobile/PC comparison. Review the acceptance gates after each run;
do not batch scopes together. Archive only non-secret input metadata, run IDs,
review sheets, and evidence locations. Keep `.env`, browser profiles, screenshots
containing sensitive information, and generated artifacts out of Git.
