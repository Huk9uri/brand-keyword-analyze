import json

import pytest

from scripts.keyword_candidate_discovery.batch import (
    build_store_external_keywords,
    load_batch_plan,
    run_batch_plan,
)
from scripts.keyword_candidate_discovery.extractor import RuleBasedExtractor
from scripts.keyword_candidate_discovery.models import AnalysisWindow
from scripts.keyword_candidate_discovery.batch_cli import parse_args


def test_batch_plan_applies_same_brand_menus_and_related_terms_to_every_store(tmp_path):
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps({
        "brand_code": "01",
        "as_of": "2026-09-09",
        "months": 12,
        "brand_menus": ["설렁탕", "왕갈비탕"],
        "stores": [
            {"store_name": "부천본점", "place_id": "12012595"},
            {"store_name": "강동점", "place_id": "11627699"},
        ],
    }, ensure_ascii=False), encoding="utf-8")

    plan = load_batch_plan(plan_path)
    rows = build_store_external_keywords(plan, ("설렁탕 맛집", "갈비탕 맛집"))

    assert [(row.place_id, row.normalized_keyword, row.from_menu, row.from_searchad_related)
            for row in rows] == [
        ("12012595", "설렁탕", True, False),
        ("12012595", "왕갈비탕", True, False),
        ("12012595", "설렁탕 맛집", False, True),
        ("12012595", "갈비탕 맛집", False, True),
        ("11627699", "설렁탕", True, False),
        ("11627699", "왕갈비탕", True, False),
        ("11627699", "설렁탕 맛집", False, True),
        ("11627699", "갈비탕 맛집", False, True),
    ]
    assert all(not row.from_operation_keyword for row in rows)


def test_batch_plan_rejects_more_than_five_searchad_seed_menus(tmp_path):
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps({
        "brand_code": "01",
        "as_of": "2026-09-09",
        "brand_menus": ["메뉴1", "메뉴2", "메뉴3", "메뉴4", "메뉴5", "메뉴6"],
        "stores": [{"store_name": "부천본점", "place_id": "12012595"}],
    }, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match="최대 5개"):
        load_batch_plan(plan_path)


def test_batch_plan_rejects_duplicate_place_ids(tmp_path):
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps({
        "brand_code": "01",
        "as_of": "2026-09-09",
        "brand_menus": ["설렁탕"],
        "stores": [
            {"store_name": "부천본점", "place_id": "12012595"},
            {"store_name": "중복", "place_id": "12012595"},
        ],
    }, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match="중복 Place ID"):
        load_batch_plan(plan_path)


def test_batch_run_persists_one_store_scoped_run_per_store(tmp_path):
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps({
        "brand_code": "01",
        "as_of": "2026-09-09",
        "brand_menus": ["설렁탕"],
        "stores": [
            {"store_name": "부천본점", "place_id": "12012595"},
            {"store_name": "강동점", "place_id": "11627699"},
        ],
    }, ensure_ascii=False), encoding="utf-8")
    plan = load_batch_plan(plan_path)

    class EmptySource:
        def iter_reviews(self, brand_code, window, target_place_id=None):
            return ()

    class RecordingSink:
        def __init__(self):
            self.calls = []

        def save_run(self, run_id, terms, candidates):
            self.calls.append((run_id, terms, candidates))

    sink = RecordingSink()
    summaries = run_batch_plan(
        plan,
        EmptySource(),
        RuleBasedExtractor(AnalysisWindow(plan.as_of, plan.months)),
        sink,
        related_keywords=("설렁탕 맛집",),
        dry_run=False,
    )

    assert [item["place_id"] for item in summaries] == ["12012595", "11627699"]
    assert len(sink.calls) == 2
    for (_, terms, candidates), place_id in zip(sink.calls, ("12012595", "11627699")):
        assert terms == ()
        assert {(candidate.place_id, candidate.normalized_keyword) for candidate in candidates} == {
            (place_id, "설렁탕"),
            (place_id, "설렁탕 맛집"),
        }


def test_batch_cli_defaults_to_dry_run_and_can_enable_searchad():
    args = parse_args(["--input", "inputs/hanchon.json", "--expand-searchad"])

    assert str(args.input).endswith("hanchon.json")
    assert args.expand_searchad
    assert args.dry_run
