from datetime import date, timedelta

from scripts.yuksudang_volume.pipeline import run_pipeline
from scripts.yuksudang_volume.searchad import SearchVolume


START = date(2026, 8, 3)
END = date(2026, 9, 1)


class FakeSearchAd:
    def __init__(self):
        self.calls: list[list[str]] = []

    def fetch_volumes(self, keywords):
        self.calls.append(list(keywords))
        return {
            keyword: SearchVolume(keyword, 30, 60, "success", 30, 60)
            for keyword in keywords
        }


class FakeDataLab:
    def __init__(self, zero_keyword=None):
        self.zero_keyword = zero_keyword
        self.calls: list[list[str]] = []

    def fetch_daily_ratios(self, keywords, start_date, end_date):
        self.calls.append(list(keywords))
        return {
            keyword: {
                start_date + timedelta(days=i): (
                    0.0 if keyword == self.zero_keyword else 1.0
                )
                for i in range(30)
            }
            for keyword in keywords
        }


def test_pipeline_deduplicates_search_volume_but_keeps_store_slots(tmp_path):
    payload = {
        "source_file": "source.xlsx",
        "stores": [
            {
                "source_row": 3,
                "store_name": "점포A",
                "keywords": [{"slot": "keyword1", "keyword": "공통키워드"}],
            },
            {
                "source_row": 4,
                "store_name": "점포B",
                "keywords": [{"slot": "keyword1", "keyword": "공통 키워드"}],
            },
        ],
    }
    searchad = FakeSearchAd()
    datalab = FakeDataLab()

    result = run_pipeline(payload, searchad, datalab, START, END, tmp_path)

    assert len(searchad.calls) == 1
    assert searchad.calls[0] == ["공통키워드"]
    assert len(result["keywords"]) == 2
    assert len(result["daily_rows"]) == 60
    assert result["summary"]["success_keywords"] == 2
    assert all(row["estimated_total"] == 3 for row in result["daily_rows"])


def test_pipeline_isolates_zero_ratio_keyword(tmp_path):
    payload = {
        "source_file": "source.xlsx",
        "stores": [
            {
                "source_row": 3,
                "store_name": "점포A",
                "keywords": [
                    {"slot": "keyword1", "keyword": "정상"},
                    {"slot": "keyword2", "keyword": "신호없음"},
                    {"slot": "keyword3", "keyword": None},
                ],
            }
        ],
    }

    result = run_pipeline(
        payload,
        FakeSearchAd(),
        FakeDataLab(zero_keyword="신호없음"),
        START,
        END,
        tmp_path,
    )

    by_slot = {row["slot"]: row for row in result["keywords"]}
    assert by_slot["keyword1"]["status"] == "success"
    assert by_slot["keyword2"]["status"] == "datalab_no_data"
    assert by_slot["keyword3"]["status"] == "missing_keyword"
    assert len(result["daily_rows"]) == 30
    assert result["summary"]["failed_keywords"] == 2
