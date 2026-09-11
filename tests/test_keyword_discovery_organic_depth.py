from scripts.keyword_discovery_rank.browser import BrowserSession
from scripts.keyword_discovery_rank.models import CollectStatus, ParsedSearch
from scripts.keyword_discovery_rank.validation import ResultValidator
from test_keyword_discovery_browser import FakeDriver, ManualClock, make_task, result_html
from test_keyword_discovery_validation import result


def session(driver):
    clock = ManualClock()
    return BrowserSession(driver, organic_limit=True, timeout_seconds=5,
                          poll_interval=1, monotonic=clock.monotonic, sleep=clock.sleep)


def test_no_location_search_accepts_existing_cards_without_waiting_for_location():
    task = make_task()
    driver = FakeDriver([('https://m.search.naver.com/search.naver?query=' + task.query,
                          '<span>위치 정보 없음</span>' + result_html(20))])
    assert session(driver).search(task).observed_result_count == 20


def test_browser_continues_past_twenty_cards_when_two_are_ads():
    task = make_task()
    def html(n):
        return result_html(n).replace('data-place-id="1"', 'data-place-id="1" data-is-ad="true"').replace(
            'data-place-id="2"', 'data-place-id="2" data-is-ad="true"')
    driver = FakeDriver([('https://m.search.naver.com/search.naver?query=' + task.query, html(n))
                         for n in (20, 22)])
    assert session(driver).search(task).observed_result_count == 22


def test_disappearing_more_button_does_not_prove_twentieth_rank_or_end():
    task = make_task()
    driver = FakeDriver([('https://m.search.naver.com/search.naver?query=' + task.query, result_html(8))])
    class More:
        def is_displayed(self): return True
        def is_enabled(self): return True
        def click(self): driver.more_button = None
    driver.more_button = More()
    page = session(driver).search(task)
    assert page.observed_result_count == 8
    assert page.result_end_reached is False


def mixed(n):
    return (result(1, None, 'ad', is_ad=True),) + tuple(result(i+1, i, str(i)) for i in range(1,n+1))


def test_validator_keeps_ads_and_twenty_organic_results():
    outcome = ResultValidator(organic_limit=True).validate(ParsedSearch(mixed(22), 23, False), 20)
    assert outcome.status is CollectStatus.SUCCESS
    assert len(outcome.results) == 21
    assert outcome.results[-1].organic_rank == 20


def test_twenty_total_cards_with_ad_are_partial_without_end():
    outcome = ResultValidator(organic_limit=True).validate(ParsedSearch(mixed(19), 20, False), 20)
    assert outcome.status is CollectStatus.PARTIAL


def test_confirmed_short_list_is_complete_but_retains_actual_depth():
    outcome = ResultValidator(organic_limit=True).validate(ParsedSearch(mixed(4), 5, True), 20)
    assert outcome.status is CollectStatus.SUCCESS
    assert outcome.results[-1].organic_rank == 4


def test_unparsed_card_is_partial_even_with_twenty_organic_results():
    outcome = ResultValidator(organic_limit=True).validate(ParsedSearch(mixed(20), 22, False), 20)
    assert outcome.status is CollectStatus.PARTIAL
