from pathlib import Path

import pytest

from scripts.keyword_discovery_rank.browser import BrowserFactory, BrowserSessionError
from scripts.keyword_discovery_rank.models import DeviceType


class Driver:
    def __init__(self, fail=False):
        self.closed = False
        self.fail = fail

    def set_window_size(self, *args):
        if self.fail:
            raise RuntimeError('viewport failed')

    def quit(self):
        self.closed = True


def test_sessions_isolate_profile_data_and_clean_up():
    paths = []
    def build(**kwargs):
        path = Path(kwargs['user_data_dir'])
        assert path.is_dir()
        assert not (path / 'cookie').exists()
        (path / 'cookie').write_text('session')
        paths.append(path)
        return Driver()

    factory = BrowserFactory(driver_builder=build)
    first = factory.create(DeviceType.PC, None, None)
    second = factory.create(DeviceType.PC, None, None)
    try:
        assert paths[0] != paths[1]
        first.close()
        assert first.driver.closed
        assert not paths[0].exists()
        assert paths[1].exists()
    finally:
        second.close()
    assert not paths[1].exists()


@pytest.mark.parametrize('construction_failure', [False, True])
def test_failed_creation_cleans_owned_resources(construction_failure):
    paths = []
    driver = Driver(fail=True)
    def build(**kwargs):
        paths.append(Path(kwargs['user_data_dir']))
        if construction_failure:
            raise RuntimeError('startup failed')
        return driver

    with pytest.raises(BrowserSessionError):
        BrowserFactory(driver_builder=build).create(DeviceType.PC, None, None)
    assert len(paths) == 1
    assert not paths[0].exists()
    assert driver.closed is (not construction_failure)


def test_default_factory_uses_uc_with_isolated_profile(monkeypatch):
    import undetected_chromedriver as uc

    captured = {}
    driver = Driver()
    def build(**kwargs):
        captured.update(kwargs)
        return driver

    monkeypatch.setattr(uc, 'Chrome', build)
    monkeypatch.setattr(uc, 'find_chrome_executable', lambda: 'chrome.exe')
    monkeypatch.setattr('scripts.keyword_discovery_rank.browser._chrome_major', lambda path: 152, raising=False)
    session = BrowserFactory(headless=True).create(DeviceType.MOBILE, None, None)
    try:
        assert isinstance(captured['options'], uc.ChromeOptions)
        assert '--headless=new' in captured['options'].arguments
        assert '--lang=ko-KR' in captured['options'].arguments
        assert captured['use_subprocess'] is True
        assert captured['port'] == 0
        assert captured['version_main'] == 152
        assert captured['browser_executable_path'] == 'chrome.exe'
        assert Path(captured['user_data_dir']).is_dir()
    finally:
        session.close()


def test_close_cleans_profile_when_driver_quit_fails():
    class FailingQuitDriver(Driver):
        def quit(self):
            raise RuntimeError('quit failed')

    paths = []
    def build(**kwargs):
        paths.append(Path(kwargs['user_data_dir']))
        return FailingQuitDriver()

    session = BrowserFactory(driver_builder=build).create(DeviceType.PC, None, None)
    with pytest.raises(RuntimeError, match='quit failed'):
        session.close()
    assert not paths[0].exists()


def test_cleanup_failure_does_not_hide_browser_startup_error(monkeypatch):
    class LockedProfile:
        name = 'temporary-profile'
        def __init__(self, **kwargs): pass
        def cleanup(self): raise PermissionError('locked')

    monkeypatch.setattr('scripts.keyword_discovery_rank.browser.TemporaryDirectory', LockedProfile)
    def fail(**kwargs): raise RuntimeError('version mismatch')
    with pytest.raises(BrowserSessionError, match='version mismatch'):
        BrowserFactory(driver_builder=fail).create(DeviceType.PC, None, None)


@pytest.mark.parametrize('version', ['152.0.7977.76', 'Google Chrome 152.0.7977.76'])
def test_chrome_major_reads_installed_binary_version(monkeypatch, version):
    from types import SimpleNamespace
    from scripts.keyword_discovery_rank.browser import _chrome_major
    monkeypatch.setattr('scripts.keyword_discovery_rank.browser.sys.platform', 'linux')
    monkeypatch.setattr('scripts.keyword_discovery_rank.browser.subprocess.run',
                        lambda *args, **kwargs: SimpleNamespace(stdout=version))
    assert _chrome_major('chrome.exe') == 152


def test_unknown_chrome_version_fails_before_download(monkeypatch):
    from types import SimpleNamespace
    from scripts.keyword_discovery_rank.browser import _chrome_major
    monkeypatch.setattr('scripts.keyword_discovery_rank.browser.sys.platform', 'linux')
    monkeypatch.setattr('scripts.keyword_discovery_rank.browser.subprocess.run',
                        lambda *args, **kwargs: SimpleNamespace(stdout=''))
    with pytest.raises(RuntimeError):
        _chrome_major('chrome.exe')


def test_windows_chrome_version_does_not_launch_powershell(monkeypatch):
    from scripts.keyword_discovery_rank import browser
    monkeypatch.setattr(browser.sys,'platform','win32')
    monkeypatch.setattr(browser,'_windows_chrome_major',lambda path:152,raising=False)
    def forbidden(*args,**kwargs):raise AssertionError('PowerShell subprocess must not run')
    monkeypatch.setattr(browser.subprocess,'run',forbidden)
    assert browser._chrome_major('chrome.exe')==152


def test_close_waits_for_browser_before_retrying_locked_profile(monkeypatch, tmp_path):
    from scripts.keyword_discovery_rank import browser
    events = []
    path = tmp_path / 'uc_keyword_rank_test'
    path.mkdir()

    class Profile:
        name = str(path)
        attempts = 0
        def cleanup(self):
            events.append('cleanup')
            self.attempts += 1
            if self.attempts < 3:
                raise PermissionError('Chrome still holds a file')
            path.rmdir()

    class ClosingDriver(Driver):
        def quit(self): events.append('quit')

    def prepare_wait(driver):
        events.append('capture')
        return lambda: events.append('wait')

    monkeypatch.setattr(browser, '_prepare_browser_exit_wait', prepare_wait, raising=False)
    monkeypatch.setattr(browser.time, 'sleep', lambda seconds: None)
    profile = Profile()
    browser.BrowserSession(ClosingDriver(), profile=profile).close()
    assert events[:3] == ['capture', 'quit', 'wait']
    assert profile.attempts == 3
    assert not path.exists()


def test_close_records_profile_path_after_exhausted_retries(monkeypatch, caplog):
    from scripts.keyword_discovery_rank import browser
    class Profile:
        name = 'uc_keyword_rank_locked'
        attempts = 0
        def cleanup(self):
            self.attempts += 1
            raise PermissionError('locked')
    monkeypatch.setattr(browser.time, 'sleep', lambda seconds: None)
    monkeypatch.setattr(browser, '_pending_profiles', [])
    profile = Profile()
    browser.BrowserSession(Driver(), profile=profile).close()
    assert browser._pending_profiles == [profile]
    assert profile.attempts > 1
    assert profile.name in caplog.text


def test_startup_failure_retries_locked_profile(monkeypatch):
    from scripts.keyword_discovery_rank import browser
    class Profile:
        name = 'uc_keyword_rank_startup'
        attempts = 0
        def cleanup(self):
            self.attempts += 1
            if self.attempts == 1: raise PermissionError('locked')
    profile = Profile()
    monkeypatch.setattr(browser, 'TemporaryDirectory', lambda **kwargs: profile)
    monkeypatch.setattr(browser.time, 'sleep', lambda seconds: None)
    def fail(**kwargs): raise RuntimeError('startup failed')
    with pytest.raises(BrowserSessionError, match='startup failed'):
        BrowserFactory(driver_builder=fail).create(DeviceType.PC, None, None)
    assert profile.attempts == 2


def test_access_limit_is_not_a_retryable_page_error():
    from scripts.keyword_discovery_rank.browser import detect_page_state
    assert detect_page_state('https://m.search.naver.com/search.naver?query=test',
        '<p>과도한 접근 요청으로 서비스 이용이 제한되었습니다. 잠시 후 다시 시도해주세요.</p>',
        'test') == 'SECURITY_CHECK'


def test_exit_timeout_terminates_captured_handle_and_confirms_exit(monkeypatch):
    import ctypes
    from types import SimpleNamespace
    from scripts.keyword_discovery_rank import browser
    calls = []
    class Fn:
        def __init__(self, fn): self.fn = fn
        def __call__(self, *args): return self.fn(*args)
    waits = iter([258, 0])
    kernel = SimpleNamespace(
        OpenProcess=Fn(lambda *args: 1234),
        WaitForSingleObject=Fn(lambda *args: next(waits)),
        TerminateProcess=Fn(lambda handle, code: calls.append(('terminate', handle)) or 1),
        CloseHandle=Fn(lambda handle: calls.append(('close', handle)) or 1))
    monkeypatch.setattr(browser.sys, 'platform', 'win32')
    monkeypatch.setattr(ctypes, 'WinDLL', lambda *a, **k: kernel, raising=False)
    wait = browser._prepare_browser_exit_wait(SimpleNamespace(browser_pid=42))
    wait()
    assert calls == [('terminate', 1234), ('close', 1234)]


def test_unconfirmed_exit_does_not_delete_profile(monkeypatch):
    from scripts.keyword_discovery_rank import browser
    calls = []
    def fail(): raise OSError('browser still running')
    monkeypatch.setattr(browser, '_prepare_browser_exit_wait', lambda d: fail)
    class Profile:
        def cleanup(self): calls.append('delete')
    with pytest.raises(OSError):
        browser.BrowserSession(Driver(), profile=Profile()).close()
    assert calls == []


def test_deferred_cleanup_recovers_and_enforces_limit(monkeypatch):
    from scripts.keyword_discovery_rank import browser
    monkeypatch.setattr(browser.time, 'sleep', lambda _: None)
    monkeypatch.setattr(browser, '_pending_profiles', [])
    class Profile:
        name = 'owned-test-profile'
        locked = True
        def cleanup(self):
            if self.locked: raise PermissionError('locked')
    p = Profile()
    browser._cleanup_or_defer(p)
    assert browser._pending_profiles == [p]
    p.locked = False
    browser._retry_pending_profiles()
    assert not browser._pending_profiles
    for _ in range(3): browser._cleanup_or_defer(Profile())
    with pytest.raises(OSError): browser._cleanup_or_defer(Profile())
