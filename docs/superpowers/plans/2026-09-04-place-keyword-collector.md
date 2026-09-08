# Place Keyword Collector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collect the configured `keywordList` for unique top-10 organic Naver Place results, retain monthly check history, and persist keyword rows only when the array changes.

**Architecture:** Add an independent `scripts/place_keyword_collector` package whose rank source, refresh policy, browser, pure parser, change detector, repository, and orchestrator communicate through immutable dataclasses. Every check creates a snapshot, while result rows belong only to changed `SUCCESS` or `EMPTY` versions and unchanged or failed checks point to the last valid version through `effective_snapshot_id`.

**Tech Stack:** Python 3.12, Selenium 4.46.0, Beautiful Soup 4.15.0, pymssql 2.3.13, python-dotenv 1.2.2, pytest 8.x, SQL Server

**Spec:** `docs/superpowers/specs/2026-09-04-place-keyword-collector-design.md`

## Global Constraints

- Work on `feat/place-keyword-collector`; branch names must use `feat/`, `fix/`, or `docs/` and never `codex/`.
- Tell the user the exact Korean commit message before every commit.
- Keep this collector independent from candidate extraction and keyword evaluation logic.
- Use `https://m.place.naver.com/restaurant/{place_id}/home`; do not prepend `view-source:`.
- Default input is a rank collector `run_id`; select organic, non-ad results with rank 1-10 and deduplicate by Place ID.
- Default refresh policy is `MONTHLY`; support `WEEKLY` and force refresh without changing persistence contracts.
- Preserve raw keyword text and array order; normalization is limited to whitespace, Unicode NFKC, and English casefold.
- Do not merge synonyms or calculate professional-optimization ratios in this module.
- Retry `BLOCKED` and `LOAD_TIMEOUT` up to three total attempts; do not retry `PARSE_ERROR` or `PLACE_MISMATCH` in the same run.
- Stop after five identical consecutive failures.
- Do not delete or overwrite the previous valid keyword version after a failed check.
- Never print, persist in evidence, or commit database credentials.
- Preserve unrelated untracked spreadsheets and `.t/` files.

## File Map

```text
scripts/place_keyword_collector/
  __init__.py       package exports
  models.py         immutable contracts and enums
  config.py         environment and runtime policy
  rank_source.py    rank-run target selection
  parser.py         pure keywordList extraction
  browser.py        mobile Place page acquisition and state detection
  change.py         normalization, hashing, and version decision
  repository.py     schema preflight, refresh lookup, transactional save
  collector.py      retry, abort, evidence, and orchestration
  cli.py            command-line composition
scripts/run_place_keyword_collector.py
sql/place_keyword_collector/01_create_tables.sql
sql/place_keyword_collector/02_verify_tables.sql
tests/fixtures/place_keyword_collector/*.html
tests/test_place_keyword_*.py
docs/place-keyword-collector-runbook.md
```

---

### Task 1: Core Contracts and Configuration

**Files:**
- Create: `scripts/place_keyword_collector/__init__.py`
- Create: `scripts/place_keyword_collector/models.py`
- Create: `scripts/place_keyword_collector/config.py`
- Create: `tests/test_place_keyword_models.py`
- Create: `tests/test_place_keyword_config.py`
- Modify: `.env.example`

**Interfaces:**
- Produces: `RefreshPolicy`, `KeywordCollectStatus`, `RankPlaceTarget`, `CollectedKeyword`, `ParsedKeywordList`, `PreviousVersion`, `KeywordSnapshot`, `CollectionSummary`, and `PlaceKeywordConfig`.
- `PlaceKeywordConfig.from_env(repo_root: Path) -> PlaceKeywordConfig` reuses `DB_SERVER`, `DB_PORT`, and `KEYWORD_DISCOVERY_DB_*` credentials and reads `PLACE_KEYWORD_HEADLESS`, `PLACE_KEYWORD_TIMEOUT_SECONDS`, and `PLACE_KEYWORD_ARTIFACT_ROOT`.

Use these contracts:

```python
class RefreshPolicy(str, Enum):
    MONTHLY = "MONTHLY"
    WEEKLY = "WEEKLY"

class KeywordCollectStatus(str, Enum):
    SUCCESS = "SUCCESS"
    EMPTY = "EMPTY"
    BLOCKED = "BLOCKED"
    LOAD_TIMEOUT = "LOAD_TIMEOUT"
    PLACE_MISMATCH = "PLACE_MISMATCH"
    PARSE_ERROR = "PARSE_ERROR"

@dataclass(frozen=True)
class RankPlaceTarget:
    place_id: str
    place_name: str

@dataclass(frozen=True)
class CollectedKeyword:
    keyword_order: int
    raw_keyword: str
    normalized_keyword: str

@dataclass(frozen=True)
class ParsedKeywordList:
    place_id: str
    keywords: tuple[CollectedKeyword, ...]

@dataclass(frozen=True)
class PreviousVersion:
    effective_snapshot_id: int
    content_hash: str
    checked_at: datetime
    status: KeywordCollectStatus
```

- [ ] **Step 1: Write failing contract and configuration tests**

```python
def test_config_defaults_to_monthly_and_top_ten(tmp_path, monkeypatch):
    config = PlaceKeywordConfig.from_env(write_env(tmp_path), environ(monkeypatch))
    assert config.refresh_policy is RefreshPolicy.MONTHLY
    assert config.top_n == 10
    assert config.max_retries == 2
    assert config.failure_limit == 5

def test_config_repr_redacts_password(valid_config):
    assert "secret" not in repr(valid_config)
```

- [ ] **Step 2: Run tests and verify RED**

Run: `./.venv/Scripts/python.exe -m pytest -q tests/test_place_keyword_models.py tests/test_place_keyword_config.py`

Expected: FAIL because `scripts.place_keyword_collector` does not exist.

- [ ] **Step 3: Implement immutable models and validated configuration**

Validate `top_n` in 1-20, positive timeout, non-negative retry count, and positive failure limit. Keep passwords out of `repr` and error messages.

- [ ] **Step 4: Run Task 1 tests and verify GREEN**

Expected: all Task 1 tests pass.

- [ ] **Step 5: Commit**

Tell the user: `feat: 플레이스 대표키워드 수집 계약 추가`

```powershell
git add -- .env.example scripts/place_keyword_collector tests/test_place_keyword_models.py tests/test_place_keyword_config.py
git commit -m "feat: 플레이스 대표키워드 수집 계약 추가"
```

---

### Task 2: SQL Schema and Preflight Contract

**Files:**
- Create: `sql/place_keyword_collector/01_create_tables.sql`
- Create: `sql/place_keyword_collector/02_verify_tables.sql`
- Create: `tests/test_place_keyword_schema_sql.py`

**Interfaces:**
- Produces exactly `dbo.naver_place_keyword_snapshot` and `dbo.naver_place_keyword_result`.
- `effective_snapshot_id` is a nullable self-reference during insertion and must reference a valid-version snapshot after the transaction completes.

- [ ] **Step 1: Write failing SQL contract tests**

Assert exact table names, required columns, allowed status checks, unique keys, FKs, and indexes. Minimum constraints:

```python
assert "CHECK (collect_status IN ('SUCCESS','EMPTY','BLOCKED','LOAD_TIMEOUT','PLACE_MISMATCH','PARSE_ERROR'))" in ddl
assert "UNIQUE (run_id, place_id)" in ddl
assert "UNIQUE (snapshot_id, keyword_order)" in ddl
assert "FOREIGN KEY (effective_snapshot_id)" in ddl
```

- [ ] **Step 2: Run schema tests and verify RED**

Run: `./.venv/Scripts/python.exe -m pytest -q tests/test_place_keyword_schema_sql.py`

Expected: FAIL because SQL files do not exist.

- [ ] **Step 3: Write idempotent DDL**

Use these SQL types:

```text
snapshot_id bigint identity primary key
run_id uniqueidentifier not null
rank_run_id uniqueidentifier not null
place_id varchar(50) not null
place_name nvarchar(300) not null
source_url nvarchar(2000) not null
collect_status varchar(30) not null
collect_method varchar(20) not null
content_hash char(64) null
is_changed bit not null
effective_snapshot_id bigint null
keyword_count smallint not null
parser_version varchar(30) not null
collect_msg nvarchar(1000) null
checked_at datetime2(3) not null
keyword_order smallint not null
raw_keyword nvarchar(255) not null
normalized_keyword nvarchar(255) not null
```

Add indexes for `(place_id, checked_at DESC)`, `(rank_run_id)`, `(effective_snapshot_id)`, and `(snapshot_id, keyword_order)`. `02_verify_tables.sql` must fail with `THROW` unless table, column, constraint, and index counts match the contract.

- [ ] **Step 4: Run schema tests and verify GREEN**

- [ ] **Step 5: Commit**

Tell the user: `feat: 대표키워드 스냅샷 테이블 정의`

```powershell
git add -- sql/place_keyword_collector tests/test_place_keyword_schema_sql.py
git commit -m "feat: 대표키워드 스냅샷 테이블 정의"
```

---

### Task 3: Rank Target Source and Refresh Policy

**Files:**
- Create: `scripts/place_keyword_collector/rank_source.py`
- Create: `tests/test_place_keyword_rank_source.py`

**Interfaces:**
- Produces `RankResultSource.load(rank_run_id: str, top_n: int) -> tuple[RankPlaceTarget, ...]`.
- Produces `is_refresh_due(previous: PreviousVersion | None, policy: RefreshPolicy, now: datetime, force: bool) -> bool`.

- [ ] **Step 1: Write failing selection and refresh tests**

```python
def test_rank_source_selects_top_ten_organic_and_deduplicates_place_ids(fake_cursor):
    targets = RankResultSource(fake_cursor).load(RUN_ID, 10)
    assert [target.place_id for target in targets] == ["13149768", "12006259"]
    assert fake_cursor.params == (RUN_ID, 10)

def test_monthly_refresh_is_due_one_calendar_month_later():
    previous = version(checked_at=datetime(2026, 1, 31, 9))
    assert is_refresh_due(previous, RefreshPolicy.MONTHLY, datetime(2026, 2, 28, 9), False)

def test_force_refresh_ignores_recent_check():
    assert is_refresh_due(version(checked_at=NOW), RefreshPolicy.MONTHLY, NOW, True)
```

- [ ] **Step 2: Run tests and verify RED**

Run: `./.venv/Scripts/python.exe -m pytest -q tests/test_place_keyword_rank_source.py`

- [ ] **Step 3: Implement parameterized target SQL and calendar-safe month arithmetic**

The SQL must filter `collect_status IN ('SUCCESS','PARTIAL')`, `organic_rank IS NOT NULL`, `is_ad=0`, and `organic_rank<=%s`, then deduplicate Place IDs deterministically using the best organic rank and lexical place name tie-breaker.

- [ ] **Step 4: Run Task 3 tests and verify GREEN**

- [ ] **Step 5: Commit**

Tell the user: `feat: 순위 결과 기반 수집 대상 선정`

```powershell
git add -- scripts/place_keyword_collector/rank_source.py tests/test_place_keyword_rank_source.py
git commit -m "feat: 순위 결과 기반 수집 대상 선정"
```

---

### Task 4: Pure keywordList Parser and Change Detector

**Files:**
- Create: `scripts/place_keyword_collector/parser.py`
- Create: `scripts/place_keyword_collector/change.py`
- Create: `tests/fixtures/place_keyword_collector/keyword_list.html`
- Create: `tests/fixtures/place_keyword_collector/empty_keyword_list.html`
- Create: `tests/fixtures/place_keyword_collector/wrong_place_object.html`
- Create: `tests/fixtures/place_keyword_collector/missing_keyword_list.html`
- Create: `tests/test_place_keyword_parser.py`
- Create: `tests/test_place_keyword_change.py`

**Interfaces:**
- `KeywordListParser.parse(html: str, expected_place_id: str) -> ParsedKeywordList`.
- Raises `PlaceMismatchError` when candidate objects exist but none match the requested ID.
- Raises `KeywordListParseError` when the page is not blocked but no definitive array can be found.
- `normalize_keyword(value: str) -> str`.
- `content_hash(keywords: Sequence[CollectedKeyword]) -> str` includes normalized array order.
- `decide_change(previous: PreviousVersion | None, parsed: ParsedKeywordList) -> ChangeDecision`.

- [ ] **Step 1: Store the user-provided source excerpt as a minimal fixture and write failing parser tests**

```python
def test_parser_extracts_target_keyword_list_in_original_order():
    parsed = KeywordListParser().parse(fixture("keyword_list.html"), "13149768")
    assert [item.raw_keyword for item in parsed.keywords] == ["순대", "순댓국", "국밥", "수육"]
    assert [item.keyword_order for item in parsed.keywords] == [1, 2, 3, 4]

def test_parser_does_not_take_keyword_list_from_another_place():
    with pytest.raises(PlaceMismatchError):
        KeywordListParser().parse(fixture("wrong_place_object.html"), "13149768")
```

- [ ] **Step 2: Run parser tests and verify RED**

Run: `./.venv/Scripts/python.exe -m pytest -q tests/test_place_keyword_parser.py tests/test_place_keyword_change.py`

- [ ] **Step 3: Implement structured extraction and minimal normalization**

Parse script payloads into Python structures where possible and recursively traverse mappings and arrays. Only accept `keywordList` from a mapping whose `id` string equals `expected_place_id`. Decode escaped serialized payloads in bounded passes; never use `eval`.

라이브 확정 파싱 계약은 다음과 같다. 하나의 논리적 최상위 Apollo 객체에 `PlaceDetailBase:{요청 Place ID}` 키가 정확히 하나만 있으면 그 객체 아래의 `id` 없는 `keywordList` 배열을 요청 매장의 배열로 허용한다. 최상위 `PlaceDetailBase:` 매장이 둘 이상이면 `id` 없는 배열은 거부하고, 배열과 같은 객체에 요청 Place ID가 명시된 경우만 허용한다. 중첩 `PlaceDetailBase:` 키, `PlaceDetailTopPhotoItem:` 같은 사진 키, 사진 URL 및 URL 속 숫자는 매장 신원으로 사용하지 않는다. 요청 매장 객체의 `keywordList:null`은 정상적인 미설정 관측으로 분류하여 빈 배열과 같은 `EMPTY`로 처리한다.

```python
def normalize_keyword(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    return " ".join(normalized.split()).casefold()
```

Remove empty normalized values and duplicate normalized values after their first occurrence while retaining the first raw value and order.

- [ ] **Step 4: Verify ordered hashing and change semantics**

Test that identical arrays have identical SHA-256 values, reordered arrays differ, and `EMPTY` hashes are deterministic.

- [ ] **Step 5: Run Task 4 tests and verify GREEN**

- [ ] **Step 6: Commit**

Tell the user: `feat: 플레이스 대표키워드 원문 파서 추가`

```powershell
git add -- scripts/place_keyword_collector/parser.py scripts/place_keyword_collector/change.py tests/fixtures/place_keyword_collector tests/test_place_keyword_parser.py tests/test_place_keyword_change.py
git commit -m "feat: 플레이스 대표키워드 원문 파서 추가"
```

---

### Task 5: Browser Page Acquisition and Evidence

**Files:**
- Create: `scripts/place_keyword_collector/browser.py`
- Create: `tests/fixtures/place_keyword_collector/blocked.html`
- Create: `tests/test_place_keyword_browser.py`

**Interfaces:**
- `PlacePageBrowser.fetch(target: RankPlaceTarget) -> PlacePage`.
- `PlacePage(final_url: str, html: str)` contains no parsing policy.
- Raises typed `BlockedPageError`, `PlaceLoadTimeout`, and `PlaceBrowserError`, each carrying `last_url` and `html`.
- `save_evidence(directory: Path, html: str) -> tuple[Path, Path]` writes HTML and screenshot for final failures.

- [ ] **Step 1: Write failing browser state tests with a fake WebDriver**

```python
def test_browser_uses_mobile_place_home_url(fake_driver):
    browser(fake_driver).fetch(RankPlaceTarget("13149768", "농민백암순대 본점"))
    assert fake_driver.requested_url == "https://m.place.naver.com/restaurant/13149768/home"

def test_browser_classifies_access_restriction(fake_driver):
    fake_driver.page_source = fixture("blocked.html")
    with pytest.raises(BlockedPageError):
        browser(fake_driver).fetch(target())
```

- [ ] **Step 2: Run browser tests and verify RED**

Run: `./.venv/Scripts/python.exe -m pytest -q tests/test_place_keyword_browser.py`

- [ ] **Step 3: Implement condition-based page readiness**

Use mobile user-agent, headless configuration, bounded polling, and page-load timeout. A page is ready when source contains the requested Place ID and either `keywordList` or definitive target object data. Detect the exact Naver restriction markers before parsing.

- [ ] **Step 4: Test timeout and evidence failures**

Assert deadline covers navigation plus polling, screenshots are checked for a false return value, and evidence errors never expose credentials.

- [ ] **Step 5: Run Task 5 tests and verify GREEN**

- [ ] **Step 6: Commit**

Tell the user: `feat: 플레이스 상세 페이지 브라우저 수집 추가`

```powershell
git add -- scripts/place_keyword_collector/browser.py tests/fixtures/place_keyword_collector/blocked.html tests/test_place_keyword_browser.py
git commit -m "feat: 플레이스 상세 페이지 브라우저 수집 추가"
```

---

### Task 6: Version Repository and Transactional Persistence

**Files:**
- Create: `scripts/place_keyword_collector/repository.py`
- Create: `tests/test_place_keyword_repository.py`

**Interfaces:**
- `PlaceKeywordRepository.preflight(expected_database: str = "naverDB") -> None`.
- `get_previous(place_id: str) -> PreviousVersion | None` returns the latest check and its effective valid version.
- `save(snapshot: KeywordSnapshot, keywords: Sequence[CollectedKeyword]) -> int` commits one check atomically.
- `get_due_targets(...)` is not added; refresh decisions remain outside persistence.

- [ ] **Step 1: Write failing preflight and lookup tests**

Use fake cursors to assert exact parameterized queries, expected schema equality, correct conversion of SQL rows, and rejection of the wrong database.

- [ ] **Step 2: Write failing persistence tests**

```python
def test_changed_success_inserts_snapshot_results_and_self_effective_id(repo):
    snapshot_id = repo.save(changed_success(), keywords())
    assert snapshot_id == 101
    assert repo.connection.commits == 1
    assert repo.updated_effective_id == 101

def test_unchanged_check_inserts_no_keyword_rows(repo):
    repo.save(unchanged(effective_snapshot_id=101), ())
    assert repo.executemany_calls == []

def test_failure_keeps_previous_effective_snapshot(repo):
    repo.save(blocked(effective_snapshot_id=101), ())
    assert repo.inserted_effective_snapshot_id == 101
```

- [ ] **Step 3: Run repository tests and verify RED**

Run: `./.venv/Scripts/python.exe -m pytest -q tests/test_place_keyword_repository.py`

- [ ] **Step 4: Implement exact schema preflight and one-check transaction**

For a changed valid observation, insert the snapshot with a null effective ID, insert result rows, update `effective_snapshot_id=snapshot_id`, verify row count, and commit. For unchanged or failed observations, insert with the previous effective ID and no result rows. Roll back on any mismatch; classify duplicate `(run_id, place_id)` as a task-local persistence error and connection/schema failures as fatal.

- [ ] **Step 5: Run Task 6 tests and verify GREEN**

- [ ] **Step 6: Commit**

Tell the user: `feat: 대표키워드 변경 이력 저장소 구현`

```powershell
git add -- scripts/place_keyword_collector/repository.py tests/test_place_keyword_repository.py
git commit -m "feat: 대표키워드 변경 이력 저장소 구현"
```

---

### Task 7: Collector Orchestration, Retry, and Abort

**Files:**
- Create: `scripts/place_keyword_collector/collector.py`
- Create: `tests/test_place_keyword_collector.py`

**Interfaces:**
- `PlaceKeywordCollector.run(targets: Iterable[RankPlaceTarget], run_id: str, rank_run_id: str, policy: RefreshPolicy, force_refresh: bool = False) -> CollectionSummary`.
- Browser sessions are reused across targets and closed in `finally`.
- Repository lookup occurs before browser creation so all-not-due executions make zero browser calls.

- [ ] **Step 1: Write failing happy-path and reuse tests**

```python
def test_recent_monthly_target_is_reused_without_browser_call():
    summary = collector(previous=recent_version()).run([target()], RUN_ID, RANK_RUN_ID, RefreshPolicy.MONTHLY)
    assert summary.reused == 1
    assert browser.fetch_calls == []

def test_changed_success_persists_keywords_once():
    summary = collector(previous=old_version(), page=valid_page()).run([target()], RUN_ID, RANK_RUN_ID, RefreshPolicy.MONTHLY)
    assert summary.status_counts == {KeywordCollectStatus.SUCCESS: 1}
    assert repository.saved[0].snapshot.is_changed is True
    assert len(repository.saved[0].keywords) == 4
```

- [ ] **Step 2: Run collector tests and verify RED**

Run: `./.venv/Scripts/python.exe -m pytest -q tests/test_place_keyword_collector.py`

- [ ] **Step 3: Implement retry matrix and final-attempt persistence**

Retry only `BlockedPageError` and `PlaceLoadTimeout`, two retries after the first attempt. Persist only the final attempt. Save final failure evidence under `<artifact_root>/<run_id>/<place_id>/`. Treat `SUCCESS` and `EMPTY` as resetting the consecutive-failure counter.

- [ ] **Step 4: Test five-identical-failure abort and differing-failure reset**

Assert the sixth target is not fetched after five identical consecutive failures, while a success or different failure identity resets/restarts the counter correctly.

- [ ] **Step 5: Run Task 7 tests and verify GREEN**

- [ ] **Step 6: Commit**

Tell the user: `feat: 대표키워드 수집 실행 흐름 구현`

```powershell
git add -- scripts/place_keyword_collector/collector.py tests/test_place_keyword_collector.py
git commit -m "feat: 대표키워드 수집 실행 흐름 구현"
```

---

### Task 8: CLI Composition and End-to-End Tests

**Files:**
- Create: `scripts/place_keyword_collector/cli.py`
- Create: `scripts/run_place_keyword_collector.py`
- Create: `tests/test_place_keyword_cli.py`
- Create: `tests/test_place_keyword_end_to_end.py`

**Interfaces:**
- CLI requires `--rank-run-id`.
- CLI options are `--top-n`, `--refresh-policy monthly|weekly`, repeatable `--include-place-id`, `--force-refresh`, `--dry-run`, and `--rollback-test`.
- `select_included_targets(targets: Sequence[RankPlaceTarget], requested_place_ids: Sequence[str]) -> tuple[RankPlaceTarget, ...]` preserves rank-source order and raises `CliError` when any requested ID is absent.
- Exit 0 for completed runs without persistence failures, 1 for controlled abort or task persistence failures, and 2 for configuration, preflight, or fatal repository errors.

- [ ] **Step 1: Write failing CLI argument and dry-run tests**

```python
def test_cli_defaults_to_top_ten_and_monthly():
    args = parse_args(["--rank-run-id", RANK_RUN_ID])
    assert args.top_n == 10
    assert args.refresh_policy == "monthly"

def test_include_place_id_rejects_ids_absent_from_rank_run():
    targets = (RankPlaceTarget("13149768", "농민백암순대 본점"),)
    with pytest.raises(CliError, match="requested Place ID is absent from the rank run: 999"):
        select_included_targets(targets, ("999",))

def test_dry_run_lists_unique_target_count_without_browser_or_writes(tmp_path):
    harness = CliHarness(tmp_path, targets=(target("1"), target("2"), target("3")))
    assert harness.run(["--rank-run-id", RANK_RUN_ID, "--dry-run"]) == 0
    assert harness.output == f"run_id={RUN_ID} rank_run_id={RANK_RUN_ID} targets=3 due=3 dry_run=true\n"
    assert harness.browser_create_calls == 0
    assert harness.repository_save_calls == 0
```

Define `CliHarness` inside `tests/test_place_keyword_cli.py`; it injects a fixed UUID, fake database connection, fake rank source, fake repository, and a browser factory that records creation without opening Chrome.

- [ ] **Step 2: Run CLI tests and verify RED**

Run: `./.venv/Scripts/python.exe -m pytest -q tests/test_place_keyword_cli.py tests/test_place_keyword_end_to_end.py`

- [ ] **Step 3: Implement composition root and rollback connection adapter**

Preflight schema before browser creation. Load and deduplicate targets, calculate due count, then compose browser, parser, repository, and collector. `--rollback-test` converts every repository commit into rollback while retaining the full live collection path.

- [ ] **Step 4: Run Task 8 tests and verify GREEN**

- [ ] **Step 5: Run the complete automated suite**

Run: `./.venv/Scripts/python.exe -m pytest -q`

Expected: all tests pass with zero failures.

- [ ] **Step 6: Commit**

Tell the user: `feat: 대표키워드 수집 CLI 완성`

```powershell
git add -- scripts/place_keyword_collector/cli.py scripts/run_place_keyword_collector.py tests/test_place_keyword_cli.py tests/test_place_keyword_end_to_end.py
git commit -m "feat: 대표키워드 수집 CLI 완성"
```

---

### Task 9: Database and Live Integration Verification

**Files:**
- Create: `docs/place-keyword-collector-runbook.md`
- Modify only if verified defects are found: `scripts/place_keyword_collector/*.py`, corresponding `tests/test_place_keyword_*.py`

**Interfaces:**
- Produces an operator runbook with create, verify, dry-run, rollback-test, live three-place test, full-run, rerun, force-refresh, and diagnostic SQL commands.

- [ ] **Step 1: Give the user SQL execution order**

The user executes:

```text
sql/place_keyword_collector/01_create_tables.sql
sql/place_keyword_collector/02_verify_tables.sql
```

Do not proceed to live persistence until the user reports verification success.

- [ ] **Step 2: Run dry-run for rank execution `d32fbdc3-3af6-4d25-85e1-fe6970855df1`**

```powershell
./.venv/Scripts/python.exe scripts/run_place_keyword_collector.py --rank-run-id d32fbdc3-3af6-4d25-85e1-fe6970855df1 --dry-run
```

Verify target count equals the SQL count of distinct top-10 organic Place IDs.

- [ ] **Step 3: Run a rollback test restricted to the three approved Place IDs**

Run the approved repeatable filter against the existing rank run:

```powershell
./.venv/Scripts/python.exe scripts/run_place_keyword_collector.py `
  --rank-run-id d32fbdc3-3af6-4d25-85e1-fe6970855df1 `
  --include-place-id 13149768 `
  --include-place-id 12006259 `
  --include-place-id 31076466 `
  --force-refresh `
  --rollback-test
```

Compare extracted raw arrays against browser source and verify both target tables retain zero rows after rollback.

- [ ] **Step 4: Run a live three-place persistence test**

Verify three final snapshot rows, valid keyword counts, statuses, hashes, and effective links. Query result rows ordered by `place_id, keyword_order` and compare with source.

- [ ] **Step 5: Verify unchanged and forced-refresh behavior**

Re-run normally and confirm all three are reused without browser collection because monthly refresh is not due. Then run `--force-refresh`; confirm new check snapshots exist, unchanged arrays have `is_changed=0`, no duplicate keyword result rows exist, and `effective_snapshot_id` points to the previous changed version.

- [ ] **Step 6: Expand to all unique targets from the rank run**

Run with defaults, then report processed, reused, changed, empty, failure, and persistence-failure counts. Stop and diagnose if identical failures reach five.

- [ ] **Step 7: Write the operator runbook and run final verification**

Run:

```powershell
./.venv/Scripts/python.exe -m pytest -q
git diff --check
git status --short
```

- [ ] **Step 8: Commit**

Tell the user: `docs: 대표키워드 수집 운영 절차 정리`

```powershell
git add -- docs/place-keyword-collector-runbook.md
git commit -m "docs: 대표키워드 수집 운영 절차 정리"
```

- [ ] **Step 9: Push and prepare the pull request**

Push `feat/place-keyword-collector`. Use a Korean PR title and description containing automated test counts, the three-place validation result, full-run counts, schema verification result, and the prerequisite that PR #5 is merged or included in main.
