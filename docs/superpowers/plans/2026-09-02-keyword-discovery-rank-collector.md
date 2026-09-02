# Keyword Discovery Rank Collector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an independent Naver Place collector that reads location-aware keyword tasks from Excel, collects up to 20 mobile-first results, validates every run, and atomically stores one snapshot plus its result rows in two new `naverDB` tables.

**Architecture:** Keep production code under `scripts/keyword_discovery_rank` with typed input, browser, parser, validator, matcher, and repository boundaries. Selenium supplies rendered mobile or PC DOM and deterministic failure evidence; pure functions parse and validate saved HTML so most behavior is testable without a live browser. The collector retries transient failures, persists only the final attempt, and continues task-by-task unless a fatal preflight failure or five identical consecutive failures occurs.

**Tech Stack:** Python 3.12, Selenium 4.46.0, Beautiful Soup 4.15.0, openpyxl 3.1.5, pymssql 2.3.13, python-dotenv 1.2.2, pytest 8.x, SQL Server

**Spec:** `docs/superpowers/specs/2026-09-02-keyword-discovery-rank-collector-design.md`

## Global Constraints

- Do not modify or import code from `C:\workspace\naver_crawling`.
- Do not modify the existing `naver_place_rank` table or collector.
- Create exactly two tables: `dbo.naver_keyword_discovery_snapshot` and `dbo.naver_keyword_discovery_result`.
- Initial input is `inputs/keyword_discovery_queries.xlsx`; later DB input implements the same `TaskSource.load() -> list[SearchTask]` contract.
- Default device is `MOBILE`; latitude and longitude are mandatory.
- Collect at most 20 visible cards, retaining ads in `raw_position` and excluding them from `organic_rank`.
- Parse rendered DOM only; structured JSON dual parsing is excluded.
- Retry transient failures twice after the first attempt and persist only the final attempt.
- Save failure HTML and screenshots only for `PARTIAL`, `LOAD_TIMEOUT`, `QUERY_MISMATCH`, `PARSER_ERROR`, and `SEARCH_ERROR`.
- Persist each task in its own transaction; never print or commit `.env` credential values.
- Bootstrap `.venv` with `C:\Users\user1\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe`; this host has no system `python` or `py -3.12` registration.

## File Map

```text
requirements-keyword-discovery.txt
.env.example
inputs/keyword_discovery_queries.example.xlsx
scripts/keyword_discovery_rank/{config,models,task_source,browser,parser,validation,matching,repository,collector,cli}.py
scripts/run_keyword_discovery_rank.py
sql/keyword_discovery_rank/{01_create_tables,02_verify_tables}.sql
tests/fixtures/keyword_discovery_rank/*.html
tests/test_keyword_discovery_*.py
docs/keyword-discovery-rank-pilot-runbook.md
```

---

### Task 1: Runtime Contract and Core Models

**Files:**
- Create: `requirements-keyword-discovery.txt`
- Create: `.env.example`
- Create: `scripts/keyword_discovery_rank/__init__.py`
- Create: `scripts/keyword_discovery_rank/models.py`
- Create: `scripts/keyword_discovery_rank/config.py`
- Create: `tests/test_keyword_discovery_models.py`
- Create: `tests/test_keyword_discovery_config.py`

**Interfaces:**
- Produces: `DeviceType`, `SourceType`, `CollectStatus`, `MatchMethod`, `SearchTask`, `SearchPage`, `ParsedResult`, `ParsedSearch`, `SearchSnapshot`, and `CollectorConfig`.
- `CollectorConfig.from_env(repo_root: Path) -> CollectorConfig` reads DB and collector settings.

Use these exact field contracts across later tasks:

```python
SearchTask(task_id, query, target_store_id, target_store_name, location_name,
           latitude, longitude, source_type, source_id, device_type=DeviceType.MOBILE)
SearchPage(final_url, html, state, observed_result_count, result_end_reached)
ParsedResult(raw_position, organic_rank, place_id, place_name, category, is_ad,
             detail_url, distance_text, is_own_store=False,
             matched_store_id=None, match_method=MatchMethod.NONE)
ParsedSearch(results, observed_result_count, result_end_reached)
```

`CollectStatus` values are exactly `SUCCESS`, `NO_RESULT`, `PARTIAL`, `LOAD_TIMEOUT`, `QUERY_MISMATCH`, `PARSER_ERROR`, `SEARCH_ERROR`, and `VALIDATION_ERROR`. `MatchMethod` values are exactly `PLACE_ID`, `MANUAL_MAPPING`, `EXACT_NAME`, `NORMALIZED_NAME`, and `NONE`.

- [ ] **Step 1: Write failing model and configuration tests**

Test immutable dataclasses, enum values, redacted configuration output, mobile default, result limit 20, retry count 2, failure limit 5, and missing DB keys.

```python
def test_search_task_defaults_to_mobile():
    task = SearchTask("row-2", "선릉역 국밥", "S1", "육수당 선릉점", "선릉점", 37.5048, 127.0489, SourceType.EXCEL, "2")
    assert task.device_type is DeviceType.MOBILE

def test_config_repr_redacts_password(tmp_path: Path):
    config = CollectorConfig.from_env(write_env(tmp_path, DB_PASSWORD="top-secret"))
    assert "top-secret" not in repr(config)
    assert (config.result_limit, config.max_retries) == (20, 2)
```

- [ ] **Step 2: Run tests and verify RED**

Run `.\.venv\Scripts\python.exe -m pytest -q tests/test_keyword_discovery_models.py tests/test_keyword_discovery_config.py`.
Expected: package import failure.

- [ ] **Step 3: Implement contracts and pin dependencies**

Pin `beautifulsoup4==4.15.0`, `openpyxl==3.1.5`, `pymssql==2.3.13`, `python-dotenv==1.2.2`, `selenium==4.46.0`, and `pytest>=8.0,<9`. Make boundary dataclasses `frozen=True`. Add secret-free `.env.example` keys for existing DB fields plus `KEYWORD_DISCOVERY_HEADLESS`, `KEYWORD_DISCOVERY_TIMEOUT_SECONDS`, and `KEYWORD_DISCOVERY_ARTIFACT_ROOT`.

- [ ] **Step 4: Run the Step 2 command and verify GREEN**

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add -- requirements-keyword-discovery.txt .env.example scripts/keyword_discovery_rank/__init__.py scripts/keyword_discovery_rank/models.py scripts/keyword_discovery_rank/config.py tests/test_keyword_discovery_models.py tests/test_keyword_discovery_config.py
git commit -m "feat: define keyword discovery collector contracts"
```

---

### Task 2: Excel and Database Task Sources

**Files:**
- Create: `scripts/keyword_discovery_rank/task_source.py`
- Create: `tests/test_keyword_discovery_task_source.py`
- Create: `inputs/keyword_discovery_queries.example.xlsx`
- Modify: `.gitignore`

**Interfaces:**
- Produces: `TaskSource.load() -> list[SearchTask]`, `ExcelTaskSource`, `DatabaseTaskSource`, `normalize_query(str) -> str`, and `build_task_key(SearchTask) -> str`.

- [ ] **Step 1: Write failing Excel tests**

Use headers `검색어`, `기준매장ID`, `기준매장명`, `조회위치명`, `위도`, `경도`, `기기`, `소스ID`. Assert mobile default, `excel-row-{row}` source ID, query normalization, row-numbered validation errors, coordinate bounds, and first-row retention for duplicate task keys.

```python
assert build_task_key(task) == hashlib.sha256(
    "선릉역 국밥|S1|37.5048000|127.0489000|MOBILE".encode("utf-8")
).hexdigest()
```

- [ ] **Step 2: Write a failing DB adapter contract test**

Use a fake cursor returning equivalent fields and assert `SourceType.DATABASE`; downstream code must not know DB column names.

- [ ] **Step 3: Run tests and verify RED**

Run `.\.venv\Scripts\python.exe -m pytest -q tests/test_keyword_discovery_task_source.py`.

- [ ] **Step 4: Implement both adapters and example workbook**

Use `openpyxl.load_workbook(..., read_only=True, data_only=True)`. Accumulate all row errors into `InputValidationError`. Ignore `inputs/keyword_discovery_queries.xlsx`; commit only the clearly labeled example workbook.

- [ ] **Step 5: Run Step 3 and verify GREEN**

- [ ] **Step 6: Commit**

```powershell
git add -- scripts/keyword_discovery_rank/task_source.py tests/test_keyword_discovery_task_source.py inputs/keyword_discovery_queries.example.xlsx .gitignore
git commit -m "feat: add keyword discovery task sources"
```

---

### Task 3: Search-State Detection and Browser Execution

**Files:**
- Create: `scripts/keyword_discovery_rank/browser.py`
- Create: `tests/test_keyword_discovery_browser.py`
- Create: `tests/fixtures/keyword_discovery_rank/{results,no_result,error}.html`

**Interfaces:**
- Produces: `query_matches_url`, `detect_page_state`, `BrowserSession.search`, `BrowserSession.save_evidence`, and `BrowserFactory.create(device_type, latitude, longitude)`.

- [ ] **Step 1: Write failing pure state tests**

Cover decoded Korean `query` and `searchText`, stale-result rejection, results, explicit no-result, error text, and undecided loading. URL-query match must precede terminal DOM acceptance.

- [ ] **Step 2: Write failing factory tests with a fake WebDriver**

Assert mobile UA and `390x844`, PC `1440x1000`, and CDP geolocation:

```python
driver.execute_cdp_cmd("Emulation.setGeolocationOverride", {
    "latitude": task.latitude, "longitude": task.longitude, "accuracy": 100
})
```

- [ ] **Step 3: Run tests and verify RED**

Run `.\.venv\Scripts\python.exe -m pytest -q tests/test_keyword_discovery_browser.py`.

- [ ] **Step 4: Implement waits and result expansion**

Build URLs with `urllib.parse.urlencode`. Scroll until 20 cards, confirmed end marker, or timeout. Raise typed `QueryMismatch`, `SearchStateTimeout`, `SearchPageError`, and `BrowserSessionError` carrying last URL and HTML.

- [ ] **Step 5: Run Step 3 and verify GREEN**

- [ ] **Step 6: Commit**

```powershell
git add -- scripts/keyword_discovery_rank/browser.py tests/test_keyword_discovery_browser.py tests/fixtures/keyword_discovery_rank
git commit -m "feat: add mobile-first Naver search executor"
```

---

### Task 4: DOM Parser and Result Validation

**Files:**
- Create: `scripts/keyword_discovery_rank/parser.py`
- Create: `scripts/keyword_discovery_rank/validation.py`
- Create: `tests/test_keyword_discovery_parser.py`
- Create: `tests/test_keyword_discovery_validation.py`
- Create: `tests/fixtures/keyword_discovery_rank/{mixed_results,partial_results}.html`

**Interfaces:**
- `DomResultParser.parse(SearchPage) -> ParsedSearch`.
- `ResultValidator.validate(ParsedSearch, requested_limit: int) -> ValidationOutcome`.

- [ ] **Step 1: Write failing parser tests**

Fixture: three organic results and one ad. Assert raw positions `[1,2,3,4]`, organic ranks `[1,None,2,3]`, place IDs, names, category, URL, and distance.

- [ ] **Step 2: Write failing invariant tests**

Cover discontinuous ranks, ads with ranks, missing ID/name, URL-ID mismatch, duplicate rank, short results with/without end marker, and partial cards.

- [ ] **Step 3: Run tests and verify RED**

Run `.\.venv\Scripts\python.exe -m pytest -q tests/test_keyword_discovery_parser.py tests/test_keyword_discovery_validation.py`.

- [ ] **Step 4: Implement parser and validator**

Keep selectors in `parser.py`, set `PARSER_VERSION = "dom-v1"`, allow absent optional category/distance, and preserve rendered `observed_result_count` even when fewer rows are accepted. Status must be `SUCCESS`, `NO_RESULT`, `PARTIAL`, or `VALIDATION_ERROR` as applicable.

- [ ] **Step 5: Run Step 3 and verify GREEN**

- [ ] **Step 6: Commit**

```powershell
git add -- scripts/keyword_discovery_rank/parser.py scripts/keyword_discovery_rank/validation.py tests/test_keyword_discovery_parser.py tests/test_keyword_discovery_validation.py tests/fixtures/keyword_discovery_rank
git commit -m "feat: parse and validate Naver Place result cards"
```

---

### Task 5: Own-Store Matching

**Files:**
- Create: `scripts/keyword_discovery_rank/matching.py`
- Create: `tests/test_keyword_discovery_matching.py`

**Interfaces:**
- `OwnStoreMatcher.match(result) -> MatchDecision(is_own_store, matched_store_id, match_method)`.

- [ ] **Step 1: Write failing precedence and false-positive tests**

Assert `PLACE_ID > MANUAL_MAPPING > EXACT_NAME > NORMALIZED_NAME > NONE`, punctuation/spacing normalization, and near-name competitors remaining `NONE`. Containment alone is not a match.

- [ ] **Step 2: Run tests and verify RED**

Run `.\.venv\Scripts\python.exe -m pytest -q tests/test_keyword_discovery_matching.py`.

- [ ] **Step 3: Implement conservative matching**

Normalize with Unicode NFKC, lowercase Latin, remove whitespace/punctuation, permit normalized equality only, and keep manual mappings keyed by Naver place ID.

- [ ] **Step 4: Run Step 2 and verify GREEN**

- [ ] **Step 5: Commit**

```powershell
git add -- scripts/keyword_discovery_rank/matching.py tests/test_keyword_discovery_matching.py
git commit -m "feat: identify own stores in discovery results"
```

---

### Task 6: SQL Schema and Transactional Repository

**Files:**
- Create: `sql/keyword_discovery_rank/01_create_tables.sql`
- Create: `sql/keyword_discovery_rank/02_verify_tables.sql`
- Create: `scripts/keyword_discovery_rank/repository.py`
- Create: `tests/test_keyword_discovery_schema_sql.py`
- Create: `tests/test_keyword_discovery_repository.py`

**Interfaces:**
- Produces: `SnapshotRepository.save(snapshot, results) -> int`, `ping()`, and `close()`.

- [ ] **Step 1: Write failing static schema tests**

Assert exactly two approved tables, every approved column/type, FK, `(run_id, task_key)` uniqueness, checks, filtered unique rank index, and seven lookup indexes. Assert `attempt_count`, `actual_result_count`, `created_at`, `raw_html_path`, and `screenshot_path` are absent.

- [ ] **Step 2: Write failing fake-connection tests**

Assert snapshot before bulk results, reused identity, one commit, rollback on result failure, no rows for `NO_RESULT`, and duplicate-key conversion to `RepositoryError`.

- [ ] **Step 3: Run tests and verify RED**

Run `.\.venv\Scripts\python.exe -m pytest -q tests/test_keyword_discovery_schema_sql.py tests/test_keyword_discovery_repository.py`.

- [ ] **Step 4: Implement idempotent DDL and repository**

Guard objects through `OBJECT_ID` and `sys.indexes`; use explicit columns and `OUTPUT INSERTED.snapshot_id`; verify inserted counts before commit. Never reference `naver_place_rank` except in a negative static test.

- [ ] **Step 5: Run Step 3 and verify GREEN**

- [ ] **Step 6: Run DB rollback acceptance**

Confirm `DB_DATABASE` resolves to `naverDB`; in one explicit transaction insert a synthetic snapshot and two results, query them, then roll back. Verify zero synthetic rows afterward.

- [ ] **Step 7: Commit**

```powershell
git add -- sql/keyword_discovery_rank scripts/keyword_discovery_rank/repository.py tests/test_keyword_discovery_schema_sql.py tests/test_keyword_discovery_repository.py
git commit -m "feat: persist keyword discovery snapshots"
```

---

### Task 7: Collector, Retry, Evidence, and CLI

**Files:**
- Create: `scripts/keyword_discovery_rank/collector.py`
- Create: `scripts/keyword_discovery_rank/cli.py`
- Create: `scripts/run_keyword_discovery_rank.py`
- Create: `tests/test_keyword_discovery_collector.py`
- Create: `tests/test_keyword_discovery_cli.py`
- Modify: `.gitignore`

**Interfaces:**
- `KeywordDiscoveryCollector.run(tasks, run_id) -> RunSummary`.
- CLI accepts `--input`, `--source excel|database`, `--device-override`, `--limit`, `--dry-run`, and `--rollback-test`.

- [ ] **Step 1: Write failing orchestration tests**

Cover immediate success, transient-then-success, three exhausted attempts, no retry for no-result/parser structure failure, browser recreation, final-only persistence, next-task continuation, and abort after five identical failures.

- [ ] **Step 2: Write failing evidence and CLI tests**

Assert `artifacts/keyword_discovery_rank/{run_id}/{task_key}/page.html` and `screenshot.png`; no evidence for `SUCCESS`, `NO_RESULT`, or `VALIDATION_ERROR`. `--dry-run` must validate/deduplicate without creating browser or DB clients.

- [ ] **Step 3: Run tests and verify RED**

Run `.\.venv\Scripts\python.exe -m pytest -q tests/test_keyword_discovery_collector.py tests/test_keyword_discovery_cli.py`.

- [ ] **Step 4: Implement status mapping and retry**

Retry only page load, timeout, mismatch, browser session, and interrupted loading. Persist final URL/HTML-derived counts/end flag/parser version and cap messages at 1,000 characters.

- [ ] **Step 5: Implement CLI and preflight**

Generate one UUID per run. Preflight input, DB, and Chrome. Ignore artifact root. DB source requires an explicit SQL query file. Print only run ID and aggregate counts.

- [ ] **Step 6: Run Step 3 and verify GREEN**

- [ ] **Step 7: Commit**

```powershell
git add -- scripts/keyword_discovery_rank/collector.py scripts/keyword_discovery_rank/cli.py scripts/run_keyword_discovery_rank.py tests/test_keyword_discovery_collector.py tests/test_keyword_discovery_cli.py .gitignore
git commit -m "feat: orchestrate keyword discovery collection"
```

---

### Task 8: End-to-End Verification and Pilot Runbook

**Files:**
- Modify: `README.md`
- Create: `docs/keyword-discovery-rank-pilot-runbook.md`
- Create: `tests/test_keyword_discovery_end_to_end.py`

**Interfaces:**
- Produces a repeatable 25-task mobile pilot and 10-query mobile/PC comparison procedure.

- [ ] **Step 1: Write a failing fixture-based end-to-end test**

Feed a temporary workbook through the real source/parser/validator/matcher and fake browser/repository. Assert one deduplicated task produces one snapshot and ordered result rows with correct own-store classification.

- [ ] **Step 2: Run test and verify RED or the exact integration gap**

Run `.\.venv\Scripts\python.exe -m pytest -q tests/test_keyword_discovery_end_to_end.py`.

- [ ] **Step 3: Complete wiring and documentation**

Document:

```powershell
& 'C:\Users\user1\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-keyword-discovery.txt
.\.venv\Scripts\python.exe scripts\run_keyword_discovery_rank.py --input inputs\keyword_discovery_queries.xlsx --dry-run
.\.venv\Scripts\python.exe scripts\run_keyword_discovery_rank.py --input inputs\keyword_discovery_queries.xlsx --rollback-test
```

The runbook defines 5 stores × 5 keywords, 10-query device comparison, manual review fields, exclusion of `PARTIAL` from scoring, and all numeric success criteria from the spec.

- [ ] **Step 4: Run the complete automated suite**

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.pytest_tmp\keyword_discovery_final tests/test_keyword_discovery_models.py tests/test_keyword_discovery_config.py tests/test_keyword_discovery_task_source.py tests/test_keyword_discovery_browser.py tests/test_keyword_discovery_parser.py tests/test_keyword_discovery_validation.py tests/test_keyword_discovery_matching.py tests/test_keyword_discovery_schema_sql.py tests/test_keyword_discovery_repository.py tests/test_keyword_discovery_collector.py tests/test_keyword_discovery_cli.py tests/test_keyword_discovery_end_to_end.py
```

Expected: zero failures.

- [ ] **Step 5: Run live smoke tests in increasing scope**

Run one query/limit 5 with rollback and manual DOM comparison; then three queries/limit 20 with rollback; then one store/five keywords with persistence. Query only the two new tables and confirm `naver_place_rank` is unchanged.

- [ ] **Step 6: Evaluate the pilot**

Run 25 mobile and 10 matched PC tasks. Require field parsing ≥95%, place ID/rank accuracy 100%, own-store false positives 0, ad errors 0, cross-task impact 0, duplicate snapshots 0, and short-result end errors 0. Stop expansion if a hard criterion fails.

- [ ] **Step 7: Verify scope and secrets**

```powershell
git diff --check
git status --short
git grep -n -I -E "(DB_PASSWORD|NAVER_.*SECRET).*=.+" -- . ":(exclude).env" ":(exclude).env.example"
```

Expected: no whitespace errors, credentials, generated artifacts, or changes under `C:\workspace\naver_crawling`.

- [ ] **Step 8: Commit**

```powershell
git add -- README.md docs/keyword-discovery-rank-pilot-runbook.md tests/test_keyword_discovery_end_to_end.py
git commit -m "docs: add keyword discovery pilot runbook"
```
