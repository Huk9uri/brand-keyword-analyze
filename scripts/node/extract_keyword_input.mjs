import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

function parseArgs(argv) {
  const args = {};
  for (let i = 0; i < argv.length; i += 2) args[argv[i].slice(2)] = argv[i + 1];
  if (!args.input || !args.output) throw new Error("--input and --output are required");
  return args;
}
const text = (value) => String(value ?? "").trim() || null;
const normalize = (value) => String(value ?? "").trim().replace(/\s+/g, "").toLowerCase();

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(args.input));
  const sheet = workbook.worksheets.items.find((item) => item.name === "키워드입력");
  if (!sheet) throw new Error("sheet not found: 키워드입력");
  const values = sheet.getUsedRange(true)?.values ?? [];
  const headers = values[0] ?? [];
  const headerTexts = headers.map(text);
  const storeColumn = headerTexts.indexOf("매장명");
  if (storeColumn < 0) throw new Error("missing required header: 매장명");
  if (!headerTexts.includes("키워드1")) throw new Error("missing required header: 키워드1");
  const unsupported = headerTexts.find((value) => /^키워드\d+$/.test(value ?? "") && Number(value.slice(3)) > 5);
  if (unsupported) throw new Error(`${unsupported}: 매장당 6개 이상은 앵커 키워드 기반 별도 모델이 필요합니다`);
  const keywordColumns = Array.from({length: 5}, (_, i) => ({index: headerTexts.indexOf(`키워드${i + 1}`), slot: `keyword${i + 1}`})).filter((item) => item.index >= 0);
  const errors = [];
  const storeNames = new Set();
  let stores = [];
  for (let offset = 0; offset < values.slice(1).length; offset += 1) {
    const row = values[offset + 1];
    const sourceRow = offset + 2;
    if (!row.some((value) => text(value))) continue;
    const storeName = text(row[storeColumn]);
    if (!storeName) { errors.push(`row ${sourceRow}: store name is required`); continue; }
    if (storeName === "예시 매장명" || storeName.startsWith("예시:")) { errors.push(`row ${sourceRow}: 예시 행을 삭제하세요`); continue; }
    if (storeNames.has(storeName)) { errors.push(`row ${sourceRow}: duplicate store name: ${storeName}`); continue; }
    storeNames.add(storeName);
    const seen = new Set();
    const keywords = keywordColumns.flatMap(({index, slot}) => {
      const keyword = text(row[index]);
      const key = normalize(keyword);
      if (!key || seen.has(key)) return [];
      seen.add(key);
      return [{slot, keyword}];
    });
    if (!keywords.length) { errors.push(`row ${sourceRow}: at least one keyword is required`); continue; }
    stores.push({source_row: sourceRow, store_name: storeName, keywords});
  }
  if (errors.length) throw new Error(`${errors.join("\n")}\ninput validation failed`);
  if (args.store) {
    stores = stores.filter((store) => store.store_name === args.store);
    if (!stores.length) throw new Error(`store not found: ${args.store}`);
  }
  await fs.mkdir(path.dirname(path.resolve(args.output)), {recursive: true});
  await fs.writeFile(args.output, JSON.stringify({source_file: path.resolve(args.input), sheet: "키워드입력", stores}, null, 2), "utf8");
}

main().catch((error) => { process.stderr.write(`${error.message}\n`); process.exitCode = 1; });
