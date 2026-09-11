"""플레이스 목록 전용 수집 조건. keywordList 수집 경로와 독립적이다."""
import math
from urllib.parse import urlencode, urlparse, parse_qs

PROFILE = 'MOBILE_PLACE_LIST_STORE_LOCATION_ORGANIC20_V4'


def list_cards(soup):
    return soup.select('.place_business_list_wrapper > ul > li.UEzoS')


def search_url(task):
    if (task.device_type.value != 'MOBILE' or type(task.latitude) not in (float, int)
            or type(task.longitude) not in (float, int) or not math.isfinite(task.latitude)
            or not math.isfinite(task.longitude) or not 33 <= task.latitude <= 39 or not 124 <= task.longitude <= 132):
        raise ValueError('플레이스 목록 검색에는 검증된 매장 좌표와 MOBILE 기기가 필요합니다')
    return 'https://m.place.naver.com/restaurant/list?' + urlencode(dict(
        query=task.query, x=task.longitude, y=task.latitude, level='top', entry='pll'))


def matches_location(url, task):
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    try:
        return (parsed.netloc == 'm.place.naver.com' and parsed.path == '/restaurant/list'
                and round(float(query['x'][0]), 7) == round(task.longitude, 7)
                and round(float(query['y'][0]), 7) == round(task.latitude, 7))
    except (KeyError, ValueError, TypeError):
        return False


SCROLL_SCRIPT = """
const wrapper = document.querySelector('.place_business_list_wrapper');
let node = wrapper;
while (node && node !== document.body) {
  if (node.scrollHeight > node.clientHeight && /(auto|scroll)/.test(getComputedStyle(node).overflowY)) {
    node.scrollTop += Math.max(400, node.clientHeight * 0.8);
    return;
  }
  node = node.parentElement;
}
window.scrollBy(0, Math.max(400, window.innerHeight * 0.8));
"""
