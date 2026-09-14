import json
from copy import deepcopy

import pytest

from scripts.brand_keyword_research.cli import execute, replay, main
from test_brand_keyword_research import config, state, volume


class InventoryRepo:
    def __init__(self):
        self.preparations = 0
        self.collections = 0

    def prepare(self, cfg, collect=False, root=None):
        self.preparations += 1
        resolved = deepcopy(cfg); resolved['targets'] = []
        return resolved, [dict(store_code='001', store_name='미확인점', place_id=None,
                               target_store_id='IYN-001', status='PLACE_ID_MISSING', search_location=None)]

    def read(self, cfg, start, end):
        s = state(); s['config'] = cfg; s['volumes'] = [volume()]
        return s

    def collect(self, s, root):
        self.collections += 1
        return {'aborted': False, 'processed': 0, 'persistence_failures': 0}


def test_readonly_inventory_is_partial_and_csvs_replay_without_database(tmp_path):
    repo = InventoryRepo(); cfg = config(); cfg['scope'] = 'ALL_STORES'
    root = tmp_path/'read'
    assert execute(cfg, root, repo) == 2
    assert repo.preparations == 1 and repo.collections == 0
    result = json.loads((root/'comparison.json').read_text(encoding='utf-8'))
    assert result['keyword_summary'][0]['total_stores'] == 1
    assert result['keyword_summary'][0]['valid_stores'] == 0
    assert result['keyword_summary'][0]['top20_rate_pct'] is None
    assert result['keyword_summary'][0]['volume_interval'] == [0, 18]
    replay(root/'input.json', tmp_path/'replay')
    for filename in ('report.md', 'keyword-summary.csv', 'store-ranks.csv', 'store-inventory.csv'):
        assert (root/filename).read_bytes() == (tmp_path/'replay'/filename).read_bytes()


def test_collect_pins_inventory_once_across_before_and_after_reads(tmp_path):
    repo = InventoryRepo(); cfg = config(); cfg['scope'] = 'ALL_STORES'
    assert execute(cfg, tmp_path/'collect', repo, collect=True) == 2
    assert repo.preparations == 1 and repo.collections == 1


def test_cli_all_stores_configures_scope_and_batch_size(tmp_path, monkeypatch):
    from scripts.keyword_evaluation import cli as base_cli
    from scripts.brand_keyword_research import cli
    class Connection:
        def close(self): pass
    monkeypatch.setattr(base_cli, '_connection', lambda path: Connection())
    seen = []
    monkeypatch.setattr(cli, 'execute', lambda cfg, *a: seen.append(cfg) or 0)
    path = tmp_path/'config.json'; path.write_text(json.dumps(config()), encoding='utf-8')
    assert main(['--config', str(path), '--output', str(tmp_path/'out'), '--all-stores', '--batch-size', '40']) == 0
    assert seen[0]['scope'] == 'ALL_STORES'
    assert seen[0]['batch_size'] == 40


def test_replay_cannot_silently_ignore_all_store_flag(tmp_path):
    with pytest.raises(SystemExit):
        main(['--replay', 'unused.json', '--output', str(tmp_path/'out'), '--all-stores'])
