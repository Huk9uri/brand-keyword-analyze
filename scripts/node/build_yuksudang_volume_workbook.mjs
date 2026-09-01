import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

function parseArgs(argv) {
  const args = {};
  for (let i = 0; i < argv.length; i += 2) {
    const key = argv[i];
    const value = argv[i + 1];
    if (!key?.startsWith("--") || value === undefined) {
      throw new Error(`invalid argument near ${key ?? "<end>"}`);
    }
    args[key.slice(2)] = value;
  }
  for (const required of ["input", "results", "output", "preview-dir"]) {
    if (!args[required]) throw new Error(`--${required} is required`);
  }
  return args;
}

function excelDate(value) {
  if (!value) return null;
  return new Date(`${value}T00:00:00`);
}

function applyHeaderStyle(range) {
  range.format = {
    fill: "#203864",
    font: { bold: true, color: "#FFFFFF" },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    wrapText: true,
    borders: { preset: "all", style: "thin", color: "#B4C6E7" },
  };
  range.format.rowHeight = 34;
}

function setWidths(sheet, widths) {
  widths.forEach((width, index) => {
    sheet.getRangeByIndexes(0, index, 1, 1).format.columnWidth = width;
  });
}

function addStatusFormatting(sheet, rangeAddress) {
  const range = sheet.getRange(rangeAddress);
  range.conditionalFormats.add("containsText", {
    text: "success",
    format: { fill: "#E2F0D9", font: { color: "#375623" } },
  });
  range.conditionalFormats.add("notContainsText", {
    text: "success",
    format: { fill: "#FCE4D6", font: { color: "#9C0006" } },
  });
}

async function savePreview(workbook, sheetName, range, target) {
  const preview = await workbook.render({
    sheetName,
    range,
    scale: 1,
    format: "png",
  });
  await fs.writeFile(target, new Uint8Array(await preview.arrayBuffer()));
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const result = JSON.parse(await fs.readFile(args.results, "utf8"));
  if (!Array.isArray(result.keywords) || !Array.isArray(result.daily_rows)) {
    throw new Error("result JSON must contain keywords and daily_rows arrays");
  }

  const input = await FileBlob.load(args.input);
  const workbook = await SpreadsheetFile.importXlsx(input);
  const summaryName = "30일_키워드요약";
  const dailyName = "30일_일간검색량";
  const existingNames = workbook.worksheets.items.map((sheet) => sheet.name);
  if (existingNames.includes(summaryName) || existingNames.includes(dailyName)) {
    throw new Error("source workbook already contains result sheets");
  }

  const summarySheet = workbook.worksheets.add(summaryName);
  summarySheet.showGridLines = false;
  summarySheet.getRange("A1:M1").merge();
  summarySheet.getRange("A1").values = [["육수당 매장별 키워드 최근 30일 검색량 추정"]];
  summarySheet.getRange("A1:M1").format = {
    fill: "#203864",
    font: { bold: true, color: "#FFFFFF", size: 16 },
    horizontalAlignment: "left",
    verticalAlignment: "center",
  };
  summarySheet.getRange("A1:M1").format.rowHeight = 32;

  const metadata = result.metadata ?? {};
  const counts = result.summary ?? {};
  const displayVersion = String(metadata.model_version ?? "").split("-").at(-1);
  const collectedAt = metadata.collected_at
    ? `KST ${String(metadata.collected_at).replace("T", " ").slice(0, 19)}`
    : "";
  summarySheet.getRange("A3:F5").values = [
    ["조회 기간", `${metadata.period_start ?? ""} ~ ${metadata.period_end ?? ""}`, "모델 버전", displayVersion, "수집시각", collectedAt],
    ["원본 파일", path.basename(metadata.source_file ?? path.resolve(args.input)), "매장 수", counts.stores ?? 0, "성공 키워드", counts.success_keywords ?? 0],
    ["실패 키워드", counts.failed_keywords ?? 0, "일간 행 수", counts.daily_rows ?? 0, "", ""],
  ];
  summarySheet.getRange("A3:F5").format = {
    fill: "#D9E2F3",
    borders: { preset: "all", style: "thin", color: "#B4C6E7" },
    wrapText: true,
    verticalAlignment: "center",
  };
  summarySheet.getRange("A3:F5").format.rowHeight = 24;
  summarySheet.getRange("A6:M6").merge();
  summarySheet.getRange("A6").values = [["주의: 실제 검색 로그가 아니라 검색광고 API의 최근 30일 검색량을 DataLab 일별 ratio로 배분한 추정치입니다."]];
  summarySheet.getRange("A6:M6").format = {
    fill: "#FFF2CC",
    font: { color: "#7F6000" },
    verticalAlignment: "center",
  };
  summarySheet.getRange("A6:M6").format.rowHeight = 24;

  const summaryHeaders = [
    "매장명", "키워드구분", "키워드", "PC_30일검색량", "모바일_30일검색량",
    "전체_30일검색량", "일간추정합계", "일평균", "최대검색일", "최대일간검색량",
    "DataLab_ratio합", "상태", "오류사유",
  ];
  const summaryRows = result.keywords.map((row) => [
    row.store_name ?? "", row.slot ?? "", row.keyword ?? "", row.monthly_pc ?? null,
    row.monthly_mobile ?? null, row.monthly_total ?? null, row.estimated_total ?? null,
    row.daily_average ?? null, excelDate(row.peak_date), row.peak_volume ?? null,
    row.ratio_sum ?? null, row.status ?? "", row.error_reason ?? "",
  ]);
  const summaryStart = 7;
  summarySheet.getRangeByIndexes(summaryStart, 0, 1, summaryHeaders.length).values = [summaryHeaders];
  applyHeaderStyle(summarySheet.getRangeByIndexes(summaryStart, 0, 1, summaryHeaders.length));
  if (summaryRows.length) {
    summarySheet.getRangeByIndexes(summaryStart + 1, 0, summaryRows.length, summaryHeaders.length).values = summaryRows;
    summarySheet.tables.add(`A${summaryStart + 1}:M${summaryStart + 1 + summaryRows.length}`, true, "KeywordSummaryTable");
    summarySheet.getRange(`D${summaryStart + 2}:G${summaryStart + 1 + summaryRows.length}`).format.numberFormat = "#,##0";
    summarySheet.getRange(`H${summaryStart + 2}:H${summaryStart + 1 + summaryRows.length}`).format.numberFormat = "#,##0.0";
    summarySheet.getRange(`I${summaryStart + 2}:I${summaryStart + 1 + summaryRows.length}`).format.numberFormat = "yyyy-mm-dd";
    summarySheet.getRange(`J${summaryStart + 2}:J${summaryStart + 1 + summaryRows.length}`).format.numberFormat = "#,##0";
    summarySheet.getRange(`K${summaryStart + 2}:K${summaryStart + 1 + summaryRows.length}`).format.numberFormat = "0.00";
    addStatusFormatting(summarySheet, `L${summaryStart + 2}:L${summaryStart + 1 + summaryRows.length}`);
  }
  setWidths(summarySheet, [24, 12, 24, 14, 16, 16, 14, 12, 14, 16, 15, 18, 36]);
  summarySheet.freezePanes.freezeRows(summaryStart + 1);

  const dailySheet = workbook.worksheets.add(dailyName);
  dailySheet.showGridLines = false;
  const dailyHeaders = [
    "매장명", "키워드구분", "키워드", "검색일", "PC_30일검색량", "모바일_30일검색량",
    "전체_30일검색량", "DataLab_ratio", "PC_일간추정량", "모바일_일간추정량",
    "전체_일간추정량", "상태", "오류사유",
  ];
  const dailyRows = result.daily_rows.map((row) => [
    row.store_name ?? "", row.slot ?? "", row.keyword ?? "", excelDate(row.search_date),
    row.monthly_pc ?? null, row.monthly_mobile ?? null, row.monthly_total ?? null,
    row.ratio ?? null, row.estimated_pc ?? null, row.estimated_mobile ?? null,
    row.estimated_total ?? null, row.status ?? "", row.error_reason ?? "",
  ]);
  dailySheet.getRangeByIndexes(0, 0, 1, dailyHeaders.length).values = [dailyHeaders];
  applyHeaderStyle(dailySheet.getRangeByIndexes(0, 0, 1, dailyHeaders.length));
  if (dailyRows.length) {
    dailySheet.getRangeByIndexes(1, 0, dailyRows.length, dailyHeaders.length).values = dailyRows;
    dailySheet.tables.add(`A1:M${dailyRows.length + 1}`, true, "DailyVolumeTable");
    dailySheet.getRange(`D2:D${dailyRows.length + 1}`).format.numberFormat = "yyyy-mm-dd";
    dailySheet.getRange(`E2:G${dailyRows.length + 1}`).format.numberFormat = "#,##0";
    dailySheet.getRange(`H2:H${dailyRows.length + 1}`).format.numberFormat = "0.00";
    dailySheet.getRange(`I2:K${dailyRows.length + 1}`).format.numberFormat = "#,##0";
    addStatusFormatting(dailySheet, `L2:L${dailyRows.length + 1}`);
  }
  setWidths(dailySheet, [24, 12, 24, 13, 14, 16, 16, 14, 14, 16, 16, 18, 36]);
  dailySheet.freezePanes.freezeRows(1);

  const formulaErrors = await workbook.inspect({
    kind: "match",
    searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
    options: { useRegex: true, maxResults: 50 },
    summary: "result workbook formula error scan",
  });
  const errorRecords = formulaErrors.ndjson
    .split("\n")
    .filter((line) => line.trim())
    .map((line) => JSON.parse(line));
  if (errorRecords.some((record) => Array.isArray(record.matches) && record.matches.length)) {
    throw new Error("formula error found in result workbook");
  }

  await fs.mkdir(path.dirname(path.resolve(args.output)), { recursive: true });
  await fs.mkdir(path.resolve(args["preview-dir"]), { recursive: true });
  await savePreview(
    workbook,
    summaryName,
    `A1:M${Math.min(summaryRows.length + summaryStart + 1, 48)}`,
    path.join(args["preview-dir"], "summary.png"),
  );
  await savePreview(
    workbook,
    dailyName,
    `A1:M${Math.min(dailyRows.length + 1, 61)}`,
    path.join(args["preview-dir"], "daily.png"),
  );
  const output = await SpreadsheetFile.exportXlsx(workbook);
  await output.save(args.output);
}

main().catch((error) => {
  process.stderr.write(`${error.stack ?? error.message}\n`);
  process.exitCode = 1;
});
