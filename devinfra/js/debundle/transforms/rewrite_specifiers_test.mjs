import assert from "node:assert/strict";
import test from "node:test";

import { createArtifact, createChunk, createFile } from "../common/artifact.mjs";
import { parseModuleCode } from "../test_support/fixtures.mjs";
import { serializeGeneratedJsFile } from "../split/chunk.mjs";
import { rewriteChunkEntrySpecifiers, shouldRewriteChunkEntrySpecifiersForFile } from "./rewrite_specifiers.mjs";

test("shouldRewriteChunkEntrySpecifiersForFile skips selected-module lowered modules", () => {
  const file = createFile({
    path: "ui/example.js",
    ast: parseModuleCode('import "../dep.js";'),
    metadata: {
      chunkId: "static/app",
      role: "module",
      generated: {
        stage: "selected_module_lowering",
      },
    },
  });

  assert.equal(shouldRewriteChunkEntrySpecifiersForFile(file), false);
});

test("rewriteChunkEntrySpecifiers rewrites real source references but preserves shadowed workers", () => {
  const artifact = createArtifact({
    chunks: [
      createChunk({
        chunkId: "static/app",
        entryFile: "entry.js",
        metadata: { sourcePath: "static/app.js" },
        files: [
          createFile({
            path: "entry.js",
            ast: parseModuleCode(`
              import "./dep.js";
              import "../kept/entry.js";
              export { value } from "./shared.js";
              export * from "./all.js";
              await import("./lazy.js");
              new Worker("./worker.js");
              new SharedWorker("./shared-worker.js");
              function shadowed(Worker, SharedWorker) {
                new Worker("./shadowed-worker.js");
                return new SharedWorker("./shadowed-shared-worker.js");
              }
            `),
            metadata: {
              chunkId: "static/app",
              chunkFile: "entry.js",
              role: "entry",
              sourcePath: "static/app.js",
            },
          }),
        ],
      }),
      makeEntryChunk("static/dep", "static/dep.js"),
      makeEntryChunk("static/shared", "static/shared.js"),
      makeEntryChunk("static/all", "static/all.js"),
      makeEntryChunk("static/lazy", "static/lazy.js"),
      makeEntryChunk("static/worker", "static/worker.js"),
      makeEntryChunk("static/shared-worker", "static/shared-worker.js"),
      makeEntryChunk("static/kept", "static/kept.js"),
    ],
  });

  const rewritten = rewriteChunkEntrySpecifiers({ artifact });
  const entryFile = rewritten.artifact.chunks.get("static/app").files.get("entry.js");
  const code = serializeGeneratedJsFile({ ast: entryFile.ast });

  assert.match(code, /import "\.\.\/dep\/entry\.js";/);
  assert.match(code, /import "\.\.\/kept\/entry\.js";/);
  assert.match(code, /from "\.\.\/shared\/entry\.js";/);
  assert.match(code, /from "\.\.\/all\/entry\.js";/);
  assert.match(code, /import\("\.\.\/lazy\/entry\.js"\)/);
  assert.match(code, /new Worker\(new URL\("\.\.\/worker\/entry\.js", import\.meta\.url\)\)/);
  assert.match(code, /new SharedWorker\(new URL\("\.\.\/shared-worker\/entry\.js", import\.meta\.url\)\)/);
  assert.match(code, /new Worker\("\.\/shadowed-worker\.js"\)/);
  assert.match(code, /new SharedWorker\("\.\/shadowed-shared-worker\.js"\)/);
  assert.equal(rewritten.manifest.counts.files, 1);
  assert.equal(rewritten.manifest.counts.rewrites, 6);
  assert.equal(rewritten.manifest.counts.traversedFiles, 8);
});

function makeEntryChunk(chunkId, sourcePath) {
  return createChunk({
    chunkId,
    entryFile: "entry.js",
    metadata: { sourcePath },
    files: [
      createFile({
        path: "entry.js",
        ast: parseModuleCode("export const value = 1;"),
        metadata: {
          chunkId,
          chunkFile: "entry.js",
          role: "entry",
          sourcePath,
        },
      }),
    ],
  });
}
