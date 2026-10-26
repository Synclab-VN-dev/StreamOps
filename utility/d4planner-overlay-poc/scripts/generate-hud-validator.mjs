import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import Ajv2020 from "ajv/dist/2020.js";
import addFormats from "ajv-formats";
import standaloneCode from "ajv/dist/standalone/index.js";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "..");
const schemaPath = path.resolve(root, "../d4planner/contracts/release1/v1/schemas/hud.schema.json");
const outputPath = path.resolve(root, "src/hud-validator.generated.ts");
const schema = JSON.parse(fs.readFileSync(schemaPath, "utf8"));
const ajv = new Ajv2020({ allErrors: true, strict: false, code: { source: true, esm: true } });
addFormats(ajv);
const validate = ajv.compile(schema);
const generated = standaloneCode(ajv, validate);
fs.writeFileSync(
  outputPath,
  `// @ts-nocheck\n// Generated from hud.schema.json; do not edit by hand.\n${generated}`,
  "utf8",
);
