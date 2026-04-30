import assert from "node:assert/strict";
import test from "node:test";
import * as t from "@babel/types";

import { createArtifact, createFile } from "../common/artifact.mjs";
import { createWebFixtureRoots } from "../test_support/fixtures.mjs";
import { writeJsTree } from "./write.mjs";

test("writeJsTree rejects emitted modules that do not parse", () => {
  const { outRoot } = createWebFixtureRoots("debundle-write-js-tree-syntax-");
  const artifact = createArtifact({
    chunks: [
      {
        chunkId: "static/app",
        entryFile: "entry.js",
        files: [
          createFile({
            path: "entry.js",
            ast: invalidReservedDefaultBindingAst(),
            metadata: {
              chunkId: "static/app",
              chunkFile: "entry.js",
              role: "entry",
            },
          }),
        ],
      },
    ],
  });

  assert.throws(
    () =>
      writeJsTree({
        artifact,
        force: true,
        outDir: outRoot,
      }),
    (error) => {
      assert.match(error.message, /writeJsTree emitted invalid JavaScript/);
      assert.match(error.message, /static\/app\/entry\.js/);
      assert.match(error.message, /default/);
      return true;
    }
  );
});

function invalidReservedDefaultBindingAst() {
  return t.file(
    t.program([
      t.variableDeclaration("const", [t.variableDeclarator(t.identifier("source"), t.objectExpression([]))]),
      t.variableDeclaration("const", [
        t.variableDeclarator(
          t.objectPattern([t.objectProperty(t.identifier("default"), t.identifier("default"), false, true)]),
          t.identifier("source")
        ),
      ]),
    ])
  );
}
