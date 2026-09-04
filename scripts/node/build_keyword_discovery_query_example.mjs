import fs from "node:fs/promises";
import path from "node:path";

import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const outputPath = path.resolve("inputs/keyword_discovery_queries.example.xlsx");
const previewPath = path.resolve(".tmp_keyword_discovery_artifact/keyword_discovery_queries.example.png");
const identityPreviewPath = path.resolve(
  ".tmp_keyword_discovery_artifact/keyword_discovery_queries.identity.example.png",
);

const workbook = Workbook.create();
const sheet = workbook.worksheets.add("검색작업");

sheet.getRange("A1:H2").values = [
  ["검색어", "기준매장ID", "기준매장명", "조회위치명", "위도", "경도", "기기", "소스ID"],
  ["예시: 선릉역 국밥", "SAMPLE-S1", "예시 매장", "선릉역", 37.5048, 127.0489, "MOBILE", "sample-row-001"],
];

sheet.showGridLines = false;
sheet.freezePanes.freezeRows(1);
sheet.getRange("A1:H1").format = {
  fill: "#1F4E78",
  font: { bold: true, color: "#FFFFFF" },
  borders: { preset: "outside", style: "thin", color: "#17365D" },
};
sheet.getRange("A2:H2").format = {
  fill: "#EAF2F8",
  borders: { preset: "outside", style: "thin", color: "#B4C7E7" },
};
sheet.getRange("E2:F2").format.numberFormat = "0.0000000";
sheet.getRange("A1:A2").format.columnWidth = 24;
sheet.getRange("B1:B2").format.columnWidth = 16;
sheet.getRange("C1:C2").format.columnWidth = 18;
sheet.getRange("D1:D2").format.columnWidth = 14;
sheet.getRange("E1:F2").format.columnWidth = 14;
sheet.getRange("G1:G2").format.columnWidth = 12;
sheet.getRange("H1:H2").format.columnWidth = 20;
sheet.getRange("A1:H1").format.rowHeight = 24;
sheet.getRange("A2:H2").format.rowHeight = 22;

const identitySheet = workbook.worksheets.add("자사매장");
identitySheet.getRange("A1:D2").values = [
  ["매장ID", "매장명", "네이버플레이스ID", "수동매핑플레이스ID"],
  ["SAMPLE-S1", "예시 매장", "1001", "legacy-1001"],
];
identitySheet.showGridLines = false;
identitySheet.freezePanes.freezeRows(1);
identitySheet.getRange("A1:D1").format = {
  fill: "#1F4E78",
  font: { bold: true, color: "#FFFFFF" },
  borders: { preset: "outside", style: "thin", color: "#17365D" },
};
identitySheet.getRange("A2:D2").format = {
  fill: "#EAF2F8",
  borders: { preset: "outside", style: "thin", color: "#B4C7E7" },
};
identitySheet.getRange("A1:A2").format.columnWidth = 18;
identitySheet.getRange("B1:B2").format.columnWidth = 20;
identitySheet.getRange("C1:C2").format.columnWidth = 22;
identitySheet.getRange("D1:D2").format.columnWidth = 25;
identitySheet.getRange("A1:D1").format.rowHeight = 24;
identitySheet.getRange("A2:D2").format.rowHeight = 22;

const inspection = await workbook.inspect({
  kind: "table",
  range: "검색작업!A1:H2",
  include: "values,formulas",
  tableMaxRows: 2,
  tableMaxCols: 8,
});
console.log(inspection.ndjson);
const identityInspection = await workbook.inspect({
  kind: "table",
  range: "자사매장!A1:D2",
  include: "values,formulas",
  tableMaxRows: 2,
  tableMaxCols: 4,
});
console.log(identityInspection.ndjson);
const formulaErrors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 50 },
  summary: "keyword discovery example formula error scan",
});
console.log(formulaErrors.ndjson);

const preview = await workbook.render({
  sheetName: "검색작업",
  range: "A1:H2",
  scale: 2,
  format: "png",
});
await fs.mkdir(path.dirname(previewPath), { recursive: true });
await fs.writeFile(previewPath, new Uint8Array(await preview.arrayBuffer()));

const identityPreview = await workbook.render({
  sheetName: "자사매장",
  range: "A1:D2",
  scale: 2,
  format: "png",
});
await fs.writeFile(identityPreviewPath, new Uint8Array(await identityPreview.arrayBuffer()));

const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);

console.log(JSON.stringify({ outputPath, previewPath, identityPreviewPath }));
