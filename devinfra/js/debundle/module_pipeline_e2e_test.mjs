import test from "node:test";
import {
  assertEntryOutput,
  assertGeneratedModuleAfterEntryScript,
  assertModuleExports,
  runLogicalModulesE2eFixture,
} from "./pipeline_e2e_support.mjs";

test("logical-module pipeline preserves source-order evaluation for split declarator fragments", async () => {
  const fixture = await runLogicalModulesE2eFixture({
    prefix: "debundle-logical-modules-split-declarator-order-",
    source: `const a = 1,
  b = 2,
  c = 3,
  d = a + b,
  e = d + c,
  f = e;
const z = "z";
console.log(f);
export { f, z };
`,
    operations: [
      {
        id: "logical__value",
        operation: "define_logical_module",
        selector: {
          chunkId: "static/app",
        },
        target: {
          path: "checks/value",
        },
        members: [
          {
            id: "member__f",
            name: "f",
            selector: {
              binding: {
                kind: "VariableDeclarator",
                name: "f",
              },
            },
          },
        ],
      },
    ],
  });

  assertModuleExports({
    includes: ["f"],
    modulePath: "static/app/modules/checks/value.js",
    outRoot: fixture.outRoot,
  });
  assertModuleExports({
    excludes: ["f"],
    modulePath: "static/app/modules/residual/unhandled.js",
    outRoot: fixture.outRoot,
  });
  assertEntryOutput(fixture, "6\n");
});

test("logical-module pipeline preserves function declaration hoisting across extracted modules", async () => {
  const fixture = await runLogicalModulesE2eFixture({
    prefix: "debundle-logical-modules-hoisted-functions-",
    source: `function a() {
  return b();
}
const c = a();
const d = Date.now();
function b() {
  return "b";
}
console.log(c);
export { c };
`,
    operations: [
      {
        id: "logical__helper",
        operation: "define_logical_module",
        selector: {
          chunkId: "static/app",
        },
        target: {
          path: "checks/hoisted_helper",
        },
        members: [
          {
            id: "member__a",
            name: "a",
            selector: {
              binding: {
                kind: "FunctionDeclaration",
                name: "a",
              },
            },
          },
          {
            id: "member__d",
            name: "d",
            selector: {
              binding: {
                kind: "VariableDeclarator",
                name: "d",
              },
            },
          },
          {
            id: "member__b",
            name: "b",
            selector: {
              binding: {
                kind: "FunctionDeclaration",
                name: "b",
              },
            },
          },
        ],
      },
      {
        id: "logical__consumer",
        operation: "define_logical_module",
        selector: {
          chunkId: "static/app",
        },
        target: {
          path: "checks/hoisted_consumer",
        },
        members: [
          {
            id: "member__c",
            name: "c",
            selector: {
              binding: {
                kind: "VariableDeclarator",
                name: "c",
              },
            },
          },
        ],
      },
    ],
  });

  assertModuleExports({
    excludes: ["c"],
    includes: ["a"],
    modulePath: "static/app/modules/checks/hoisted_helper.js",
    outRoot: fixture.outRoot,
  });
  assertModuleExports({
    excludes: ["a"],
    includes: ["c"],
    modulePath: "static/app/modules/checks/hoisted_consumer.js",
    outRoot: fixture.outRoot,
  });
  assertEntryOutput(fixture, "b\n");
});

test("logical-module pipeline preserves default references after readable and explicit renames", async () => {
  const fixture = await runLogicalModulesE2eFixture({
    prefix: "debundle-logical-modules-default-reference-readable-rename-",
    source: `const q = () => "a";
const b = ({ a: c = q } = {}) => c();
const z = "z";
console.log(b({}), b({ a: () => "b" }));
export { q, b, z };
`,
    operations: [
      {
        id: "logical__default_reference",
        operation: "define_logical_module",
        selector: {
          chunkId: "static/app",
        },
        target: {
          path: "checks/default_reference",
        },
        members: [
          {
            id: "member__a",
            name: "a",
            selector: {
              binding: {
                kind: "VariableDeclarator",
                name: "q",
              },
            },
          },
          {
            id: "member__b",
            name: "b",
            selector: {
              binding: {
                kind: "VariableDeclarator",
                name: "b",
              },
            },
          },
        ],
      },
    ],
  });

  assertModuleExports({
    includes: ["a", "b"],
    modulePath: "static/app/modules/checks/default_reference.js",
    outRoot: fixture.outRoot,
  });
  assertModuleExports({
    excludes: ["a", "b"],
    modulePath: "static/app/modules/residual/unhandled.js",
    outRoot: fixture.outRoot,
  });
  assertEntryOutput(fixture, "a b\n");
});

test("logical-module pipeline imports renamed dependencies across split declarators", async () => {
  const fixture = await runLogicalModulesE2eFixture({
    prefix: "debundle-logical-modules-renamed-dependency-",
    source: `const q = o => o.a,
  r = o => o.b;
const s = o => q(o) ?? r(o);
console.log(s({ a: null, b: "c" }));
export { s };
`,
    operations: [
      {
        id: "logical__uv",
        operation: "define_logical_module",
        selector: {
          chunkId: "static/app",
        },
        target: {
          path: "m/uv",
        },
        members: [
          {
            id: "member__u",
            name: "u",
            selector: {
              binding: {
                kind: "VariableDeclarator",
                name: "q",
              },
            },
          },
          {
            id: "member__v",
            name: "v",
            selector: {
              binding: {
                kind: "VariableDeclarator",
                name: "r",
              },
            },
          },
        ],
      },
      {
        id: "logical__w",
        operation: "define_logical_module",
        selector: {
          chunkId: "static/app",
        },
        target: {
          path: "m/w",
        },
        members: [
          {
            id: "member__w",
            name: "w",
            selector: {
              binding: {
                kind: "VariableDeclarator",
                name: "s",
              },
            },
          },
        ],
      },
    ],
  });

  assertModuleExports({
    includes: ["u", "v"],
    modulePath: "static/app/modules/m/uv.js",
    outRoot: fixture.outRoot,
  });
  assertModuleExports({
    excludes: ["u"],
    includes: ["w"],
    modulePath: "static/app/modules/m/w.js",
    outRoot: fixture.outRoot,
  });
  assertGeneratedModuleAfterEntryScript({
    expectedStdout: "d\n",
    outRoot: fixture.outRoot,
    source: `const { w } = await import("./static/app/modules/m/w.js");
console.log(w({ a: null, b: "d" }));
`,
  });
  assertEntryOutput(fixture, "c\n");
});

test("logical-module pipeline imports lazy dependencies through destructuring", async () => {
  const fixture = await runLogicalModulesE2eFixture({
    prefix: "debundle-logical-modules-destructuring-dependency-",
    source: `const q = (o, k) => ({ x: o.a.get(k), y: "a" }),
  r = (o, k) => ({ x: o.b.get(k), y: "b" });
const s = x => x,
  t = x => s(x),
  u = o => {
    const {
        a,
        c
      } = o,
      d = a.get("d");
    const {
        x,
        y
      } = d !== "c" ? q(o, "x") : c.e ? r(o, "x") : q(o, "x");
    return t(x ?? y);
  };
console.log(u({ a: new Map([["x", "p"]]), b: new Map(), c: { e: false } }));
export { u };
`,
    operations: [
      {
        id: "logical__fg",
        operation: "define_logical_module",
        selector: {
          chunkId: "static/app",
        },
        target: {
          path: "m/fg",
        },
        members: [
          {
            id: "member__f",
            name: "f",
            selector: {
              binding: {
                kind: "VariableDeclarator",
                name: "q",
              },
            },
          },
          {
            id: "member__g",
            name: "g",
            selector: {
              binding: {
                kind: "VariableDeclarator",
                name: "r",
              },
            },
          },
        ],
      },
      {
        id: "logical__hij",
        operation: "define_logical_module",
        selector: {
          chunkId: "static/app",
        },
        target: {
          path: "m/hij",
        },
        members: [
          {
            id: "member__h",
            name: "h",
            selector: {
              binding: {
                kind: "VariableDeclarator",
                name: "s",
              },
            },
          },
          {
            id: "member__i",
            name: "i",
            selector: {
              binding: {
                kind: "VariableDeclarator",
                name: "t",
              },
            },
          },
          {
            id: "member__j",
            name: "j",
            selector: {
              binding: {
                kind: "VariableDeclarator",
                name: "u",
              },
            },
          },
        ],
      },
    ],
  });

  assertModuleExports({
    includes: ["f", "g"],
    modulePath: "static/app/modules/m/fg.js",
    outRoot: fixture.outRoot,
  });
  assertModuleExports({
    excludes: ["f"],
    includes: ["j"],
    modulePath: "static/app/modules/m/hij.js",
    outRoot: fixture.outRoot,
  });
  assertGeneratedModuleAfterEntryScript({
    expectedStdout: "q\n",
    outRoot: fixture.outRoot,
    source: `const { j } = await import("./static/app/modules/m/hij.js");
console.log(j({
  a: new Map([["d", "c"]]),
  b: new Map([["x", "q"]]),
  c: { e: true },
}));
`,
  });
  assertEntryOutput(fixture, "p\n");
});

test("logical-module pipeline closes explicit modules over helper dependencies", async () => {
  const fixture = await runLogicalModulesE2eFixture({
    prefix: "debundle-logical-modules-helper-closure-",
    source: `const q = m => {
  throw TypeError(m);
};
const r = x => {
  if (typeof x !== "object") q("a");
  return x.a();
};
function s() {
  return r({ a: () => "b" });
}
console.log(s());
export { s };`,
    operations: [
      {
        id: "logical__a",
        operation: "define_logical_module",
        selector: {
          chunkId: "static/app",
        },
        target: {
          path: "m/a",
        },
        members: [
          {
            id: "member__a",
            name: "a",
            selector: {
              binding: {
                kind: "VariableDeclarator",
                name: "r",
              },
            },
          },
        ],
      },
    ],
  });

  assertModuleExports({
    includes: ["a"],
    modulePath: "static/app/modules/m/a.js",
    outRoot: fixture.outRoot,
  });
  assertModuleExports({
    excludes: ["a", "q"],
    modulePath: "static/app/modules/residual/unhandled.js",
    outRoot: fixture.outRoot,
  });
  assertGeneratedModuleAfterEntryScript({
    expectedStdout: "c\nTypeError\n",
    outRoot: fixture.outRoot,
    source: `const { a } = await import("./static/app/modules/m/a.js");
console.log(a({ a: () => "c" }));
try {
  a(1);
} catch (error) {
  console.log(error.name);
}
`,
  });
  assertEntryOutput(fixture, "b\n");
});

test("logical-module pipeline keeps shared bootstrap dependencies in named modules", async () => {
  const fixture = await runLogicalModulesE2eFixture({
    prefix: "debundle-logical-modules-bootstrap-shared-dependencies-",
    source: `const q = "a";
function r() {
  return q;
}
function s() {
  return "b" + r();
}
function t() {
  return s() + r();
}
console.log(t());
export { t, s };`,
    operations: [
      {
        id: "logical__s",
        operation: "define_logical_module",
        selector: {
          chunkId: "static/app",
        },
        target: {
          path: "m/s",
        },
        members: [
          {
            id: "member__s",
            name: "s",
            selector: {
              binding: {
                kind: "FunctionDeclaration",
                name: "s",
              },
            },
          },
        ],
      },
      {
        id: "logical__t",
        operation: "define_logical_module",
        selector: {
          chunkId: "static/app",
        },
        target: {
          path: "m/t",
        },
        members: [
          {
            id: "member__t",
            name: "t",
            selector: {
              binding: {
                kind: "FunctionDeclaration",
                name: "t",
              },
            },
          },
        ],
      },
    ],
  });

  assertModuleExports({
    includes: ["r", "s"],
    modulePath: "static/app/modules/m/s.js",
    outRoot: fixture.outRoot,
  });
  assertModuleExports({
    excludes: ["r", "s"],
    includes: ["t"],
    modulePath: "static/app/modules/m/t.js",
    outRoot: fixture.outRoot,
  });
  assertGeneratedModuleAfterEntryScript({
    expectedStdout: "ba\na\nbaa\n",
    outRoot: fixture.outRoot,
    source: `const x = await import("./static/app/modules/m/s.js");
const y = await import("./static/app/modules/m/t.js");
console.log(x.s());
console.log(x.r());
console.log(y.t());
`,
  });
  assertEntryOutput(fixture, "baa\n");
});
