import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";
const output = process.argv[2];
const scenario = process.argv[3] ?? "valid";
const workbook = Workbook.create();
const sheet = workbook.worksheets.add(scenario === "missing_sheet" ? "다른시트" : "키워드입력");
const scenarios = {
  valid: [
    ["매장명", "키워드1", "키워드2", "키워드3", "키워드4", "키워드5", "메모"],
    ["한촌설렁탕 테스트점", "갈비탕", " 해장 ", "갈비탕", null, "혼밥", "ignored"],
  ],
  missing_sheet: [["매장명", "키워드1"], ["테스트점", "갈비탕"]],
  missing_store_header: [["점포", "키워드1"], ["테스트점", "갈비탕"]],
  missing_keyword1_header: [["매장명", "키워드2"], ["테스트점", "갈비탕"]],
  keyword6_header: [["매장명", "키워드1", "키워드6"], ["테스트점", "갈비탕", "설렁탕"]],
  duplicate_store: [["매장명", "키워드1"], ["테스트점", "갈비탕"], ["테스트점", "해장"]],
  no_keywords: [["매장명", "키워드1"], ["테스트점", null]],
  orphan_values: [["매장명", "키워드1", "메모"], [null, "갈비탕", "값 있음"]],
  example_row: [["매장명", "키워드1"], ["예시 매장명", "지역명"]],
};
const rows = scenarios[scenario];
if (!rows) throw new Error(`unknown scenario: ${scenario}`);
sheet.getRangeByIndexes(0, 0, rows.length, rows[0].length).values = rows;
await (await SpreadsheetFile.exportXlsx(workbook)).save(output);
