import json
from pathlib import Path
from scripts.menu_keyword_pipeline.workflow import write


def test_transient_windows_replace_failure_is_retried(tmp_path,monkeypatch):
    original=Path.replace;attempts=[]
    def replace(self,target):
        attempts.append(True)
        if len(attempts)<3:raise PermissionError('temporarily locked')
        return original(self,target)
    monkeypatch.setattr(Path,'replace',replace)
    monkeypatch.setattr('time.sleep',lambda _:None)
    write(tmp_path,'state.json',{'status':'DONE'})
    assert len(attempts)==3
    assert json.loads((tmp_path/'state.json').read_text())=={'status':'DONE'}
