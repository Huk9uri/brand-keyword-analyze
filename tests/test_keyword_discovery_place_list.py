from dataclasses import replace
import pytest
from urllib.parse import urlparse, parse_qs

from scripts.keyword_discovery_rank.browser import _build_search_url, _result_progress, detect_page_state
from scripts.keyword_discovery_rank.parser import DomResultParser
from scripts.keyword_discovery_rank.models import SearchPage
from scripts.keyword_discovery_rank.validation import ResultValidator
from test_keyword_discovery_browser import make_task, FakeDriver, make_session

PROFILE = 'MOBILE_PLACE_LIST_STORE_LOCATION_ORGANIC20_V4'


def list_html(count=20):
    ad = '<li class="UEzoS"><div class="SgjqM"><a href="https://ader.naver.com/v1/a?fu=https%3A%2F%2Fm.place.naver.com%2Frestaurant%2F999"><span class="TYaxT">광고 매장</span></a></div></li>'
    cards = ''.join(f'<li class="UEzoS"><div class="SgjqM"><a href="/restaurant/{i}?entry=pll"><span class="TYaxT">매장 {i}</span><span class="KCMnt">곰탕,설렁탕</span></a></div></li>' for i in range(1, count+1))
    promo = '<li class="phKao"><a href="/restaurant/888">새로 오픈했어요</a></li>'
    return '<div class="place_business_list_wrapper"><ul>'+ad+promo+cards+'</ul></div>'


def test_store_list_url_has_correct_coordinates_and_preserves_legacy_url():
    task = replace(make_task(), location_name=PROFILE)
    url = urlparse(_build_search_url(task))
    assert url.netloc == 'm.place.naver.com'
    assert url.path == '/restaurant/list'
    assert parse_qs(url.query)['x'] == [str(task.longitude)]
    assert parse_qs(url.query)['y'] == [str(task.latitude)]
    assert urlparse(_build_search_url(make_task())).netloc == 'm.search.naver.com'


def test_list_parser_excludes_modules_and_resolves_relative_links():
    html = list_html()
    observed, ended = _result_progress(html)
    assert observed == 21 and not ended
    parsed = DomResultParser().parse(SearchPage('',html,'RESULTS',observed,ended))
    assert len(parsed.results) == 21
    assert parsed.results[0].is_ad
    assert parsed.results[1].place_id == '1'
    assert parsed.results[-1].organic_rank == 20
    assert ResultValidator(organic_limit=True).validate(parsed,20).status.value == 'SUCCESS'


def test_list_search_does_not_require_mobile_search_location_control():
    task = replace(make_task(), location_name=PROFILE)
    url = _build_search_url(task)
    driver = FakeDriver([(url,list_html())])
    session = make_session(driver, location_override_active=True)
    session.organic_limit = True
    page = session.search(task)
    assert page.observed_result_count == 21


def test_security_check_is_not_loading_or_empty_result():
    url = 'https://m.place.naver.com/restaurant/list?query=test'
    assert detect_page_state(url,'<p>보안 확인을 완료해 주세요</p>','test',require_location=False) == 'SECURITY_CHECK'


def test_list_search_scrolls_until_twenty_organic_results():
    task = replace(make_task(), location_name=PROFILE)
    url = _build_search_url(task)
    driver = FakeDriver([(url,list_html(10)),(url,list_html(20))])
    session = make_session(driver,location_override_active=True)
    session.organic_limit = True
    assert session.search(task).observed_result_count == 21
    assert '.place_business_list_wrapper' in driver.script_calls[0]


def test_list_search_rejects_different_coordinates():
    from scripts.keyword_discovery_rank.browser import QueryMismatch
    task = replace(make_task(), location_name=PROFILE)
    wrong = _build_search_url(replace(task, longitude=126.0))
    session = make_session(FakeDriver([(wrong,list_html())]))
    session.organic_limit = True
    with pytest.raises(QueryMismatch):
        session.search(task)


def test_v4_plan_and_evaluation_do_not_reuse_v3_observations():
    from test_keyword_evaluation_store_location import located_bundle
    from test_keyword_evaluation_engine import bundle
    from scripts.keyword_evaluation.pipeline import evaluate_bundle
    from scripts.keyword_evaluation.collection import build_rank_tasks
    data = located_bundle()
    data['rank_profile'] = PROFILE
    rank = bundle()['ranks'][0]
    rank.update(profile='MOBILE_STORE_LOCATION_ORGANIC20_V3', search_location=data['targets'][0]['search_location'])
    data['ranks'] = [rank]
    evaluated = evaluate_bundle(data)
    assert all(r['rank_snapshot_id'] is None for r in evaluated['results'])
    tasks = build_rank_tasks(evaluated)
    assert len(tasks) == 25
    assert all(urlparse(_build_search_url(t)).path == '/restaurant/list' for t in tasks)


def test_security_check_stops_run_without_retry_or_next_task(tmp_path):
    from scripts.keyword_discovery_rank.browser import SecurityCheckRequired
    from test_keyword_discovery_collector import collector, FakeSession, task
    error = SecurityCheckRequired('SECURITY_CHECK_REQUIRED',last_url='https://m.place.naver.com',html='<p>보안 확인</p>')
    session = FakeSession([error])
    instance, _, repository = collector(tmp_path,[session])
    summary = instance.run([task(),replace(task(),query='other')], 'security-test')
    assert summary.processed_tasks == 1
    assert summary.aborted
    assert summary.abort_reason == 'SECURITY_CHECK_REQUIRED'
    assert len(repository.saved) == 1
