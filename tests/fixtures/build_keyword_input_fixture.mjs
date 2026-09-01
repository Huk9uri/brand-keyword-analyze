import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";
const output = process.argv[2];
const workbook = Workbook.create();
const sheet = workbook.worksheets.add("키워드입력");
sheet.getRange("A1:G2").values = [
  ["매장명", "키워드1", "키워드2", "키워드3", "키워드4", "키워드5", "메모"],
  ["한촌설렁탕 테스트점", "갈비탕", " 해장 ", "갈비탕", null, "혼밥", "ignored"],
];
await (await SpreadsheetFile.exportXlsx(workbook)).save(output);
