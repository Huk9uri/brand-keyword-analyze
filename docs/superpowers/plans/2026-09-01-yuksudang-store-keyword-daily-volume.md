# 육수당 매장별 키워드 일간 검색량 추정 모델 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 육수당 매장별 키워드1·2·3의 최근 30일 PC·모바일 일간 검색량 추정치를 네이버 검색광고 API와 DataLab API로 계산하고, 원본을 보존한 결과 엑셀을 생성한다.

**Architecture:** Node.js 입력 추출기가 원본 XLSX를 JSON으로 변환하고, Python 코어가 API 수집·캐시·일간 정수 배분을 수행해 결과 JSON을 만든다. Node.js 결과 생성기가 원본 워크북에 요약·상세 시트를 추가하고 값과 레이아웃을 검증한다.

**Tech Stack:** Python 3.12 표준 라이브러리, pytest, Node.js, `@oai/artifact-tool`, 네이버 검색광고 API, 네이버 DataLab API

**Spec:** `docs/superpowers/specs/2026-09-01-yuksudang-store-keyword-daily-volume-design.md`

## Global Constraints

- 입력 시트는 `육수당 키워드검색량0513`이며 매장명 A열, 키워드1 N열, 키워드2 T열, 키워드3 Z열을 사용한다.
- 앵커를 사용하지 않고 키워드별 `30일 검색량 × 일별 ratio ÷ ratio 합`으로 계산한다.
- 성공 키워드의 PC·모바일·전체 일간 합계는 각 최근 30일 검색량과 정확히 일치해야 한다.
- API 비밀값과 인증 헤더를 로그, 테스트 출력, 캐시, JSON, CSV, XLSX에 기록하지 않는다.
- 원본 XLSX는 덮어쓰지 않고 `outputs/<run-id>/` 아래에 새 결과 파일을 생성한다.
- 엑셀 읽기·작성·렌더링에는 로더가 제공한 Node.js와 `@oai/artifact-tool`만 사용한다.
- 네트워크 오류·429·5xx만 제한적으로 재시도하고 401·403 인증 오류는 즉시 중단한다.
- 한 키워드의 데이터 오류는 다른 키워드의 처리를 중단시키지 않는다.

---

## File Map

| 파일 | 책임 |
|---|---|
| `scripts/yuksudang_volume/models.py` | 입력·API·계산 결과 데이터 구조와 상태 상수 |
| `scripts/yuksudang_volume/config.py` | `.env` 파싱 및 필수 설정 검증 |
| `scripts/yuksudang_volume/estimation.py` | ratio 정규화와 최대 나머지 정수 배분 |
| `scripts/yuksudang_volume/searchad.py` | 검색광고 API 서명·요청·응답 파싱 |
| `scripts/yuksudang_volume/datalab.py` | DataLab 요청·30일 series 정규화 |
| `scripts/yuksudang_volume/cache.py` | 비밀정보를 제외한 JSON 캐시 |
| `scripts/yuksudang_volume/pipeline.py` | 매장별 수집·오류 격리·결과 조립 |
| `scripts/run_yuksudang_daily_keyword_volume.py` | 사용자용 단일 실행 CLI와 Node 단계 호출 |
| `scripts/node/extract_yuksudang_keywords.mjs` | XLSX에서 매장명과 키워드1·2·3 추출 |
| `scripts/node/build_yuksudang_volume_workbook.mjs` | 원본 보존 결과 XLSX 생성·검증·렌더링 |
| `tests/test_yuksudang_volume_estimation.py` | 계산 불변조건 테스트 |
| `tests/test_yuksudang_volume_config.py` | 설정·비밀값 보호 테스트 |
| `tests/test_yuksudang_volume_searchad.py` | 서명·검색량 파싱 테스트 |
| `tests/test_yuksudang_volume_datalab.py` | 날짜 채움·ratio 0 처리 테스트 |
| `tests/test_yuksudang_volume_pipeline.py` | 캐시·중복·부분 실패 통합 테스트 |
| `tests/fixtures/yuksudang_volume/*.json` | 비밀값이 없는 고정 API fixture |

---

### Task 1: 계산 코어와 데이터 계약

**Files:**
- Create: `scripts/yuksudang_volume/__init__.py`
- Create: `scripts/yuksudang_volume/models.py`
- Create: `scripts/yuksudang_volume/estimation.py`
- Test: `tests/test_yuksudang_volume_estimation.py`

**Interfaces:**
- Consumes: `monthly_pc: int`, `monthly_mobile: int`, `ratios: dict[date, float]`
- Produces: `allocate_integer_total(total: int, weights: list[float]) -> list[int]`
- Produces: `estimate_daily(monthly_pc: int, monthly_mobile: int, ratios: dict[date, float]) -> list[DailyEstimate]`

- [ ] **Step 1: Write failing tests for exact integer allocation**

```python
from datetime import date, timedelta

import pytest

from scripts.yuksudang_volume.estimation import (
    NoRatioSignalError,
    allocate_integer_total,
    estimate_daily,
)


def test_allocate_integer_total_preserves_total():
    assert allocate_integer_total(10, [1.0, 1.0, 1.0]) == [4, 3, 3]


def test_estimate_daily_preserves_pc_mobile_and_total():
    start = date(2026, 8, 3)
    ratios = {start + timedelta(days=i): float(i + 1) for i in range(30)}
    rows = estimate_daily(2_000, 8_000, ratios)
    assert len(rows) == 30
    assert sum(row.estimated_pc for row in rows) == 2_000
    assert sum(row.estimated_mobile for row in rows) == 8_000
    assert sum(row.estimated_total for row in rows) == 10_000
    assert all(row.estimated_total == row.estimated_pc + row.estimated_mobile for row in rows)


def test_estimate_daily_rejects_zero_ratio_sum():
    ratios = {date(2026, 8, 3) + timedelta(days=i): 0.0 for i in range(30)}
    with pytest.raises(NoRatioSignalError):
        estimate_daily(100, 200, ratios)
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```powershell
python -m pytest tests/test_yuksudang_volume_estimation.py -q
```

Expected: collection fails because `scripts.yuksudang_volume.estimation` does not exist.

- [ ] **Step 3: Implement the data classes and largest-remainder allocator**

```python
# scripts/yuksudang_volume/models.py
from dataclasses import asdict, dataclass
from datetime import date


@dataclass(frozen=True)
class DailyEstimate:
    search_date: date
    ratio: float
    estimated_pc: int
    estimated_mobile: int
    estimated_total: int

    def to_dict(self) -> dict:
        data = asdict(self)
        data["search_date"] = self.search_date.isoformat()
        return data
```

```python
# scripts/yuksudang_volume/estimation.py
from datetime import date
from math import floor

from .models import DailyEstimate


class NoRatioSignalError(ValueError):
    pass


def allocate_integer_total(total: int, weights: list[float]) -> list[int]:
    if total < 0:
        raise ValueError("total must be non-negative")
    weight_sum = sum(weights)
    if weight_sum <= 0:
        raise NoRatioSignalError("ratio sum is zero")
    raw = [total * weight / weight_sum for weight in weights]
    allocated = [floor(value) for value in raw]
    remainder = total - sum(allocated)
    order = sorted(range(len(raw)), key=lambda i: (-(raw[i] - allocated[i]), i))
    for index in order[:remainder]:
        allocated[index] += 1
    return allocated


def estimate_daily(
    monthly_pc: int,
    monthly_mobile: int,
    ratios: dict[date, float],
) -> list[DailyEstimate]:
    ordered = sorted(ratios.items())
    weights = [ratio for _, ratio in ordered]
    pc = allocate_integer_total(monthly_pc, weights)
    mobile = allocate_integer_total(monthly_mobile, weights)
    return [
        DailyEstimate(day, ratio, pc_value, mobile_value, pc_value + mobile_value)
        for (day, ratio), pc_value, mobile_value in zip(ordered, pc, mobile)
    ]
```

- [ ] **Step 4: Run tests and verify GREEN**

Run: `python -m pytest tests/test_yuksudang_volume_estimation.py -q`

Expected: 3 passed.

- [ ] **Step 5: Commit the calculation core**

```powershell
git add -- scripts/yuksudang_volume/__init__.py scripts/yuksudang_volume/models.py scripts/yuksudang_volume/estimation.py tests/test_yuksudang_volume_estimation.py
git commit -m "feat: add daily keyword volume estimator"
```

---

### Task 2: 환경설정과 비밀정보 보호

**Files:**
- Create: `scripts/yuksudang_volume/config.py`
- Test: `tests/test_yuksudang_volume_config.py`
- Create: `.gitignore`

**Interfaces:**
- Consumes: `.env` path
- Produces: `NaverConfig.from_env_file(path: Path) -> NaverConfig`
- Produces: `NaverConfig.redacted() -> dict[str, str]`

- [ ] **Step 1: Write failing configuration tests**

```python
from pathlib import Path

import pytest

from scripts.yuksudang_volume.config import ConfigError, NaverConfig


def test_loads_required_naver_keys_without_exposing_values(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text(
        "NAVER_SEARCHAD_CUSTOMER_ID=123\n"
        "NAVER_SEARCHAD_API_KEY=license\n"
        "NAVER_SEARCHAD_SECRET_KEY=secret\n"
        "NAVER_DATALAB_CLIENT_ID=client\n"
        "NAVER_DATALAB_CLIENT_SECRET=client-secret\n",
        encoding="utf-8",
    )
    config = NaverConfig.from_env_file(env)
    rendered = repr(config) + str(config.redacted())
    assert "license" not in rendered
    assert "client-secret" not in rendered


def test_missing_required_key_raises(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text("NAVER_SEARCHAD_CUSTOMER_ID=123\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="NAVER_SEARCHAD_API_KEY"):
        NaverConfig.from_env_file(env)
```

- [ ] **Step 2: Run test and verify RED**

Run: `python -m pytest tests/test_yuksudang_volume_config.py -q`

Expected: import fails because `config.py` does not exist.

- [ ] **Step 3: Implement strict `.env` parsing and redaction**

```python
from dataclasses import dataclass
from pathlib import Path


class ConfigError(ValueError):
    pass


@dataclass(frozen=True, repr=False)
class NaverConfig:
    searchad_customer_id: str
    searchad_api_key: str
    searchad_secret_key: str
    datalab_client_id: str
    datalab_client_secret: str

    @classmethod
    def from_env_file(cls, path: Path) -> "NaverConfig":
        values: dict[str, str] = {}
        for raw in path.read_text(encoding="utf-8-sig").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
        names = {
            "searchad_customer_id": "NAVER_SEARCHAD_CUSTOMER_ID",
            "searchad_api_key": "NAVER_SEARCHAD_API_KEY",
            "searchad_secret_key": "NAVER_SEARCHAD_SECRET_KEY",
            "datalab_client_id": "NAVER_DATALAB_CLIENT_ID",
            "datalab_client_secret": "NAVER_DATALAB_CLIENT_SECRET",
        }
        missing = [env_name for env_name in names.values() if not values.get(env_name)]
        if missing:
            raise ConfigError("missing environment keys: " + ", ".join(missing))
        return cls(**{field: values[env_name] for field, env_name in names.items()})

    def redacted(self) -> dict[str, str]:
        return {
            "searchad_customer_id": self.searchad_customer_id,
            "searchad_api_key": "***",
            "searchad_secret_key": "***",
            "datalab_client_id": "***",
            "datalab_client_secret": "***",
        }

    def __repr__(self) -> str:
        return f"NaverConfig({self.redacted()!r})"
```

- [ ] **Step 4: Add ignore rules before any API run**

```gitignore
.env
.cache/
tmp/
outputs/
__pycache__/
*.pyc
```

- [ ] **Step 5: Run tests and verify tracked files do not contain secrets**

Run:

```powershell
python -m pytest tests/test_yuksudang_volume_config.py -q
git grep -n -E 'NAVER_(SEARCHAD|DATALAB).*(secret|license|client-secret)' -- ':!docs/superpowers/plans/*'
```

Expected: 2 passed; `git grep` prints no credential values.

- [ ] **Step 6: Commit configuration safety**

```powershell
git add -- .gitignore scripts/yuksudang_volume/config.py tests/test_yuksudang_volume_config.py
git commit -m "feat: add protected Naver API configuration"
```

---

### Task 3: 검색광고 API 클라이언트

**Files:**
- Create: `scripts/yuksudang_volume/searchad.py`
- Test: `tests/test_yuksudang_volume_searchad.py`
- Create: `tests/fixtures/yuksudang_volume/searchad_keywordstool.json`

**Interfaces:**
- Consumes: `NaverConfig`, keyword list
- Produces: `SearchVolume(keyword: str, pc: int | None, mobile: int | None, status: str, raw_pc: str | int | None, raw_mobile: str | int | None)`
- Produces: `SearchAdClient.fetch_volumes(keywords: list[str]) -> dict[str, SearchVolume]`

- [ ] **Step 1: Add a secret-free response fixture**

```json
{
  "keywordList": [
    {"relKeyword": "문래동", "monthlyPcQcCnt": 4560, "monthlyMobileQcCnt": 15300},
    {"relKeyword": "문래SKV1center", "monthlyPcQcCnt": "< 10", "monthlyMobileQcCnt": 100}
  ]
}
```

- [ ] **Step 2: Write failing signature and parser tests**

```python
import json
from pathlib import Path

from scripts.yuksudang_volume.searchad import build_signature, parse_keyword_rows


def test_build_signature_is_stable():
    assert build_signature("1700000000000", "GET", "/keywordstool", "secret") == "A6Gzu+sW9C2ovLsH+T+rFrie81KwHy1xrodUFQERKf4="


def test_parse_keyword_rows_preserves_low_volume_state():
    payload = json.loads(Path("tests/fixtures/yuksudang_volume/searchad_keywordstool.json").read_text(encoding="utf-8"))
    rows = parse_keyword_rows(payload, ["문래동", "문래 SK V1 center"])
    assert rows["문래동"].pc == 4560
    assert rows["문래 SK V1 center"].pc is None
    assert rows["문래 SK V1 center"].status == "searchad_low_volume"
```

- [ ] **Step 3: Run test and verify RED**

Run: `python -m pytest tests/test_yuksudang_volume_searchad.py -q`

Expected: import fails because `searchad.py` does not exist.

- [ ] **Step 4: Implement signing, normalization and parsing**

```python
import base64
import hashlib
import hmac
import re
from dataclasses import dataclass


def normalize_keyword(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()


def build_signature(timestamp: str, method: str, uri: str, secret_key: str) -> str:
    message = f"{timestamp}.{method}.{uri}".encode()
    digest = hmac.new(secret_key.encode(), message, hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


@dataclass(frozen=True)
class SearchVolume:
    keyword: str
    pc: int | None
    mobile: int | None
    status: str
    raw_pc: str | int | None
    raw_mobile: str | int | None


def _count(value):
    return value if isinstance(value, int) else None


def parse_keyword_rows(payload: dict, requested: list[str]) -> dict[str, SearchVolume]:
    by_normalized = {normalize_keyword(row.get("relKeyword", "")): row for row in payload.get("keywordList", [])}
    result = {}
    for keyword in requested:
        row = by_normalized.get(normalize_keyword(keyword))
        if not row:
            result[keyword] = SearchVolume(keyword, None, None, "searchad_no_data", None, None)
            continue
        raw_pc = row.get("monthlyPcQcCnt")
        raw_mobile = row.get("monthlyMobileQcCnt")
        pc, mobile = _count(raw_pc), _count(raw_mobile)
        status = "success" if pc is not None and mobile is not None else "searchad_low_volume"
        result[keyword] = SearchVolume(keyword, pc, mobile, status, raw_pc, raw_mobile)
    return result
```

Implement `SearchAdClient` with `urllib.request`, headers `X-Timestamp`, `X-API-KEY`, `X-Customer`, `X-Signature`, a five-keyword request chunk, and retry delays `1, 2, 4` seconds for 429 and 5xx only.

- [ ] **Step 5: Run unit tests and a one-keyword connectivity probe**

Run:

```powershell
python -m pytest tests/test_yuksudang_volume_searchad.py -q
python scripts/run_yuksudang_daily_keyword_volume.py --input "C:\Users\user1\Downloads\육수당_매장별 대표키워드 적용 5가지 산출 (1).xlsx" --store "육수당 문래SK점" --dry-run
```

Expected: unit tests pass; dry-run reports three extracted keywords and one deduplicated search-ad request group without printing credentials.

- [ ] **Step 6: Commit the search-ad client**

```powershell
git add -- scripts/yuksudang_volume/searchad.py tests/test_yuksudang_volume_searchad.py tests/fixtures/yuksudang_volume/searchad_keywordstool.json
git commit -m "feat: add Naver search volume client"
```

---

### Task 4: DataLab 클라이언트와 30일 날짜 정규화

**Files:**
- Create: `scripts/yuksudang_volume/datalab.py`
- Test: `tests/test_yuksudang_volume_datalab.py`
- Create: `tests/fixtures/yuksudang_volume/datalab_search.json`

**Interfaces:**
- Consumes: `NaverConfig`, `keywords: list[str]`, `start_date: date`, `end_date: date`
- Produces: `DataLabClient.fetch_daily_ratios(...) -> dict[str, dict[date, float]]`
- Produces: `normalize_series(payload, keywords, start_date, end_date) -> dict[str, dict[date, float]]`

- [ ] **Step 1: Add a fixture with a missing date and a zero-only group**

```json
{
  "results": [
    {"title": "문래동", "keywords": ["문래동"], "data": [{"period": "2026-08-03", "ratio": 10.0}, {"period": "2026-08-05", "ratio": 20.0}]},
    {"title": "문래역", "keywords": ["문래역"], "data": []}
  ]
}
```

- [ ] **Step 2: Write failing normalization tests**

```python
import json
from datetime import date
from pathlib import Path

from scripts.yuksudang_volume.datalab import normalize_series


def test_normalize_series_fills_missing_dates_with_zero():
    payload = json.loads(Path("tests/fixtures/yuksudang_volume/datalab_search.json").read_text(encoding="utf-8"))
    result = normalize_series(payload, ["문래동", "문래역"], date(2026, 8, 3), date(2026, 8, 5))
    assert list(result["문래동"].values()) == [10.0, 0.0, 20.0]
    assert list(result["문래역"].values()) == [0.0, 0.0, 0.0]
```

- [ ] **Step 3: Run test and verify RED**

Run: `python -m pytest tests/test_yuksudang_volume_datalab.py -q`

Expected: import fails because `datalab.py` does not exist.

- [ ] **Step 4: Implement the DataLab request and exact date grid**

Use request body:

```python
payload = {
    "startDate": start_date.isoformat(),
    "endDate": end_date.isoformat(),
    "timeUnit": "date",
    "keywordGroups": [
        {"groupName": keyword, "keywords": [keyword]}
        for keyword in unique_keywords
    ],
}
```

Create every date from `start_date` through `end_date`, initialize to `0.0`, and overwrite dates present in the response. Use headers `X-Naver-Client-Id` and `X-Naver-Client-Secret`. Retry only 429 and 5xx with delays `1, 2, 4` seconds.

- [ ] **Step 5: Run tests and verify GREEN**

Run: `python -m pytest tests/test_yuksudang_volume_datalab.py -q`

Expected: test passes.

- [ ] **Step 6: Commit the DataLab client**

```powershell
git add -- scripts/yuksudang_volume/datalab.py tests/test_yuksudang_volume_datalab.py tests/fixtures/yuksudang_volume/datalab_search.json
git commit -m "feat: add Naver DataLab daily ratio client"
```

---

### Task 5: Node.js 원본 엑셀 입력 추출기

**Files:**
- Create: `scripts/node/extract_yuksudang_keywords.mjs`
- Create: `tests/fixtures/yuksudang_volume/sample_input.json`
- Test: `tests/test_yuksudang_volume_input.py`

**Interfaces:**
- Consumes: `--input <xlsx> --output <json> [--store <name>]`
- Produces JSON: `{"source_file": str, "sheet": str, "stores": [{"store_name": str, "keywords": [{"slot": "keyword1|keyword2|keyword3", "keyword": str|null}]}]}`

- [ ] **Step 1: Write a failing CLI contract test**

```python
import json
import subprocess
from pathlib import Path


def test_extractor_returns_three_keyword_slots(tmp_path: Path):
    output = tmp_path / "input.json"
    subprocess.run(
        [
            "node",
            "scripts/node/extract_yuksudang_keywords.mjs",
            "--input",
            r"C:\Users\user1\Downloads\육수당_매장별 대표키워드 적용 5가지 산출 (1).xlsx",
            "--output",
            str(output),
            "--store",
            "육수당 문래SK점",
        ],
        check=True,
    )
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["stores"][0]["store_name"] == "육수당 문래SK점"
    assert [item["keyword"] for item in data["stores"][0]["keywords"]] == ["문래동", "문래역", "문래 SK V1 center"]
```

- [ ] **Step 2: Run test and verify RED**

Run: `python -m pytest tests/test_yuksudang_volume_input.py -q`

Expected: Node script is missing.

- [ ] **Step 3: Implement workbook import and fixed column extraction**

Use `FileBlob.load()` and `SpreadsheetFile.importXlsx()`. Read rows 3 through the used range and map zero-based indexes `0`, `13`, `19`, `25` to store name, keyword1, keyword2, keyword3. Trim strings, convert blank values to `null`, preserve the original keyword display string, and write UTF-8 JSON.

Reject the workbook when:

- the sheet does not exist;
- A2, N2, T2, Z2 do not contain the expected header labels;
- no store rows are found;
- `--store` does not match any row exactly.

- [ ] **Step 4: Run the focused extraction test**

Run: `python -m pytest tests/test_yuksudang_volume_input.py -q`

Expected: test passes with the three exact 문래SK점 keywords.

- [ ] **Step 5: Commit the input extractor**

```powershell
git add -- scripts/node/extract_yuksudang_keywords.mjs tests/test_yuksudang_volume_input.py
git commit -m "feat: extract store keyword slots from workbook"
```

---

### Task 6: 캐시와 Python 파이프라인

**Files:**
- Create: `scripts/yuksudang_volume/cache.py`
- Create: `scripts/yuksudang_volume/pipeline.py`
- Test: `tests/test_yuksudang_volume_pipeline.py`

**Interfaces:**
- Consumes: input JSON, `SearchAdClient`, `DataLabClient`, date range, cache directory
- Produces: `run_pipeline(...) -> dict` matching the result schema below
- Produces result JSON with `metadata`, `summary`, `keywords`, and `daily_rows`

- [ ] **Step 1: Write failing orchestration tests with fake clients**

```python
from datetime import date, timedelta

from scripts.yuksudang_volume.pipeline import run_pipeline
from scripts.yuksudang_volume.searchad import SearchVolume


class FakeSearchAd:
    calls = 0

    def fetch_volumes(self, keywords):
        self.calls += 1
        return {keyword: SearchVolume(keyword, 30, 60, "success", 30, 60) for keyword in keywords}


class FakeDataLab:
    def fetch_daily_ratios(self, keywords, start_date, end_date):
        return {
            keyword: {start_date + timedelta(days=i): 1.0 for i in range(30)}
            for keyword in keywords
        }


def test_pipeline_deduplicates_search_volume_but_keeps_store_slots(tmp_path):
    payload = {
        "source_file": "source.xlsx",
        "stores": [
            {"store_name": "점포A", "keywords": [{"slot": "keyword1", "keyword": "공통키워드"}]},
            {"store_name": "점포B", "keywords": [{"slot": "keyword1", "keyword": "공통키워드"}]},
        ],
    }
    searchad = FakeSearchAd()
    result = run_pipeline(payload, searchad, FakeDataLab(), date(2026, 8, 3), date(2026, 9, 1), tmp_path)
    assert searchad.calls == 1
    assert len(result["keywords"]) == 2
    assert len(result["daily_rows"]) == 60
```

Add tests where one keyword has zero ratios and verify its status is `datalab_no_data` while another keyword succeeds.

- [ ] **Step 2: Run pipeline tests and verify RED**

Run: `python -m pytest tests/test_yuksudang_volume_pipeline.py -q`

Expected: missing `pipeline.py` and `cache.py`.

- [ ] **Step 3: Implement secret-free atomic JSON cache**

Cache only parsed business data:

```json
{
  "cache_version": 1,
  "collected_at": "2026-09-01T12:00:00+09:00",
  "request_key": "sha256-of-non-secret-request-fields",
  "data": {}
}
```

Write to a sibling `.tmp` file and use `Path.replace()` for atomic replacement. Never cache request headers or config objects.

- [ ] **Step 4: Implement pipeline ordering and status isolation**

Algorithm:

1. Flatten nonblank slots while retaining store and slot.
2. Deduplicate normalized keywords for SearchAd lookup.
3. Request DataLab per store using that store's unique nonblank keywords.
4. For each slot, join monthly volume and ratio series.
5. Run `estimate_daily()` when both sources are valid.
6. Append one summary row per original slot and 30 detail rows per successful slot.
7. Append a failed summary row and no fabricated daily rows for failed slots.
8. Sort summaries by source row and slot; sort details by source row, slot, date.

- [ ] **Step 5: Run focused and full Python tests**

Run:

```powershell
python -m pytest tests/test_yuksudang_volume_pipeline.py -q
python -m pytest tests/test_yuksudang_volume_*.py -q
```

Expected: all new Python tests pass.

- [ ] **Step 6: Commit the pipeline**

```powershell
git add -- scripts/yuksudang_volume/cache.py scripts/yuksudang_volume/pipeline.py tests/test_yuksudang_volume_pipeline.py
git commit -m "feat: orchestrate store keyword volume collection"
```

---

### Task 7: 결과 워크북 생성과 시각 검증

**Files:**
- Create: `scripts/node/build_yuksudang_volume_workbook.mjs`
- Test: `tests/test_yuksudang_volume_workbook.py`

**Interfaces:**
- Consumes: `--input <source.xlsx> --results <result.json> --output <result.xlsx> --preview-dir <dir>`
- Produces: result XLSX plus PNG previews for `30일_키워드요약` and `30일_일간검색량`

- [ ] **Step 1: Write a failing workbook integration test**

```python
import json
import subprocess
from pathlib import Path


def test_builder_creates_result_workbook(tmp_path: Path):
    results = tmp_path / "results.json"
    results.write_text(json.dumps({
        "metadata": {"period_start": "2026-08-03", "period_end": "2026-09-01", "model_version": "v1"},
        "summary": {"stores": 1, "success_keywords": 1, "failed_keywords": 0},
        "keywords": [{"store_name": "육수당 문래SK점", "slot": "keyword1", "keyword": "문래동", "monthly_pc": 30, "monthly_mobile": 60, "monthly_total": 90, "estimated_total": 90, "daily_average": 3.0, "peak_date": "2026-08-03", "peak_volume": 3, "ratio_sum": 30.0, "status": "success", "error_reason": ""}],
        "daily_rows": [{"store_name": "육수당 문래SK점", "slot": "keyword1", "keyword": "문래동", "search_date": "2026-08-03", "monthly_pc": 30, "monthly_mobile": 60, "monthly_total": 90, "ratio": 1.0, "estimated_pc": 1, "estimated_mobile": 2, "estimated_total": 3, "status": "success", "error_reason": ""}],
    }, ensure_ascii=False), encoding="utf-8")
    output = tmp_path / "result.xlsx"
    subprocess.run(["node", "scripts/node/build_yuksudang_volume_workbook.mjs", "--input", r"C:\Users\user1\Downloads\육수당_매장별 대표키워드 적용 5가지 산출 (1).xlsx", "--results", str(results), "--output", str(output), "--preview-dir", str(tmp_path / "preview")], check=True)
    assert output.exists() and output.stat().st_size > 0
```

- [ ] **Step 2: Run test and verify RED**

Run: `python -m pytest tests/test_yuksudang_volume_workbook.py -q`

Expected: builder script is missing.

- [ ] **Step 3: Implement the two result sheets**

Use `@oai/artifact-tool` to import the original workbook. Delete pre-existing sheets named `30일_키워드요약` or `30일_일간검색량` only in the in-memory output copy, then recreate them.

Formatting requirements:

- dark blue title/header fill matching the source workbook's business-report style;
- white bold header text;
- filters on the tabular range;
- first row frozen;
- dates formatted `yyyy-mm-dd`;
- counts formatted `#,##0`, ratios `0.00`, averages `#,##0.0`;
- text columns left aligned, numeric columns right aligned;
- status cells conditionally colored: success green, failure red;
- capped widths so headers and Korean store names are visible without excessive whitespace.

At the top of the summary sheet, add metadata rows for period, model version, source file, collection time, success count and failure count. Do not write secrets or full API responses.

- [ ] **Step 4: Add programmatic verification before export**

Inspect:

```javascript
await workbook.inspect({
  kind: "table",
  sheetId: "30일_키워드요약",
  range: "A1:M20",
  include: "values,formulas",
  tableMaxRows: 20,
  tableMaxCols: 13,
});
```

Scan for `#REF!|#DIV/0!|#VALUE!|#NAME\?|#N/A`, render both result sheets, save previews, and fail the process if either result sheet is missing or contains no result rows.

- [ ] **Step 5: Run the workbook test and inspect previews**

Run: `python -m pytest tests/test_yuksudang_volume_workbook.py -q`

Expected: test passes, output workbook exists, and both PNG previews are generated.

- [ ] **Step 6: Commit workbook generation**

```powershell
git add -- scripts/node/build_yuksudang_volume_workbook.mjs tests/test_yuksudang_volume_workbook.py
git commit -m "feat: build verified daily volume workbook"
```

---

### Task 8: 단일 실행 CLI와 실 API 파일럿

**Files:**
- Create: `scripts/run_yuksudang_daily_keyword_volume.py`
- Test: `tests/test_run_yuksudang_daily_keyword_volume.py`
- Modify: `육수당_매장별_로컬SEO_대표키워드_분석_handoff_2026-08-31.md`

**Interfaces:**
- Consumes CLI: `--input`, `--end-date`, `--output-dir`, `--store`, `--force-refresh`, `--dry-run`
- Produces: redacted console summary, input JSON, result JSON, result XLSX and two preview PNGs

- [ ] **Step 1: Write failing CLI dry-run test**

```python
import subprocess


def test_cli_dry_run_does_not_print_secrets():
    completed = subprocess.run(
        ["python", "scripts/run_yuksudang_daily_keyword_volume.py", "--input", r"C:\Users\user1\Downloads\육수당_매장별 대표키워드 적용 5가지 산출 (1).xlsx", "--store", "육수당 문래SK점", "--end-date", "2026-09-01", "--dry-run"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "stores=1" in completed.stdout
    assert "keyword_slots=3" in completed.stdout
    assert "NAVER_SEARCHAD_SECRET_KEY" not in completed.stdout
```

- [ ] **Step 2: Run test and verify RED**

Run: `python -m pytest tests/test_run_yuksudang_daily_keyword_volume.py -q`

Expected: runner script is missing.

- [ ] **Step 3: Implement orchestration and safe subprocess calls**

Use `subprocess.run([...], check=True)` with argument arrays, never shell-built command strings. Resolve the bundled Node executable and node module path from environment/configuration documented for the workspace. Create a unique output directory before execution and pass explicit JSON paths between stages.

Dry-run sequence:

1. validate `.env`;
2. extract input JSON;
3. report store count, slot count, unique keyword count and expected DataLab request count;
4. stop before any HTTP request.

Normal sequence:

1. extract input;
2. call SearchAd and DataLab through the Python pipeline;
3. write result JSON atomically;
4. build and verify result workbook;
5. print only output paths and counts.

- [ ] **Step 4: Run all offline tests**

Run:

```powershell
python -m pytest tests/test_yuksudang_volume_*.py tests/test_run_yuksudang_daily_keyword_volume.py -q
```

Expected: all new tests pass with no network calls.

- [ ] **Step 5: Run a one-store live API pilot**

Run:

```powershell
python scripts/run_yuksudang_daily_keyword_volume.py --input "C:\Users\user1\Downloads\육수당_매장별 대표키워드 적용 5가지 산출 (1).xlsx" --store "육수당 문래SK점" --end-date 2026-09-01 --output-dir outputs/yuksudang-volume-pilot
```

Verify:

- three keyword summaries exist or carry explicit API data states;
- every successful keyword has 30 detail rows;
- PC, mobile and total daily sums equal monthly values;
- no credential value appears in output text or result files;
- preview images show readable, non-clipped headers and numbers.

- [ ] **Step 6: Run the full workbook only after pilot verification**

Run:

```powershell
python scripts/run_yuksudang_daily_keyword_volume.py --input "C:\Users\user1\Downloads\육수당_매장별 대표키워드 적용 5가지 산출 (1).xlsx" --end-date 2026-09-01 --output-dir outputs/yuksudang-volume-2026-09-01
```

Expected summary checks:

- store count equals the number of populated source rows;
- keyword summary row count equals all three source slots, including explicit missing/error states;
- successful detail row count equals `success_keywords × 30`;
- no successful keyword violates monthly-to-daily reconciliation.

- [ ] **Step 7: Update the handoff with actual run commands and limitations**

Add:

- exact CLI examples;
- output sheet definitions;
- live pilot and full-run counts;
- low-volume value policy observed from the real SearchAd response;
- DataLab zero-series count;
- cache refresh instructions;
- output path.

- [ ] **Step 8: Run final verification**

Run:

```powershell
python -m pytest -q
git diff --check
git status --short
```

Expected: all tests pass, no whitespace errors, only intended implementation and documentation changes are present.

- [ ] **Step 9: Commit the completed workflow**

```powershell
git add -- scripts/run_yuksudang_daily_keyword_volume.py tests/test_run_yuksudang_daily_keyword_volume.py 육수당_매장별_로컬SEO_대표키워드_분석_handoff_2026-08-31.md
git commit -m "feat: add end-to-end store keyword volume workflow"
```

---

## Final Acceptance Checklist

- [ ] `.env` is ignored and no credential is tracked.
- [ ] Dry-run performs no HTTP requests.
- [ ] One-store pilot completes before full execution.
- [ ] SearchAd monthly values and DataLab ratios retain raw diagnostic fields without secrets.
- [ ] Every successful keyword has exactly 30 ordered dates.
- [ ] PC, mobile and total daily sums reconcile exactly to their monthly values.
- [ ] Failed and low-volume keywords have explicit, non-fabricated statuses.
- [ ] Original workbook sheets remain present and unchanged in the output copy.
- [ ] `30일_키워드요약` and `30일_일간검색량` are present, populated and visually verified.
- [ ] Full offline test suite and `git diff --check` pass.
