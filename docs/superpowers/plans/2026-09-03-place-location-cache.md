# Naver Place Location Cache Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve missing search coordinates from a Naver Place ID, cache them in `naverDB`, and continue rank collection per task when some locations fail.

**Architecture:** A focused `place_location.py` module owns HTML parsing, the Place HTTP client, cache persistence, and cache-first resolution. Input adapters allow an absent coordinate pair, while CLI orchestration resolves unique target stores before handing only location-ready tasks to the unchanged browser collector and persists location failures as snapshots.

**Tech Stack:** Python 3.13, BeautifulSoup4, urllib, pymssql, SQL Server, pytest

**Spec:** `docs/superpowers/specs/2026-09-03-place-location-cache-design.md`

## Global Constraints

- Coordinate evidence is limited to a matching `id/x/y` store object and a matching `did/dlng/dlat` route URL.
- Photo URLs are not coordinate evidence.
- ERP databases remain read-only; the cache is stored only in `naverDB`.
- Existing explicit coordinate inputs remain supported.
- A partial coordinate pair is invalid.
- Cache entries do not expire automatically.
- Location resolution failure skips only that task and records `LOCATION_RESOLVE_ERROR`.
- All SQL values use parameter binding; schema scripts are idempotent and non-destructive.

---

### Task 1: Coordinate value, parser, and cache-first resolver

**Files:**
- Create: `scripts/keyword_discovery_rank/place_location.py`
- Create: `tests/test_keyword_discovery_place_location.py`
- Create: `tests/fixtures/keyword_discovery_rank/place_location_object.html`
- Create: `tests/fixtures/keyword_discovery_rank/place_location_route.html`

**Interfaces:**
- Produces: `PlaceLocation`, `PlaceLocationError`, `PlaceCoordinateParser.parse(html, expected_place_id)`, `PlacePageClient.fetch(place_id)`, `PlaceLocationResolver.resolve(place_id)`.
- Consumes: repository objects exposing `get(place_id)` and `upsert(location)`.

- [ ] **Step 1: Add failing parser tests** for matching object `id/x/y`, matching route `did/dlng/dlat`, Place ID mismatch, conflicting evidence, global bounds, Korean bounds, and explicit proof that photo-link coordinates alone fail.
- [ ] **Step 2: Run parser tests and verify RED** with import or missing-class failures.
- [ ] **Step 3: Implement minimal parser and immutable value object** using strict Place ID association and five-decimal evidence comparison.
- [ ] **Step 4: Run parser tests and verify GREEN.**
- [ ] **Step 5: Add failing resolver tests** proving cache hit avoids HTTP, cache miss fetches once and upserts once, and repeated in-run lookup uses memory.
- [ ] **Step 6: Run resolver tests and verify RED.**
- [ ] **Step 7: Implement `PlacePageClient` and `PlaceLocationResolver`** with fixed HTTPS URL construction, allowed-host validation, mobile User-Agent, timeout, safe errors, and memory caching.
- [ ] **Step 8: Run `tests/test_keyword_discovery_place_location.py` and verify GREEN.**
- [ ] **Step 9: Commit** with `feat: resolve and cache Naver place coordinates`.

### Task 2: SQL cache schema and repository

**Files:**
- Create: `sql/keyword_discovery_rank/03_create_place_location.sql`
- Create: `sql/keyword_discovery_rank/04_verify_place_location.sql`
- Modify: `scripts/keyword_discovery_rank/repository.py`
- Modify: `tests/test_keyword_discovery_repository.py`
- Modify: `tests/test_keyword_discovery_schema_sql.py`

**Interfaces:**
- Produces: `PlaceLocationRepository.get(place_id)`, `upsert(location)`, and `preflight(expected_database="naverDB")`.
- Consumes: `PlaceLocation` from Task 1 and the existing pymssql connection/rollback adapter.

- [ ] **Step 1: Add failing SQL structure tests** for the six-column cache contract, PK, coordinate checks, idempotency guards, snapshot coordinate nullability, and absence of destructive statements.
- [ ] **Step 2: Run schema tests and verify RED.**
- [ ] **Step 3: Write creation and verification SQL** using `IF OBJECT_ID`, `ALTER COLUMN ... NULL`, explicit constraints, metadata comparisons, and `THROW` on mismatch.
- [ ] **Step 4: Run schema tests and verify GREEN.**
- [ ] **Step 5: Add failing repository tests** for cache miss, cache hit mapping, insert, update preserving `resolved_at`, commit, rollback classification, and schema preflight.
- [ ] **Step 6: Run repository tests and verify RED.**
- [ ] **Step 7: Implement `PlaceLocationRepository`** with parameterized SELECT and UPDATE-then-INSERT upsert in one transaction.
- [ ] **Step 8: Run repository and schema tests and verify GREEN.**
- [ ] **Step 9: Commit** with `feat: add Naver place location cache schema`.

### Task 3: Optional coordinate input and collection orchestration

**Files:**
- Modify: `scripts/keyword_discovery_rank/models.py`
- Modify: `scripts/keyword_discovery_rank/task_source.py`
- Modify: `scripts/keyword_discovery_rank/collector.py`
- Modify: `scripts/keyword_discovery_rank/cli.py`
- Modify: `tests/test_keyword_discovery_models.py`
- Modify: `tests/test_keyword_discovery_task_source.py`
- Modify: `tests/test_keyword_discovery_collector.py`
- Modify: `tests/test_keyword_discovery_cli.py`
- Modify: `tests/test_keyword_discovery_end_to_end.py`

**Interfaces:**
- Changes: `SearchTask.latitude` and `longitude` become `float | None` before preparation.
- Produces: CLI preparation that resolves coordinates by `target_store_id -> OwnStore.place_id`, emits failure snapshots, then invokes the existing collector with resolved tasks.

- [ ] **Step 1: Add failing input tests** for absent pair accepted, explicit pair retained, partial pair rejected, headers without coordinate columns accepted, and deterministic pre-resolution task keys.
- [ ] **Step 2: Run task-source tests and verify RED.**
- [ ] **Step 3: Implement optional coordinate parsing and task-key serialization** using `AUTO` only when both coordinates are absent.
- [ ] **Step 4: Run task-source/model tests and verify GREEN.**
- [ ] **Step 5: Add failing orchestration tests** for unique-store resolution, resolved task replacement, explicit-coordinate bypass, one failed location plus one successful search, `LOCATION_RESOLVE_ERROR` persistence, and rollback adapter reuse.
- [ ] **Step 6: Run CLI/collector tests and verify RED.**
- [ ] **Step 7: Add `LOCATION_RESOLVE_ERROR` and implement preprocessing orchestration** without changing browser/parser/validator responsibilities.
- [ ] **Step 8: Run all keyword discovery tests and verify GREEN.**
- [ ] **Step 9: Commit** with `feat: resolve missing coordinates before rank collection`.

### Task 4: Schema verification and live rollback acceptance

**Files:**
- Modify: `README.md`
- Modify: `docs/keyword-discovery-rank-pilot-runbook.md`

**Interfaces:**
- Consumes: the SQL files and executable CLI from Tasks 1-3.
- Produces: operator instructions for applying SQL, omitting coordinates from Excel, and validating cache reuse.

- [ ] **Step 1: Document the new input contract, SQL execution order, cache behavior, and safe rollback test command.**
- [ ] **Step 2: Run `python -m pytest tests -q -k keyword_discovery` and require zero failures.**
- [ ] **Step 3: Run `git diff --check` and inspect the complete diff for secret values and unrelated changes.**
- [ ] **Step 4: Ask the user to execute `03_create_place_location.sql` with the privileged account.**
- [ ] **Step 5: Run `04_verify_place_location.sql` and capture verified table, column, constraint, and key counts.**
- [ ] **Step 6: Record baseline counts for cache, snapshot, and result tables.**
- [ ] **Step 7: Run a one-store Excel input with blank coordinates under `--rollback-test`.**
- [ ] **Step 8: Verify the run resolves coordinates, searches successfully, and leaves all three table counts equal to baseline.**
- [ ] **Step 9: Run a second non-rollback acceptance only after rollback acceptance passes, then verify one cache row and its coordinates by Place ID.**
- [ ] **Step 10: Commit** with `docs: document Place location resolution workflow`.
