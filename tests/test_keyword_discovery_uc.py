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
    monkeypatch.setattr('scripts.keyword_discovery_rank.browser.subprocess.run',
                        lambda *args, **kwargs: SimpleNamespace(stdout=version))
    assert _chrome_major('chrome.exe') == 152


def test_unknown_chrome_version_fails_before_download(monkeypatch):
    from types import SimpleNamespace
    from scripts.keyword_discovery_rank.browser import _chrome_major
    monkeypatch.setattr('scripts.keyword_discovery_rank.browser.subprocess.run',
                        lambda *args, **kwargs: SimpleNamespace(stdout=''))
    with pytest.raises(RuntimeError):
        _chrome_major('chrome.exe')
