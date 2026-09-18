import json
from pathlib import Path

from scripts.menu_keyword_pipeline import cli
from scripts.menu_keyword_pipeline.workflow import execute
from test_menu_keyword_workflow import MemoryAdapter, REG
from test_menu_keyword_pipeline import NOW


def test_cli_auto_creates_distinct_outputs_and_compares_previous(monkeypatch,tmp_path):
    monkeypatch.chdir(tmp_path)
    registry=tmp_path/'registry.json'
    registry.write_text(json.dumps(REG),encoding='utf-8')
    adapter=MemoryAdapter()
    class Connection:
        def close(self): pass
    monkeypatch.setattr('scripts.keyword_evaluation.cli._connection',lambda _:Connection())
    monkeypatch.setattr('scripts.menu_keyword_pipeline.repository.Adapter',lambda *args:adapter)
    monkeypatch.setattr(cli,'execute',lambda *args,**kwargs:execute(*args,**kwargs,clock=lambda:NOW))
    args=['--registry',str(registry),'--collect','--allow-write','--allow-network']
    assert cli.main(args)==0
    first=next(Path('outputs').iterdir())
    assert (first/'report.md').exists()
    original=(first/'results.json').read_bytes()
    assert cli.main(args)==0
    folders=list(Path('outputs').iterdir())
    assert len(folders)==2
    second=next(p for p in folders if p!=first)
    comparison=json.loads((second/'changes.json').read_text(encoding='utf-8'))
    assert comparison['baseline']==str(first.resolve())
    assert comparison['rows'][0]['change']=='UNCHANGED'
    assert (first/'results.json').read_bytes()==original
    assert len(adapter.rank_requests)==1
