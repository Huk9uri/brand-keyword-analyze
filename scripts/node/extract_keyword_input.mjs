import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const args = Object.fromEntries(Array.from({length: process.argv.slice(2).length / 2}, (_, i) => [process.argv[2 + i * 2].slice(2), process.argv[3 + i * 2]]));
if (!args.input || !args.output) throw new Error("--input and --output are required");
const text = (value) => String(value ?? "").trim() || null;
const normalize = (value) => String(value ?? "").trim().replace(/\s+/g, "").toLowerCase();
const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(args.input));
const sheet = workbook.worksheets.getItem("키워드입력");
if (!sheet) throw new Error("sheet not found: 키워드입력");
const values = sheet.getUsedRange(true)?.values ?? [];
const headers = values[0] ?? [];
const storeColumn = headers.findIndex((value) => text(value) === "매장명");
const keywordColumns = Array.from({length: 5}, (_, i) => ({index: headers.findIndex((value) => text(value) === `키워드${i + 1}`), slot: `keyword${i + 1}`})).filter((item) => item.index >= 0);
let stores = values.slice(1).flatMap((row, offset) => {
  const storeName = text(row[storeColumn]);
  if (!storeName) return [];
  const seen = new Set();
  const keywords = keywordColumns.flatMap(({index, slot}) => {
    const keyword = text(row[index]);
    const key = normalize(keyword);
    if (!key || seen.has(key)) return [];
    seen.add(key);
    return [{slot, keyword}];
  });
  return [{source_row: offset + 2, store_name: storeName, keywords}];
});
if (args.store) stores = stores.filter((store) => store.store_name === args.store);
await fs.mkdir(path.dirname(path.resolve(args.output)), {recursive: true});
await fs.writeFile(args.output, JSON.stringify({source_file: path.resolve(args.input), sheet: "키워드입력", stores}, null, 2), "utf8");
