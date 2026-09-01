import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const argv = process.argv.slice(2);
const args = {};
for (let i = 0; i < argv.length; i += 2) args[argv[i].slice(2)] = argv[i + 1];
if (!args.output || !args["preview-dir"]) throw new Error("--output and --preview-dir are required");

const workbook = Workbook.create();
const instructions = workbook.worksheets.add("사용방법");
instructions.showGridLines = false;
instructions.getRange("A1:F1").merge();
instructions.getRange("A1").values = [["매장별 키워드 검색량 표준 입력 양식"]];
instructions.getRange("A1:F1").format = {fill: "#203864", font: {bold: true, color: "#FFFFFF", size: 16}, horizontalAlignment: "center", verticalAlignment: "center"};
instructions.getRange("A1:F1").format.rowHeight = 32;
instructions.getRange("A3:A7").values = [[
  "1. 이 파일을 프로젝트의 inputs/keyword_input.xlsx로 저장합니다.",
], ["2. 키워드입력 시트의 예시 행을 삭제하고 실제 매장을 입력합니다."], ["3. 매장당 키워드는 최대 5개입니다."], ["4. 6개 이상은 앵커 키워드 기반 별도 모델이 필요합니다."], ["5. 프로젝트 폴더에서 .\\run_keyword_volume.ps1을 실행합니다."]];
instructions.getRange("A3:F7").merge(true);
instructions.getRange("A3:F7").format = {fill: "#D9E2F3", wrapText: true, verticalAlignment: "center"};
instructions.getRange("A3:F7").format.rowHeight = 28;
instructions.getRange("A1:F7").format.columnWidth = 18;

const input = workbook.worksheets.add("키워드입력");
input.showGridLines = false;
input.getRange("A1:G2").values = [
  ["매장명", "키워드1", "키워드2", "키워드3", "키워드4", "키워드5", "메모"],
  ["예시 매장명", "지역명", "역명", "메뉴명", null, null, "이 행을 삭제 후 입력"],
];
input.getRange("A1:G1").format = {fill: "#203864", font: {bold: true, color: "#FFFFFF"}, horizontalAlignment: "center", verticalAlignment: "center"};
input.getRange("A2:G2").format = {fill: "#FFF2CC", font: {color: "#7F6000"}};
input.getRange("A:G").format.numberFormat = "@";
[24, 22, 22, 22, 22, 22, 32].forEach((width, index) => { input.getRangeByIndexes(0, index, 1, 1).format.columnWidth = width; });
input.freezePanes.freezeRows(1);

await fs.mkdir(path.dirname(path.resolve(args.output)), {recursive: true});
await fs.mkdir(path.resolve(args["preview-dir"]), {recursive: true});
for (const [sheetName, range, fileName] of [["사용방법", "A1:F7", "instructions.png"], ["키워드입력", "A1:G5", "keyword_input.png"]]) {
  const image = await workbook.render({sheetName, range, scale: 2, format: "png"});
  await fs.writeFile(path.join(args["preview-dir"], fileName), new Uint8Array(await image.arrayBuffer()));
}
await (await SpreadsheetFile.exportXlsx(workbook)).save(args.output);
