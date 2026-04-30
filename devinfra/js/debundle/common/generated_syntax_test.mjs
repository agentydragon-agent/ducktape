import assert from "node:assert/strict";
import test from "node:test";

import {
  DEFAULT_GENERATED_JS_GLOBALS,
  GENERATED_JS_BROWSER_GLOBALS,
  GENERATED_JS_ECMASCRIPT_GLOBALS,
  validateGeneratedJsResolution,
  validateGeneratedJsSyntax,
} from "./generated_syntax.mjs";

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
      code: `window.ducktapeReady = document.body !== null && globalThis.location !== undefined;\nlocalStorage.setItem("ready", sessionStorage.getItem("ready") ?? "1");\nconst quota = new DOMException("quota", "QuotaExceededError");\nconst stream = new EventSource("/events");\nconst socket = new WebSocket("wss://example.invalid");\nconst file = new File(["payload"], "payload.txt");\nconst files = new FileList();\nconst reader = new FileReader();\nconst mediaStream = new MediaStream();\nconst recorder = new MediaRecorder(mediaStream);\nconst track = new MediaStreamTrack();\nconst encoded = encodeURIComponent(encodeURI("hello world"));\nconst decoded = decodeURIComponent(decodeURI(encoded));\nconst style = getComputedStyle(document.body);\nstream.close();\nsocket.close();\nreader.readAsText(file);\nfiles.item(0);\nrecorder.stop();\ntrack.stop();\nstyle.getPropertyValue(decoded);\n`,
      path: "static/app/modules/browser_globals.js",
    })
  );
});

test("generated JS resolution accepts function-scoped arguments", () => {
  assert.doesNotThrow(() =>
    validateGeneratedJsResolution({
      code: `export function install() {\n  window.gtag = function () {\n    window.dataLayer.push(arguments);\n  };\n  return () => arguments.length;\n}\n`,
      path: "static/app/modules/function_arguments.js",
    })
  );
});

test("generated JS default globals are sourced from ECMAScript and browser environments", () => {
  for (const name of ["AggregateError", "Iterator", "decodeURI", "encodeURIComponent"]) {
    assert.ok(GENERATED_JS_ECMASCRIPT_GLOBALS.includes(name), `${name} should be an ECMAScript global`);
    assert.ok(DEFAULT_GENERATED_JS_GLOBALS.has(name), `${name} should be allowed by default`);
  }
  for (const name of ["document", "File", "MediaRecorder", "WebSocket", "getComputedStyle"]) {
    assert.ok(GENERATED_JS_BROWSER_GLOBALS.includes(name), `${name} should be a browser global`);
    assert.ok(DEFAULT_GENERATED_JS_GLOBALS.has(name), `${name} should be allowed by default`);
  }
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

test("generated JS resolution rejects undeclared global writes without a fallback", () => {
  assert.throws(
    () =>
      validateGeneratedJsResolution({
        code: `const runtime = {};\nregeneratorRuntime = runtime;\n`,
        path: "static/app/modules/global_write.js",
      }),
    (error) => {
      assert.match(error.message, /\bregeneratorRuntime\b/);
      assert.match(error.message, /assignment target/);
      return true;
    }
  );
});

test("generated JS resolution rejects Node-style global aliases in generated modules", () => {
  assert.throws(
    () =>
      validateGeneratedJsResolution({
        code: `export const root = global;\n`,
        path: "static/app/modules/node_global_alias.js",
      }),
    (error) => {
      assert.match(error.message, /\bglobal\b/);
      return true;
    }
  );
});

test("generated JS resolution rejects top-level arguments in modules", () => {
  assert.throws(
    () =>
      validateGeneratedJsResolution({
        code: `export const args = arguments;\n`,
        path: "static/app/modules/top_level_arguments.js",
      }),
    (error) => {
      assert.match(error.message, /\barguments\b/);
      return true;
    }
  );
});

test("generated JS resolution rejects undeclared global read-modify-write patterns", () => {
  assert.throws(
    () =>
      validateGeneratedJsResolution({
        code: `try {\n  regeneratorRuntime = regeneratorRuntime || {};\n} catch {\n  globalThis.regeneratorRuntime = {};\n}\n`,
        path: "static/app/modules/global_read_modify_write.js",
      }),
    (error) => {
      assert.match(error.message, /\bregeneratorRuntime\b/);
      assert.match(error.message, /(assignment target|reference)/);
      return true;
    }
  );
});
