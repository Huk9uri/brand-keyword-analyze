import json
import subprocess
from pathlib import Path

NODE = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe"


def test_template_has_canonical_sheets_and_headers(tmp_path: Path):
    output = tmp_path / "template.xlsx"
    previews = tmp_path / "previews"
    subprocess.run([str(NODE), "scripts/node/build_keyword_input_template.mjs", "--output", str(output), "--preview-dir", str(previews)], check=True)
    script = (
        'import {FileBlob,SpreadsheetFile} from "@oai/artifact-tool";'
        'const w=await SpreadsheetFile.importXlsx(await FileBlob.load(process.argv[1]));'
        'const s=w.worksheets.getItem("키워드입력");'
        'console.log(JSON.stringify({names:w.worksheets.items.map(x=>x.name),headers:s.getRange("A1:G1").values[0],example:s.getRange("A2:G2").values[0]}));'
    )
    inspected = subprocess.run([str(NODE), "--input-type=module", "-e", script, str(output)], check=True, capture_output=True, text=True, encoding="utf-8")
    data = json.loads(inspected.stdout)
    assert data["names"] == ["사용방법", "키워드입력"]
    assert data["headers"] == ["매장명", "키워드1", "키워드2", "키워드3", "키워드4", "키워드5", "메모"]
    assert data["example"][:6] == ["예시 매장명", "지역명", "역명", "메뉴명", None, None]
    assert output.stat().st_size > 0
    assert (previews / "instructions.png").stat().st_size > 0
    assert (previews / "keyword_input.png").stat().st_size > 0
