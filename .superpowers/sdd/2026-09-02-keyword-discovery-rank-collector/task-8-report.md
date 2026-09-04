# Task 8 Report: End-to-End Verification and Pilot Runbook

## TDD record

The end-to-end test was written before any Task 8 production wiring. It exercises
the existing Task 1–7 public interfaces: temporary Excel workbook →
`ExcelTaskSource` → `KeywordDiscoveryCollector` → `DomResultParser` →
`ResultValidator` → `OwnStoreMatcher`, with fake browser and repository boundaries.

Initial test command:

```powershell
& '.\.venv\Scripts\python.exe' -m pytest tests/test_keyword_discovery_end_to_end.py -q
```

Initial result: exit code 0; `1 passed in 1.16s`. The test was green on its first
execution rather than RED because Tasks 1–7 already supplied the complete public
integration path. Exact integration gap: none. Consequently, no production wiring
was added; the Task 8 change is the integration test and the controlled runbook.

## Final automated verification

Command:

```powershell
$taskTests = Get-ChildItem -LiteralPath tests -Filter 'test_keyword_discovery_*.py' | ForEach-Object { $_.FullName }
& '.\.venv\Scripts\python.exe' -m pytest @taskTests -q
```

Result: exit code 0; `112 passed in 3.04s` (Task 1–8 keyword-discovery automated
suite, including the new end-to-end test). Pytest additionally emitted a non-fatal
atexit `PermissionError` while cleaning its shared Windows temp symlink; it did not
produce a test failure or change the process exit code.

## Changed files

- `tests/test_keyword_discovery_end_to_end.py` — fixture-based, offline end-to-end
  test. It proves a duplicate workbook input becomes one snapshot with ordered
  result rows and place-ID own-store classification.
- `docs/keyword-discovery-rank-pilot-runbook.md` — environment setup, exact
  commands, 25-task mobile and 10-query mobile/PC pilot scopes, review fields,
  scoring exclusions/gates, and controlled live-smoke expansion.
- `README.md` — links to the controlled pilot runbook and calls out dry-run first.

## Self-review and scope checks

- `git diff --check` completed with no whitespace errors.
- `git status --short` before staging listed only the three Task 8 files above;
  this report is added as the required Task 8 record.
- A changed-file secret scan for key/token/password assignment patterns returned no
  matches. No credentials or generated artifacts were added.
- No live Naver or database calls were made. No persistence pilot was run.
- No files under `C:\workspace\naver_crawling` were changed by this task.

## Commit

`docs: add keyword discovery pilot runbook`

## Concerns

The shared pytest temporary-directory cleanup warning is external to this worktree.
If it becomes a non-zero exit in another environment, configure pytest's base temp
directory to a writable location before treating it as a collector failure.

## Fix round 1: review follow-up

### RED / review gap

The review found that the generic rollback command was positioned before the gated
live-smoke sequence, the expanded pilot workbooks had no canonical names or exact
invocations, and the `naver_place_rank` protection check delegated to an unnamed
audit. These are human operational-document gaps, so no source-text unit test was
added: such a test would only assert prose rather than exercise collector behavior.

### GREEN / documentation correction

The runbook now limits the first rollback call to
`keyword_discovery_smoke_one_query_limit5.xlsx` with `--limit 5`, defines canonical
filenames and commands for all five pilot scopes (including the 25-task mobile and
20-task mobile/PC files), and names `KeywordDiscoveryPilotWriteScopeAudit` as the
DBA-managed SQL Server Audit mechanism. It defines the before/after audit exports,
UTC window, checksums, and zero-DML pass condition while reserving collector
database inspection for the two new tables.

### Verification

The initial Task 8 commit is `e02155d docs: add keyword discovery pilot runbook`.
The required changed-file secret scan command is:

```powershell
git show --format= HEAD | rg -n -i '(?:AKIA[0-9A-Z]{16}|(?:api[_-]?key|secret|password|token)\s*[=:]\s*[^\s#]{8,}|NAVER_[A-Z0-9_]+\s=)'
```

Its recorded result for `e02155d` was `secret_scan=no_matches`. For this follow-up,
the staged scan command was:

```powershell
git diff --cached | rg -n -i '(?:AKIA[0-9A-Z]{16}|(?:api[_-]?key|secret|password|token)\s*[=:]\s*[^\s#]{8,}|NAVER_[A-Z0-9_]+\s=)'
```

It returned `secret_scan=no_matches`; `git diff --cached --check` returned no
whitespace errors. The offline documentation-contract check verified the canonical
one-query, 25-task, and 20-task commands, audit specification name, UTC window,
and audit pass condition. The end-to-end fixture test then returned `1 passed in
2.57s` with the existing non-fatal shared-temp pytest cleanup warning. Final git
status is recorded after this follow-up commit.

Post-commit verification for `7830657 docs: clarify keyword discovery pilot
controls` ran the complete keyword-discovery suite and returned `112 passed in
5.38s` (exit code 0), with the same non-fatal shared-temp pytest cleanup warning.
`git show --check --format= HEAD` returned no whitespace errors;
`git status --short` returned no output (clean worktree); and the committed-tree
secret scan returned `secret_scan=no_matches`.

## Fix round 3: staged rollback wording

### RED / documentation assertion

The focused offline assertion for explicit staged rollback permission returned
`RED=missing staged rollback permission wording` (exit code 1) before the wording
change:

```powershell
$runbook = Get-Content -Raw 'docs/keyword-discovery-rank-pilot-runbook.md'
$expected = 'The first live rollback execution is permitted only in controlled live-smoke stage 1; later rollback scopes are permitted only after their preceding gates pass.'
if ($runbook.Contains($expected)) { throw 'Correct staged rollback wording unexpectedly already present' }
Write-Output 'RED=missing staged rollback permission wording'
exit 1
```

### GREEN / minimal correction

The syntax-reference warning now permits only the first live rollback execution in
stage 1 and explicitly permits later rollback scopes after their preceding gates
pass. The controlled smoke sequence itself is unchanged.

### Verification

The focused assertion returned
`GREEN=first rollback is stage-1-only and later rollback scopes remain gate-controlled`.
The end-to-end fixture test returned `1 passed in 1.05s`; the complete offline
keyword-discovery suite returned `112 passed in 4.02s` (exit code 0). Both pytest
invocations emitted the existing non-fatal shared-temp cleanup warning.
`git diff --check` returned no whitespace errors. No live Naver or database call
was made; final committed-tree checks are recorded after the follow-up commit.

Final committed-tree verification for `73bb88b docs: clarify staged rollback
controls`: `git show --check --format= HEAD` returned no whitespace errors,
`git status --short` returned no output (clean worktree), and the committed-tree
secret scan returned `secret_scan=no_matches`.

## Fix round 2: mandated generic command reference

### RED / documentation verification

Before the correction, this offline check returned
`RED=missing mandated generic rollback command reference` (exit code 1):

```powershell
$runbook = Get-Content -Raw 'docs/keyword-discovery-rank-pilot-runbook.md'
$genericRollback = '.\.venv\Scripts\python.exe scripts\run_keyword_discovery_rank.py --input inputs\keyword_discovery_queries.xlsx --rollback-test'
if ($runbook.Contains($genericRollback)) { throw 'Generic rollback reference unexpectedly already present' }
Write-Output 'RED=missing mandated generic rollback command reference'
exit 1
```

### GREEN / documentation correction

The runbook now defines preparation of `inputs/keyword_discovery_queries.xlsx` from
the canonical example and contains a dedicated syntax-only reference section with
both required generic commands verbatim. It expressly forbids execution of the
generic rollback command during setup or pilot work and keeps actual rollback
execution gated to the unchanged canonical one-query/limit-5 smoke command.

### Verification

The focused documentation check found both mandatory generic commands, confirmed
the generic rollback is syntax-only, and confirmed the canonical one-query/limit-5
rollback remains gated. The end-to-end fixture test returned `1 passed in 1.83s`.
The complete offline keyword-discovery suite returned `112 passed in 3.67s` (exit
code 0). Both pytest invocations emitted the existing non-fatal shared-temp cleanup
warning. `git diff --check` returned no whitespace errors. No live Naver or database
call was made; final committed-tree checks are recorded after the follow-up commit.

Final committed-tree verification for `15796da docs: restore keyword discovery
command reference`: `git show --check --format= HEAD` returned no whitespace errors,
`git status --short` returned no output (clean worktree), and the committed-tree
secret scan returned `secret_scan=no_matches`.
