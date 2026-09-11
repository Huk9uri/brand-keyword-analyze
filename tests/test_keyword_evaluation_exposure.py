from scripts.keyword_evaluation.pipeline import evaluate_bundle
from test_keyword_evaluation_engine import bundle


def test_exposure_competitors_ignore_category_and_do_not_apply_direct_share_threshold():
    data = bundle()
    data['knowledge']['competitor_basis'] = 'SEARCH_EXPOSURE'
    data['knowledge']['categories'] = {}
    template = data['keyword_snapshots'][0]
    data['keyword_snapshots'] = [dict(template, snapshot_id=i, effective_snapshot_id=i, place_id=str(200+i)) for i in range(1,11) if i != 3]
    result = evaluate_bundle(data)['results'][0]
    assert 'COMPETITOR_UNKNOWN' not in result['reason_codes']
    assert result['raw_scores']['exposure_competitor_count'] == 9
    assert result['raw_scores']['direct_share'] is None
    assert result['normalized_scores']['direct_share'] is None
    assert result['final_class'] == 'REVIEW_REQUIRED'
    assert 'COMPETITION_CALIBRATION_REQUIRED' in result['reason_codes']
    assert result['raw_scores']['keyword_coverage_count'] > 0


def test_exposure_keeps_keyword_evidence_when_missing():
    data = bundle()
    data['knowledge']['competitor_basis'] = 'SEARCH_EXPOSURE'
    data['knowledge']['categories'] = {}
    data['keyword_snapshots'] = []
    result = evaluate_bundle(data)['results'][0]
    assert 'KEYWORDLIST_MISSING' in result['reason_codes']
    assert any(e['evidence_type']=='KEYWORDLIST' for e in result['evidence'])
