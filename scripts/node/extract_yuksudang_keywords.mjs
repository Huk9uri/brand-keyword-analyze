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
  if (!args.input || !args.output) {
    throw new Error("--input and --output are required");
  }
  return args;
}

function text(value) {
  if (value === null || value === undefined) return null;
  const normalized = String(value).trim();
  return normalized || null;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const blob = await FileBlob.load(args.input);
  const workbook = await SpreadsheetFile.importXlsx(blob);
  const sheetName = args.sheet || "육수당 키워드검색량0513";
  const sheet = workbook.worksheets.getItem(sheetName);
  if (!sheet) throw new Error(`sheet not found: ${sheetName}`);

  const used = sheet.getUsedRange(true);
  if (!used) throw new Error(`sheet has no values: ${sheetName}`);
  const values = used.values;
  const headerRowIndex = args.sheet ? 0 : 1;
  const headerRow = values[headerRowIndex] ?? [];
  const keywordColumns = args["keyword-prefix"]
    ? Array.from({ length: 5 }, (_, index) => {
        const header = `${args["keyword-prefix"]}${index + 1}`;
        return [headerRow.findIndex((value) => text(value) === header), header];
      })
    : [[13, "키워드1"], [19, "키워드2"], [25, "키워드3"]];
  const storeColumn = args.sheet
    ? headerRow.findIndex((value) => text(value) === "매장명")
    : 0;
  const expectedHeaders = [[storeColumn, "매장명"], ...keywordColumns];
  for (const [index, expected] of expectedHeaders) {
    if (index < 0 || text(headerRow[index]) !== expected) {
      throw new Error(`unexpected header at row ${headerRowIndex + 1} column ${index + 1}: expected ${expected}`);
    }
  }

  let stores = values.slice(headerRowIndex + 1).flatMap((row, offset) => {
    const storeName = text(row[storeColumn]);
    if (!storeName) return [];
    return [{
      source_row: offset + headerRowIndex + 2,
      store_name: storeName,
      keywords: keywordColumns.map(([column], index) => ({
        slot: `keyword${index + 1}`,
        keyword: text(row[column]),
      })),
    }];
  });

  if (args.store) {
    stores = stores.filter((store) => store.store_name === args.store);
    if (!stores.length) throw new Error(`store not found: ${args.store}`);
  }
  if (!stores.length) throw new Error("no store rows found");

  const output = {
    source_file: path.resolve(args.input),
    sheet: sheetName,
    stores,
  };
  await fs.mkdir(path.dirname(path.resolve(args.output)), { recursive: true });
  await fs.writeFile(args.output, JSON.stringify(output, null, 2), "utf8");
}

main().catch((error) => {
  process.stderr.write(`${error.message}\n`);
  process.exitCode = 1;
});
