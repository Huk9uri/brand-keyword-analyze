from datetime import date, datetime
from pathlib import Path

from .cache import JsonCache
from .datalab import DataLabAuthError, DataLabError
from .estimation import NoRatioSignalError, estimate_daily
from .searchad import SearchVolume, normalize_keyword


MODEL_VERSION = "daily-ratio-allocation-v1"


def _unique_keywords(stores: list[dict]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for store in stores:
        for item in store.get("keywords", []):
            keyword = str(item.get("keyword") or "").strip()
            normalized = normalize_keyword(keyword)
            if normalized and normalized not in seen:
                seen.add(normalized)
                unique.append(keyword)
    return unique


def _search_volume_to_dict(volume: SearchVolume) -> dict:
    return {
        "keyword": volume.keyword,
        "pc": volume.pc,
        "mobile": volume.mobile,
        "status": volume.status,
        "raw_pc": volume.raw_pc,
        "raw_mobile": volume.raw_mobile,
    }


def _search_volume_from_dict(data: dict) -> SearchVolume:
    return SearchVolume(
        keyword=data["keyword"],
        pc=data.get("pc"),
        mobile=data.get("mobile"),
        status=data["status"],
        raw_pc=data.get("raw_pc"),
        raw_mobile=data.get("raw_mobile"),
    )


def _fetch_search_volumes(
    searchad_client,
    keywords: list[str],
    cache: JsonCache,
    end_date: date,
    force_refresh: bool,
) -> dict[str, SearchVolume]:
    key = cache.key(
        "searchad",
        {"keywords": [normalize_keyword(value) for value in keywords], "as_of": end_date.isoformat()},
    )
    cached = None if force_refresh else cache.load(key)
    if isinstance(cached, list):
        return {
            normalize_keyword(item["keyword"]): _search_volume_from_dict(item)
            for item in cached
        }

    fetched = searchad_client.fetch_volumes(keywords)
    values = list(fetched.values())
    cache.store(key, [_search_volume_to_dict(value) for value in values])
    return {normalize_keyword(value.keyword): value for value in values}


def _fetch_store_ratios(
    datalab_client,
    store_name: str,
    keywords: list[str],
    start_date: date,
    end_date: date,
    cache: JsonCache,
    force_refresh: bool,
) -> dict[str, dict[date, float]]:
    key = cache.key(
        "datalab",
        {
            "store": store_name,
            "keywords": [normalize_keyword(value) for value in keywords],
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        },
    )
    cached = None if force_refresh else cache.load(key)
    if isinstance(cached, dict):
        return {
            keyword: {date.fromisoformat(day): float(ratio) for day, ratio in series.items()}
            for keyword, series in cached.items()
        }

    fetched = datalab_client.fetch_daily_ratios(keywords, start_date, end_date)
    cache.store(
        key,
        {
            keyword: {day.isoformat(): ratio for day, ratio in series.items()}
            for keyword, series in fetched.items()
        },
    )
    return fetched


def _failed_summary(store: dict, item: dict, status: str, reason: str) -> dict:
    return {
        "source_row": store.get("source_row"),
        "store_name": store.get("store_name", ""),
        "slot": item.get("slot", ""),
        "keyword": item.get("keyword"),
        "monthly_pc": None,
        "monthly_mobile": None,
        "monthly_total": None,
        "raw_pc": None,
        "raw_mobile": None,
        "estimated_total": None,
        "daily_average": None,
        "peak_date": None,
        "peak_volume": None,
        "ratio_sum": None,
        "status": status,
        "error_reason": reason,
    }


def run_pipeline(
    payload: dict,
    searchad_client,
    datalab_client,
    start_date: date,
    end_date: date,
    cache_dir: Path,
    *,
    force_refresh: bool = False,
) -> dict:
    stores = payload.get("stores", [])
    cache = JsonCache(cache_dir)
    unique_keywords = _unique_keywords(stores)
    volumes = _fetch_search_volumes(
        searchad_client,
        unique_keywords,
        cache,
        end_date,
        force_refresh,
    ) if unique_keywords else {}

    summaries: list[dict] = []
    daily_rows: list[dict] = []

    for store in stores:
        valid_items = [
            item
            for item in store.get("keywords", [])
            if str(item.get("keyword") or "").strip()
        ]
        store_keywords: list[str] = []
        seen: set[str] = set()
        for item in valid_items:
            keyword = str(item["keyword"]).strip()
            normalized = normalize_keyword(keyword)
            if normalized not in seen:
                seen.add(normalized)
                store_keywords.append(keyword)

        ratio_error: str | None = None
        try:
            store_ratios = _fetch_store_ratios(
                datalab_client,
                store.get("store_name", ""),
                store_keywords,
                start_date,
                end_date,
                cache,
                force_refresh,
            ) if store_keywords else {}
        except DataLabAuthError:
            raise
        except DataLabError as error:
            store_ratios = {}
            ratio_error = str(error)

        ratios_by_normalized = {
            normalize_keyword(keyword): series
            for keyword, series in store_ratios.items()
        }

        for item in store.get("keywords", []):
            keyword = str(item.get("keyword") or "").strip()
            if not keyword:
                summaries.append(
                    _failed_summary(store, item, "missing_keyword", "source keyword is blank")
                )
                continue

            normalized = normalize_keyword(keyword)
            volume = volumes.get(normalized)
            if volume is None or volume.status != "success":
                summary = _failed_summary(
                    store,
                    item,
                    volume.status if volume else "searchad_no_data",
                    "SearchAd did not return numeric PC and mobile volumes",
                )
                if volume:
                    summary.update(
                        {
                            "monthly_pc": volume.pc,
                            "monthly_mobile": volume.mobile,
                            "raw_pc": volume.raw_pc,
                            "raw_mobile": volume.raw_mobile,
                        }
                    )
                summaries.append(summary)
                continue

            if ratio_error:
                summaries.append(
                    _failed_summary(store, item, "partial_api_error", ratio_error)
                )
                continue

            ratios = ratios_by_normalized.get(normalized, {})
            try:
                estimates = estimate_daily(volume.pc or 0, volume.mobile or 0, ratios)
            except NoRatioSignalError:
                summary = _failed_summary(
                    store,
                    item,
                    "datalab_no_data",
                    "DataLab ratio sum is zero",
                )
                summary.update(
                    {
                        "monthly_pc": volume.pc,
                        "monthly_mobile": volume.mobile,
                        "monthly_total": volume.total,
                        "raw_pc": volume.raw_pc,
                        "raw_mobile": volume.raw_mobile,
                        "ratio_sum": sum(ratios.values()),
                    }
                )
                summaries.append(summary)
                continue

            peak = max(estimates, key=lambda row: (row.estimated_total, -row.search_date.toordinal()))
            summary = {
                "source_row": store.get("source_row"),
                "store_name": store.get("store_name", ""),
                "slot": item.get("slot", ""),
                "keyword": keyword,
                "monthly_pc": volume.pc,
                "monthly_mobile": volume.mobile,
                "monthly_total": volume.total,
                "raw_pc": volume.raw_pc,
                "raw_mobile": volume.raw_mobile,
                "estimated_total": sum(row.estimated_total for row in estimates),
                "daily_average": volume.total / len(estimates),
                "peak_date": peak.search_date.isoformat(),
                "peak_volume": peak.estimated_total,
                "ratio_sum": sum(ratios.values()),
                "status": "success",
                "error_reason": "",
            }
            summaries.append(summary)
            for estimate in estimates:
                daily_rows.append(
                    {
                        "source_row": store.get("source_row"),
                        "store_name": store.get("store_name", ""),
                        "slot": item.get("slot", ""),
                        "keyword": keyword,
                        "search_date": estimate.search_date.isoformat(),
                        "monthly_pc": volume.pc,
                        "monthly_mobile": volume.mobile,
                        "monthly_total": volume.total,
                        "ratio": estimate.ratio,
                        "estimated_pc": estimate.estimated_pc,
                        "estimated_mobile": estimate.estimated_mobile,
                        "estimated_total": estimate.estimated_total,
                        "status": "success",
                        "error_reason": "",
                    }
                )

    slot_order = {"keyword1": 1, "keyword2": 2, "keyword3": 3}
    summaries.sort(key=lambda row: (row.get("source_row") or 0, slot_order.get(row["slot"], 99)))
    daily_rows.sort(
        key=lambda row: (
            row.get("source_row") or 0,
            slot_order.get(row["slot"], 99),
            row["search_date"],
        )
    )
    success_count = sum(row["status"] == "success" for row in summaries)
    return {
        "metadata": {
            "source_file": payload.get("source_file"),
            "source_sheet": payload.get("sheet"),
            "period_start": start_date.isoformat(),
            "period_end": end_date.isoformat(),
            "collected_at": datetime.now().astimezone().isoformat(),
            "model_version": MODEL_VERSION,
        },
        "summary": {
            "stores": len(stores),
            "keyword_slots": len(summaries),
            "success_keywords": success_count,
            "failed_keywords": len(summaries) - success_count,
            "daily_rows": len(daily_rows),
        },
        "keywords": summaries,
        "daily_rows": daily_rows,
    }
