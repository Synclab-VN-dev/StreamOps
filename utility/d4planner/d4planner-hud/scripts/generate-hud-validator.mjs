import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import Ajv2020 from "ajv/dist/2020.js";
import addFormats from "ajv-formats";
import standaloneCode from "ajv/dist/standalone/index.js";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "..");
const schemaPath = path.resolve(root, "../d4planner-be/contracts/release1/v1/schemas/hud.schema.json");
const outputPath = path.resolve(root, "src/hud-validator.generated.ts");
const schema = JSON.parse(fs.readFileSync(schemaPath, "utf8"));
const ajv = new Ajv2020({ allErrors: true, strict: false, code: { source: true, esm: true } });
addFormats(ajv);
const validate = ajv.compile(schema);
const generated = standaloneCode(ajv, validate)
  .replace('require("ajv/dist/runtime/ucs2length").default', 'ucs2length')
  .replace('require("ajv-formats/dist/formats").fullFormats["date-time"]', 'fullFormats["date-time"]');
fs.writeFileSync(
  outputPath,
  `// @ts-nocheck\n// Generated from hud.schema.json; do not edit by hand.\nimport ucs2length from "ajv/dist/runtime/ucs2length.js";\nimport formats from "ajv-formats/dist/formats.js";\nconst fullFormats = formats.fullFormats ?? formats;\n${generated}`,
  "utf8",
);
