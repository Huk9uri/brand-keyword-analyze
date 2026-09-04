# Reusable Keyword Workbook Input Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reusable workflow that reads `inputs/keyword_input.xlsx`, validates the canonical `키워드입력` schema, deduplicates up to five keywords per store, and produces the existing 30-day keyword-volume workbook with one PowerShell command.

**Architecture:** Add a strict generic workbook extractor and keep the existing SearchAd/DataLab estimation pipeline unchanged. A generic Python orchestrator owns fixed input discovery, timestamped output directories, API execution, and workbook generation; a thin PowerShell entry point provides the stable user command. A generated XLSX template defines the input contract and is verified with the same artifact-tool runtime used by production.

**Tech Stack:** Python 3.12, Node.js 24, `@oai/artifact-tool`, pytest, PowerShell, Naver SearchAd API, Naver DataLab API

**Spec:** `docs/superpowers/specs/2026-09-01-reusable-keyword-workbook-input-design.md`

## Global Constraints

- The only automatic input path is `inputs/keyword_input.xlsx`.
- The data sheet name is exactly `키워드입력`, with row 1 as the header row.
- Supported keyword headers are exactly `키워드1` through `키워드5`; `키워드6` or higher is rejected with anchor-model guidance.
- Every populated store row needs a nonblank `매장명` and at least one nonblank keyword.
- Duplicate store names are rejected before any API call.
- Duplicate keywords within a store are normalized and only the first slot is retained.
- SearchAd and DataLab credentials remain in `.env` and credential values must never be printed or committed.
- Workbook authoring and inspection use the bundled Node.js runtime and `@oai/artifact-tool` only.
- Result workbooks preserve the source sheets and add `30일_키워드요약` and `30일_일간검색량`.
- The result sheet columns remain as approved in commit `7e561cd`; diagnostic status remains in JSON only.
- Existing legacy workbook commands remain functional.

---

### Task 1: Canonical Workbook Extractor

**Files:**
- Create: `scripts/node/extract_keyword_input.mjs`
- Create: `tests/test_keyword_input_extractor.py`

**Interfaces:**
- Consumes: `--input <xlsx> --output <json> [--store <exact name>]`
- Produces: `{source_file: string, sheet: "키워드입력", stores: [{source_row: number, store_name: string, keywords: [{slot: "keyword1"|"keyword2"|"keyword3"|"keyword4"|"keyword5", keyword: string}]}]}`
- Throws before writing output when the workbook violates the canonical schema.

- [ ] **Step 1: Write failing tests for canonical extraction and store-local deduplication**

Create test fixtures at runtime by invoking a test-only artifact-tool builder in `tests/fixtures/build_keyword_input_fixture.mjs`. The fixture rows must include:

```javascript
[
  ["매장명", "키워드1", "키워드2", "키워드3", "키워드4", "키워드5", "메모"],
  ["한촌설렁탕 테스트점", "갈비탕", " 해장 ", "갈비탕", null, "혼밥", "ignored"],
]
```

Assert the extractor returns only these slots, preserving the first duplicate:

```python
assert store["keywords"] == [
    {"slot": "keyword1", "keyword": "갈비탕"},
    {"slot": "keyword2", "keyword": "해장"},
    {"slot": "keyword5", "keyword": "혼밥"},
]
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.pytest_tmp\canonical_extract_red tests/test_keyword_input_extractor.py::test_extracts_and_deduplicates_up_to_five_keywords
```

Expected: FAIL because `scripts/node/extract_keyword_input.mjs` does not exist.

- [ ] **Step 3: Implement the minimal canonical extractor**

Implement these helpers in `extract_keyword_input.mjs`:

```javascript
function normalize(value) {
  return String(value ?? "").trim().replace(/\s+/g, "").toLowerCase();
}

function displayText(value) {
  const result = String(value ?? "").trim();
  return result || null;
}

function deduplicateKeywords(row, keywordColumns) {
  const seen = new Set();
  return keywordColumns.flatMap(({ index, slot }) => {
    const keyword = displayText(row[index]);
    const key = normalize(keyword);
    if (!key || seen.has(key)) return [];
    seen.add(key);
    return [{ slot, keyword }];
  });
}
```

Read only the `키워드입력` sheet. Locate headers by their exact trimmed text rather than fixed column numbers. Ignore non-keyword columns.

- [ ] **Step 4: Run the focused test and verify GREEN**

Run the command from Step 2.

Expected: `1 passed`.

- [ ] **Step 5: Commit the extractor behavior**

```powershell
git add -- scripts/node/extract_keyword_input.mjs tests/test_keyword_input_extractor.py tests/fixtures/build_keyword_input_fixture.mjs
git commit -m "feat: extract canonical keyword workbooks"
```

---

### Task 2: Strict Preflight Validation

**Files:**
- Modify: `scripts/node/extract_keyword_input.mjs`
- Modify: `tests/test_keyword_input_extractor.py`

**Interfaces:**
- Consumes: parsed worksheet header and row matrices from Task 1.
- Produces: validation errors containing the sheet name plus an exact row, column, or header where applicable.

- [ ] **Step 1: Write table-driven failing validation tests**

Add independently generated fixtures and assertions for:

```python
cases = [
    ("missing_sheet", "sheet not found: 키워드입력"),
    ("missing_store_header", "missing required header: 매장명"),
    ("missing_keyword1_header", "missing required header: 키워드1"),
    ("keyword6_header", "앵커 키워드 기반 별도 모델"),
    ("duplicate_store", "duplicate store name"),
    ("no_keywords", "at least one keyword is required"),
    ("orphan_values", "store name is required"),
    ("example_row", "예시 행을 삭제"),
]
```

For every case, assert the extractor exits nonzero, does not create the JSON output, and includes the expected phrase in stderr.

- [ ] **Step 2: Run validation tests and verify RED**

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.pytest_tmp\canonical_validation_red tests/test_keyword_input_extractor.py -k "validation or rejects"
```

Expected: failures for rules not yet implemented.

- [ ] **Step 3: Implement one-pass validation before output**

Implement exact header recognition with:

```javascript
const keywordHeaderPattern = /^키워드(\d+)$/;
const supportedHeaders = new Set(["키워드1", "키워드2", "키워드3", "키워드4", "키워드5"]);
```

Reject any matched keyword header outside the supported set. Accumulate row errors, sort them by source row, print each on its own line, and throw a final `input validation failed` error. Treat a row as empty only when every used cell is blank. Reject store names equal to `예시 매장명` or beginning with `예시:`.

- [ ] **Step 4: Run all extractor tests and verify GREEN**

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.pytest_tmp\canonical_validation_green tests/test_keyword_input_extractor.py
```

Expected: all tests pass.

- [ ] **Step 5: Commit strict validation**

```powershell
git add -- scripts/node/extract_keyword_input.mjs tests/test_keyword_input_extractor.py tests/fixtures/build_keyword_input_fixture.mjs
git commit -m "feat: validate canonical keyword input"
```

---

### Task 3: Reusable XLSX Template

**Files:**
- Create: `scripts/node/build_keyword_input_template.mjs`
- Create: `templates/keyword_input_template.xlsx`
- Create: `tests/test_keyword_input_template.py`

**Interfaces:**
- Consumes: `--output templates/keyword_input_template.xlsx --preview-dir <dir>`
- Produces: one XLSX with `사용방법` and `키워드입력` sheets plus preview PNGs for both sheets.

- [ ] **Step 1: Write a failing template contract test**

Build the template into `tmp_path`, import it using `@oai/artifact-tool`, and assert:

```python
assert sheet_names == ["사용방법", "키워드입력"]
assert keyword_headers == ["매장명", "키워드1", "키워드2", "키워드3", "키워드4", "키워드5", "메모"]
assert example_row[:6] == ["예시 매장명", "지역명", "역명", "메뉴명", None, None]
```

Also assert both preview PNGs and the XLSX exist and are nonempty.

- [ ] **Step 2: Run the template test and verify RED**

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.pytest_tmp\template_red tests/test_keyword_input_template.py
```

Expected: FAIL because the builder does not exist.

- [ ] **Step 3: Implement the artifact-tool template builder**

Use `Workbook.create()` and create both sheets before writing values. The `사용방법` sheet must include these literal instructions:

```text
1. 이 파일을 프로젝트의 inputs/keyword_input.xlsx로 저장합니다.
2. 키워드입력 시트의 예시 행을 삭제하고 실제 매장을 입력합니다.
3. 매장당 키워드는 최대 5개입니다.
4. 6개 이상은 앵커 키워드 기반 별도 모델이 필요합니다.
5. 프로젝트 폴더에서 .\run_keyword_volume.ps1을 실행합니다.
```

Style the title and headers consistently with the existing navy workbook headers, freeze row 1 on `키워드입력`, set readable column widths, apply `@` text format to input columns, render both sheets, scan formula errors, and export the XLSX.

- [ ] **Step 4: Run the artifact operation marker and generate the committed template**

Immediately before generation, run exactly once:

```powershell
& 'C:\Users\user1\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' 'C:\Users\user1\.codex\plugins\cache\openai-primary-runtime\spreadsheets\26.826.11250\skills\spreadsheets\container_tools\mark_artifact_operation_started.mjs' --operation-kind create --expected-output-count 1 --output-format xlsx
```

Then run the builder with the loader-provided Node.js and node_modules paths. Do not install or resolve alternate spreadsheet libraries.

- [ ] **Step 5: Verify the template test and visual previews**

Run the command from Step 2 and inspect both rendered PNGs. Confirm no clipped header or instruction text and no formula error matches.

- [ ] **Step 6: Commit the template**

```powershell
git add -- scripts/node/build_keyword_input_template.mjs templates/keyword_input_template.xlsx tests/test_keyword_input_template.py
git commit -m "feat: add keyword input workbook template"
```

---

### Task 4: Generic Orchestrator and Timestamped Outputs

**Files:**
- Create: `scripts/run_keyword_volume.py`
- Create: `tests/test_run_keyword_volume.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: no required CLI arguments; optional `--end-date YYYY-MM-DD`, `--store`, `--force-refresh`, and `--dry-run` remain available for testing and operations.
- Uses: `inputs/keyword_input.xlsx`, `.env`, `scripts/node/extract_keyword_input.mjs`, existing `run_pipeline`, and `scripts/node/build_yuksudang_volume_workbook.mjs`.
- Produces: `outputs/YYYYMMDD_HHMMSS/매장별_키워드_30일_일간검색량_YYYY-MM-DD.xlsx` plus JSON, cache, and previews.

- [ ] **Step 1: Write failing dry-run and preflight tests**

Test these observable behaviors:

```python
def test_defaults_to_canonical_input_and_reports_counts(tmp_path: Path):
    assert "input=inputs\\keyword_input.xlsx" in completed.stdout
    assert "keyword_slots=3" in completed.stdout

def test_invalid_input_stops_before_api_clients_are_created(tmp_path: Path):
    assert completed.returncode != 0
    assert "input validation failed" in completed.stderr
    assert not list(output_root.glob("**/daily_volume_results.json"))

def test_default_output_directory_is_timestamped(tmp_path: Path):
    assert re.fullmatch(r"\d{8}_\d{6}", reported_output_dir.name)
```

Inject `--now 2026-09-01T12:34:56` as a hidden deterministic test option so the expected folder is `outputs/20260901_123456`; do not expose `--now` in the PowerShell wrapper.

- [ ] **Step 2: Run orchestrator tests and verify RED**

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.pytest_tmp\generic_runner_red tests/test_run_keyword_volume.py
```

Expected: FAIL because `scripts/run_keyword_volume.py` does not exist.

- [ ] **Step 3: Implement the generic orchestrator**

Reuse imports and helpers from `run_yuksudang_daily_keyword_volume.py`, but set:

```python
DEFAULT_INPUT = REPO_ROOT / "inputs" / "keyword_input.xlsx"
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "outputs"

def timestamped_output_dir(now: datetime) -> Path:
    base = DEFAULT_OUTPUT_ROOT / now.strftime("%Y%m%d_%H%M%S")
    candidate = base
    suffix = 1
    while candidate.exists():
        candidate = Path(f"{base}_{suffix:02d}")
        suffix += 1
    return candidate
```

Run `extract_keyword_input.mjs` before constructing `SearchAdClient` or `DataLabClient`. Keep secret-safe console output. Use the generic result filename from the interface block.

- [ ] **Step 4: Run orchestrator tests and verify GREEN**

Run the command from Step 2.

Expected: all tests pass and no credential value appears in captured output.

- [ ] **Step 5: Commit the reusable orchestrator**

```powershell
git add -- scripts/run_keyword_volume.py tests/test_run_keyword_volume.py .gitignore
git commit -m "feat: add reusable keyword volume runner"
```

---

### Task 5: One-Command PowerShell Entry Point

**Files:**
- Create: `run_keyword_volume.ps1`
- Create: `tests/test_run_keyword_volume_powershell.py`

**Interfaces:**
- Consumes: no arguments for the normal user workflow.
- Produces: the exit code and output of `.venv\Scripts\python.exe scripts\run_keyword_volume.py`.

- [ ] **Step 1: Write a failing wrapper test**

Run the wrapper against a temporary project input through an environment override used only by tests:

```python
completed = subprocess.run(
    ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "run_keyword_volume.ps1", "-DryRun"],
    capture_output=True,
    text=True,
)
assert completed.returncode == 0
assert "dry_run=true" in completed.stdout
```

- [ ] **Step 2: Run the wrapper test and verify RED**

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.pytest_tmp\wrapper_red tests/test_run_keyword_volume_powershell.py
```

Expected: FAIL because `run_keyword_volume.ps1` does not exist.

- [ ] **Step 3: Implement the wrapper**

Use a typed switch and safe path resolution:

```powershell
param([switch]$DryRun)
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
$runnerPath = Join-Path $projectRoot "scripts\run_keyword_volume.py"
if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    throw "Python virtual environment not found: $pythonPath"
}
$runnerArgs = @($runnerPath)
if ($DryRun) { $runnerArgs += "--dry-run" }
& $pythonPath @runnerArgs
exit $LASTEXITCODE
```

- [ ] **Step 4: Run the wrapper test and verify GREEN**

Run the command from Step 2.

Expected: PASS.

- [ ] **Step 5: Commit the entry point**

```powershell
git add -- run_keyword_volume.ps1 tests/test_run_keyword_volume_powershell.py
git commit -m "feat: add one-command keyword volume workflow"
```

---

### Task 6: Documentation and End-to-End Acceptance

**Files:**
- Create: `README.md`
- Create: `inputs/.gitkeep`
- Modify: `육수당_매장별_로컬SEO_대표키워드_분석_handoff_2026-08-31.md`
- Test: all feature tests

**Interfaces:**
- Documents the exact operator flow and troubleshooting messages from Tasks 1–5.
- Produces one verified dry-run and one verified sample result workbook without committing credentials or generated outputs.

- [ ] **Step 1: Write the operator documentation**

The README quick start must contain these exact actions:

```text
1. templates/keyword_input_template.xlsx를 복사한다.
2. 복사본을 inputs/keyword_input.xlsx로 저장한다.
3. 키워드입력 시트의 예시 행을 삭제하고 매장명과 키워드1~5를 입력한다.
4. 프로젝트 루트에서 .\run_keyword_volume.ps1을 실행한다.
5. 콘솔에 표시된 outputs/YYYYMMDD_HHMMSS 폴더에서 결과를 확인한다.
```

Document `.env` variable names without example secret values. Include troubleshooting for missing file, wrong sheet, duplicate stores, no keyword, retained example row, and keyword6/anchor guidance.

- [ ] **Step 2: Run the complete feature suite**

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.pytest_tmp\reusable_input_final tests/test_keyword_input_extractor.py tests/test_keyword_input_template.py tests/test_run_keyword_volume.py tests/test_run_keyword_volume_powershell.py tests/test_run_yuksudang_daily_keyword_volume.py tests/test_yuksudang_volume_config.py tests/test_yuksudang_volume_datalab.py tests/test_yuksudang_volume_estimation.py tests/test_yuksudang_volume_input.py tests/test_yuksudang_volume_pipeline.py tests/test_yuksudang_volume_searchad.py tests/test_yuksudang_volume_workbook.py
```

Expected: all tests pass with zero failures.

- [ ] **Step 3: Run a dry-run using the committed template copy**

Copy the template to the ignored canonical input path, replace the example row with one controlled store row, and run:

```powershell
.\run_keyword_volume.ps1 -DryRun
```

Expected console fields: `dry_run=true`, `stores=1`, the nonzero keyword slot count, unique keyword count, and a 30-day period. No credential value may appear.

- [ ] **Step 4: Run one live acceptance workbook and verify it**

Use the controlled input and existing `.env`, then run `.\run_keyword_volume.ps1`. Inspect both result sheet header ranges, scan `#REF!|#DIV/0!|#VALUE!|#NAME?|#N/A`, render both result sheets, and reconcile every success keyword to 30 daily rows and exact PC/mobile totals.

- [ ] **Step 5: Verify repository scope and secrets**

```powershell
git diff --check
git status --short
git grep -n -I -E "NAVER_(SEARCHAD|DATALAB).*(secret|key).*=.+" -- . ":(exclude).env.example"
```

Expected: no whitespace errors; only planned files are staged; no credential value is tracked.

- [ ] **Step 6: Commit documentation and acceptance updates**

```powershell
git add -- README.md inputs/.gitkeep 육수당_매장별_로컬SEO_대표키워드_분석_handoff_2026-08-31.md
git commit -m "docs: document reusable keyword volume workflow"
```
