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
