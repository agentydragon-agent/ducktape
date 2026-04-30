import assert from "node:assert/strict";
import test from "node:test";

import { validateGeneratedJsResolution, validateGeneratedJsSyntax } from "./generated_syntax.mjs";

test("generated JS resolution accepts imported generated helpers", () => {
  assert.doesNotThrow(() =>
    validateGeneratedJsResolution({
      code: `import { helper } from "./helper.js";\nexport const value = helper();\n`,
      path: "static/app/modules/consumer.js",
    })
  );
});

test("generated JS resolution accepts browser runtime globals", () => {
  assert.doesNotThrow(() =>
    validateGeneratedJsResolution({
      code: `window.ducktapeReady = document.body !== null && globalThis.location !== undefined;\n`,
      path: "static/app/modules/browser_globals.js",
    })
  );
});

test("generated JS resolution rejects missing generated imports that syntax accepts", () => {
  const code = `export function run() {\n  return Hn(Tt);\n}\n`;

  assert.doesNotThrow(() =>
    validateGeneratedJsSyntax({
      code,
      path: "static/app/modules/missing_generated_import.js",
    })
  );
  assert.throws(
    () =>
      validateGeneratedJsResolution({
        code,
        context: {
          chunkFile: "modules/missing_generated_import.js",
          chunkId: "static/app",
          moduleExtraction: {
            id: "logical_module_0007",
            nameHint: "TanaCard",
            ownerIds: ["owner_00042"],
          },
          role: "module",
        },
        path: "static/app/modules/missing_generated_import.js",
      }),
    (error) => {
      assert.match(error.message, /static\/app\/modules\/missing_generated_import\.js:2:10/);
      assert.match(error.message, /\bHn\b/);
      assert.match(error.message, /logical_module_0007/);
      assert.match(error.message, /owner_00042/);
      return true;
    }
  );
});

test("generated JS resolution rejects final-name import/body rename mismatches", () => {
  assert.throws(
    () =>
      validateGeneratedJsResolution({
        code: `import { oldName } from "./dep.js";\nexport const value = finalName();\n`,
        path: "static/app/modules/rename_mismatch.js",
      }),
    (error) => {
      assert.match(error.message, /static\/app\/modules\/rename_mismatch\.js:2:22/);
      assert.match(error.message, /\bfinalName\b/);
      return true;
    }
  );
});

test("generated JS resolution rejects private helpers used cross-module without import", () => {
  assert.throws(
    () =>
      validateGeneratedJsResolution({
        code: `export const value = privateHelper();\n`,
        path: "static/app/modules/private_helper_consumer.js",
      }),
    (error) => {
      assert.match(error.message, /static\/app\/modules\/private_helper_consumer\.js:1:22/);
      assert.match(error.message, /\bprivateHelper\b/);
      return true;
    }
  );
});
