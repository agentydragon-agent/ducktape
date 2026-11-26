import assert from "node:assert/strict";
import { existsSync, writeFileSync } from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { split } from "../testing/split.mjs";
import {
  assertCertified,
  browserLoweringAssumptions,
  browserObservedAssumptions,
  arrow,
  block,
  call,
  caseShard,
  conditional,
  browserProfileAssumptions,
  exportNamed,
  expression,
  id,
  literal,
  lower,
  moduleEvaluationOrder,
  observe,
  prepare,
  program,
  returns,
  root,
  threeUnitFixture as fixture,
  throws,
  variable,
} from "./harness.mjs";

const profile = path.join(root, "page.json");
writeFileSync(profile, JSON.stringify({ profile: "browser-page" }));
const nodeProfile = path.join(root, "node-recording.json");
writeFileSync(nodeProfile, JSON.stringify({ profile: "node-recording" }));
const entry = "entry.mjs";
const includesCase = caseShard();

const nodeProfileFixture = fixture(
  "node-recording-profile",
  "const moved = 1; const kept = 2; export const result = moved + kept;"
);
const nodeProfileVerdict = split({
  source: nodeProfileFixture.sourceFile,
  spec: nodeProfileFixture.specFile,
  out: nodeProfileFixture.out,
  hostContract: nodeProfile,
});
assert.equal(nodeProfileVerdict.status, "certified", nodeProfileVerdict.log);
assert.equal(nodeProfileVerdict.verdict.hostProfile, "node-recording");
assert(existsSync(nodeProfileFixture.out));

if (includesCase("shared-ecmascript-symbol-node")) {
  const symbolFixture = fixture(
    "shared-ecmascript-symbol-node",
    'const brand = Symbol("node-host"); const result = typeof brand; export { result };'
  );
  const verdict = symbolFixture.run("--host-contract", nodeProfile);
  assert.equal(verdict.status, "certified", JSON.stringify(verdict));
  assert.deepEqual(
    [...verdict.assumptions].sort(),
    [
      "Symbol returns the intrinsic Symbol function without observable effects throughout initialization",
      "the ambient Symbol binding is the unmodified ECMAScript intrinsic throughout initialization",
      "the intrinsic Symbol operations return fresh symbols and canonical well-known symbols without observable effects throughout initialization",
    ].sort()
  );
  for (const file of [symbolFixture.sourceFile, path.join(symbolFixture.out, entry)]) {
    assert.equal((await import(pathToFileURL(file).href)).result, "symbol");
  }
}

if (includesCase("shadowed-symbol-is-not-intrinsic")) {
  const shadowed = fixture(
    "shadowed-symbol-is-not-intrinsic",
    'const read = (Symbol) => Symbol.iterator; const result = read({ iterator: "shadowed" }); export { result };'
  );
  const verdict = shadowed.run("--host-contract", profile);
  assert.equal(verdict.status, "certified", JSON.stringify(verdict));
  assert.deepEqual(verdict.assumptions, []);
  for (const file of [shadowed.sourceFile, path.join(shadowed.out, entry)]) {
    assert.equal((await import(pathToFileURL(file).href)).result, "shadowed");
  }
}

for (const [binding, defaulted] of [
  ["ambient", false],
  ["local", false],
  ["ambient", true],
  ["local", true],
]) {
  const name = defaulted ? `${binding}-default` : binding;
  if (!includesCase(name)) continue;
  const local = binding === "local";
  const parameters = local ? [id("window")] : [];
  const type = {
    type: "UnaryExpression",
    prefix: true,
    operator: "typeof",
    argument: id("window"),
  };
  if (defaulted) parameters.push({ type: "AssignmentPattern", left: id("value"), right: type });
  const read = arrow(parameters, defaulted ? id("value") : type);
  const test = fixture(
    name,
    program([
      variable("const", "read", read),
      variable("const", "result", call(id("read"), local ? [literal(42)] : [])),
      exportNamed([["result", "result"]]),
    ])
  );
  if (!local) {
    assert.match(test.run().reason, /unsupported global window/);
    assert(!existsSync(test.out));
  }
  const verdict = test.run("--host-contract", profile);
  assert.equal(verdict.status, "certified", JSON.stringify(verdict));
  assert.equal(verdict.hostProfile, "browser-page");
  assert.deepEqual(
    browserObservedAssumptions(verdict.assumptions),
    local
      ? []
      : [
          "window, globalThis, and self return the same page global object throughout initialization",
          "typeof window is object without observable effects throughout initialization",
        ]
  );
  assert.deepEqual(browserProfileAssumptions(verdict.assumptions), []);
  assert.deepEqual(test.run("--host-contract", profile, "--check-output"), verdict);
  // Supply the single observation promised by the profile in this Node realm.
  globalThis.window = {};
  try {
    for (const file of [test.sourceFile, path.join(test.out, entry)]) {
      assert.equal((await import(pathToFileURL(file).href)).result, local ? "number" : "object");
    }
  } finally {
    delete globalThis.window;
  }
}

// Preserve the ambient symbol operations and the captured initializer across the split.
// The provider defers invoking the factory until after initialization.
if (includesCase("deferred-ambient-symbol")) {
  const dir = path.join(root, "deferred-ambient-symbol");
  const files = prepare(dir, {
    source: `
      import { defer } from "./provider.mjs";
      const load = defer(() => [Symbol.for(moved()), Symbol.iterator]);
      const moved = () => "fixture";
      export { load, moved };
    `,
    provider: "export const defer = (factory) => () => factory();",
    spec: {
      entry,
      modules: { [entry]: ["#0", "#1", "#3"], "worker.mjs": ["#2"] },
      order: ["worker.mjs"],
      sequential: true,
    },
  });
  const out = path.join(dir, "out");
  const { verdict, log } = lower(files.sourceFile, files.specFile, out);
  assertCertified(verdict, log);
  assert.equal(verdict.hostProfile, undefined);
  for (const file of [files.sourceFile, path.join(out, entry)]) {
    const namespace = await import(pathToFileURL(file).href);
    assert.equal(namespace.moved(), "fixture");
    assert.deepEqual(namespace.load(), [Symbol.for("fixture"), Symbol.iterator]);
  }
}

if (includesCase("caught-opaque-symbol-for")) {
  const caughtSymbol = fixture(
    "caught-opaque-symbol-for",
    'const read = () => { try { return Symbol.for((() => { throw "argument"; })()); } catch { return "caught"; } }; const result = read(); export { result };'
  );
  assert.match(caughtSymbol.run().reason, /unknown.*ambient member Symbol\.for is reached/);
  assert(!existsSync(caughtSymbol.out));
}

if (includesCase("reached-symbol-iterator")) {
  const reachedIterator = fixture(
    "reached-symbol-iterator",
    "const read = () => Symbol.iterator; const result = read(); export { result };"
  );
  assert.match(reachedIterator.run().reason, /unknown.*ambient member Symbol\.iterator is reached/);
  assert(!existsSync(reachedIterator.out));
}

if (includesCase("deferred-ambient-object")) {
  const dir = path.join(root, "deferred-ambient-object");
  const files = prepare(dir, {
    source: `
      import { defer } from "./provider.mjs";
      const load = defer(function summarize(prefix) {
        return Object.assign({}, { label: prefix + moved() });
      });
      const moved = () => "fixture";
      export { load, moved };
    `,
    provider: "export const defer = (factory) => factory;",
    spec: {
      entry,
      modules: { [entry]: ["#0", "#1", "#3"], "worker.mjs": ["#2"] },
      order: ["worker.mjs"],
      sequential: true,
    },
  });
  const out = path.join(dir, "out");
  const { verdict, log } = lower(files.sourceFile, files.specFile, out);
  assertCertified(verdict, log);
  assert.deepEqual(lower(files.sourceFile, files.specFile, out, ["--check-output"]).verdict, verdict);
  for (const file of [files.sourceFile, path.join(out, entry)]) {
    const { load } = await import(pathToFileURL(file).href);
    assert.equal(load.name, "summarize");
    assert.equal(load.length, 1);
    assert.deepEqual(load("deferred "), { label: "deferred fixture" });
  }
}

if (includesCase("reached-retained-body")) {
  const reachedBody = fixture(
    "reached-retained-body",
    `const read = () => {
    const unopened = () => document.title;
    const called = () => Object.keys({});
    try { return called(); } catch { return "caught"; }
  };
  const result = read();
  export { result };`
  );
  assert.match(reachedBody.run().reason, /unknown.*deferred function called: unsupported global Object/);
  assert(!existsSync(reachedBody.out));
}

for (const args of [[], [literal("absent")]]) {
  for (const reached of [false, true]) {
    const name = `opaque-error-${args.length}-${reached}`;
    if (!includesCase(name)) continue;
    const construction = { type: "NewExpression", callee: id("Error"), arguments: args };
    const source = program([
      variable("const", "read", arrow([id("fail")], conditional(id("fail"), construction, literal(42)))),
      variable("const", "result", call(id("read"), [literal(reached)])),
      exportNamed([["result", "result"]]),
    ]);
    const test = fixture(name, source);
    assert.match(test.run().reason, /unsupported global Error/);
    const verdict = test.run("--host-contract", profile);
    if (reached) {
      assert.match(verdict.reason, /unknown.*ambient constructor Error is reached/);
      assert(!existsSync(test.out));
    } else {
      assert.equal(verdict.status, "certified", JSON.stringify(verdict));
      assert.deepEqual(browserObservedAssumptions(verdict.assumptions), []);
      assert.deepEqual(test.run("--host-contract", profile, "--check-output"), verdict);
      for (const file of [test.sourceFile, path.join(test.out, entry)]) {
        assert.equal((await import(pathToFileURL(file).href)).result, 42);
      }
    }
  }
}

// A catch cannot turn unknown host construction into a proved normal return.
if (includesCase("caught-opaque-error")) {
  const caught = fixture(
    "caught-opaque-error",
    'const read = () => { try { throw new Error((() => { throw "argument"; })()); } catch { return 7; } }; const result = read(); export { result };'
  );
  assert.match(caught.run("--host-contract", profile).reason, /unknown.*ambient constructor Error is reached/);
  assert(!existsSync(caught.out));
}

if (includesCase("shadowed-host-bindings")) {
  for (const [hostName, hostProfile] of [
    ["browser", profile],
    ["node", nodeProfile],
  ]) {
    const lexical = fixture(
      `shadowed-host-bindings-${hostName}`,
      `const read = () => {
    class Error { value = "local"; }
    const Symbol = { for: (key) => key };
    return Symbol.for((new Error()).value);
  };
  const result = read(); export { result };`
    );
    const localVerdict = lexical.run("--host-contract", hostProfile);
    assert.equal(localVerdict.status, "certified", JSON.stringify(localVerdict));
    assert.deepEqual(browserObservedAssumptions(localVerdict.assumptions), []);
    for (const file of [lexical.sourceFile, path.join(lexical.out, entry)]) {
      assert.equal((await import(pathToFileURL(file).href)).result, "local");
    }
  }
}

// Both constructs occur in the same program. The crossing is valid in a page.
// In a realm without window, it reaches the deferred constructor in the split only.
for (const pageSkipsError of [true, false]) {
  const name = `profile-reversal-${pageSkipsError}`;
  if (!includesCase(name)) continue;
  const scope = path.join(root, name);
  const order = ["worker.mjs", "reader.mjs", "state.mjs"];
  const files = prepare(scope, {
    source: program([
      {
        type: "FunctionDeclaration",
        id: id("read"),
        params: [],
        generator: false,
        async: false,
        body: block([
          {
            type: "IfStatement",
            test: {
              type: "BinaryExpression",
              operator: pageSkipsError ? "===" : "!==",
              left: { type: "UnaryExpression", operator: "typeof", prefix: true, argument: id("window") },
              right: literal("object"),
            },
            consequent: returns(literal("page")),
            alternate: null,
          },
          {
            type: "IfStatement",
            test: { type: "BinaryExpression", operator: "===", left: id("current"), right: id("undefined") },
            consequent: throws({ type: "NewExpression", callee: id("Error"), arguments: [literal("too early")] }),
            alternate: null,
          },
          returns(id("current")),
        ]),
      },
      variable("var", "current", null),
      expression({ type: "AssignmentExpression", operator: "=", left: id("current"), right: literal("ready") }),
      variable("const", "result", call(id("read"))),
      exportNamed([["result", "result"]]),
    ]),
    provider: "",
    spec: {
      entry,
      modules: { "worker.mjs": ["#0"], "state.mjs": ["#1", "#2"], "reader.mjs": ["#3"], [entry]: ["#4"] },
      order,
      sequential: true,
    },
  });
  const out = path.join(scope, "out");
  const { verdict, log } = lower(files.sourceFile, files.specFile, out, ["--host-contract", profile]);
  if (!pageSkipsError) {
    assert.match(verdict.reason, /split reached an unknown result.*ambient constructor Error is reached/);
    assert(!existsSync(out));
    continue;
  }
  assert.equal(verdict.status, "certified", log);
  assert.deepEqual(browserObservedAssumptions(verdict.assumptions), [
    "window, globalThis, and self return the same page global object throughout initialization",
    "typeof window is object without observable effects throughout initialization",
  ]);
  assert.deepEqual(browserProfileAssumptions(verdict.assumptions), [
    "deferred standard constructors use the page realm's unchanged constructors throughout initialization",
  ]);
  assert.deepEqual(moduleEvaluationOrder(out, entry), [...order, entry]);
  globalThis.window = {};
  try {
    for (const file of [files.sourceFile, path.join(out, entry)]) {
      assert.equal((await import(pathToFileURL(file).href)).result, "page");
    }
  } finally {
    delete globalThis.window;
  }
  assert.deepEqual(observe(files.sourceFile, "result"), { result: "ready" });
  assert.deepEqual(observe(path.join(out, entry), "result"), { error: "Error" });
}

for (const active of [false, true]) {
  const name = `page-url-${active}`;
  if (!includesCase(name)) continue;
  const useURL = {
    type: "NewExpression",
    callee: id("URL"),
    arguments: [literal("https://example.org/")],
  };
  const test = fixture(
    name,
    program([
      variable("const", "make", arrow([id("parse")], conditional(id("parse"), useURL, literal("help")))),
      variable("const", "result", call(id("make"), [literal(active)])),
      exportNamed([
        ["make", "make"],
        ["result", "result"],
      ]),
    ])
  );
  const { status, reason, assumptions } = test.run("--host-contract", profile);
  if (active) {
    assert.equal(status, "rejected");
    assert.match(reason, /ambient constructor URL is reached/);
    assert(!existsSync(test.out));
  } else {
    assert.equal(status, "certified", reason);
    assert.deepEqual(browserObservedAssumptions(assumptions), []);
    assert.deepEqual(browserProfileAssumptions(assumptions), [
      "the browser page exposes the unchanged URL constructor throughout initialization",
    ]);
    for (const file of [test.sourceFile, path.join(test.out, entry)]) {
      const mod = await import(pathToFileURL(file).href);
      assert.equal(mod.result, "help");
      assert.equal(mod.make(true).hostname, "example.org");
    }
  }
}

if (includesCase("profile-premise-sources")) {
  const fixtureWithProfileUse = fixture(
    "profile-premise-sources",
    `if (false) console.log("must not run");
    const result = typeof window;
    export { result };`
  );
  const verdict = split({
    source: fixtureWithProfileUse.sourceFile,
    spec: fixtureWithProfileUse.specFile,
    out: fixtureWithProfileUse.out,
    hostContract: nodeProfile,
  });
  assert.equal(verdict.status, "certified", JSON.stringify(verdict));
  assert.equal(verdict.verdict.hostProfile, "node-recording");

  // These two facts justify profile-directed lowering of the retained .prim log,
  // even though the branch is not taken. The remaining facts come from the reached
  // typeof window observation in the source and candidate executions.
  const loweringFacts = [
    "Node's console.log binding is the unmodified console method throughout initialization; additionally, console.log is the unmodified Node console method and appends formatted output to the recording",
    "the recording harness uses the model's standard primitive handlers for listed calls",
  ];
  const observedFacts = [
    "a global name absent from the ECMAScript and Node layers is undeclared throughout initialization",
    "typeof window is undefined without observable effects throughout initialization",
  ];
  assert.deepEqual([...verdict.verdict.assumptions].sort(), [...loweringFacts, ...observedFacts].sort());

  const deadSymbol = fixture(
    "profile-premise-dead-symbol",
    `if (false) { const key = Symbol.iterator; }
    const result = typeof window;
    export { result };`
  );
  const symbolVerdict = deadSymbol.run("--host-contract", profile);
  assert.equal(symbolVerdict.status, "certified", JSON.stringify(symbolVerdict));
  assert.deepEqual(browserLoweringAssumptions(symbolVerdict.assumptions), [
    "the ambient Symbol binding is the unmodified ECMAScript intrinsic throughout initialization",
    "the intrinsic Symbol.iterator property is the realm's well-known symbol and reading it has no observable effects throughout initialization",
  ]);
  assert.deepEqual(browserProfileAssumptions(symbolVerdict.assumptions), [
    "the intrinsic Symbol operations return fresh symbols and canonical well-known symbols without observable effects throughout initialization",
  ]);
  assert.deepEqual(browserObservedAssumptions(symbolVerdict.assumptions), [
    "window, globalThis, and self return the same page global object throughout initialization",
    "typeof window is object without observable effects throughout initialization",
  ]);
  // `typeof window` alone is the unused-fact control: the profile contains the
  // Symbol layer, but its premises are omitted when no Symbol operation is lowered.
  assert.deepEqual(browserProfileAssumptions(verdict.verdict.assumptions), []);

  const capturedOutput = [];
  const originalLog = console.log;
  console.log = (...args) => capturedOutput.push(args);
  try {
    for (const file of [fixtureWithProfileUse.sourceFile, path.join(fixtureWithProfileUse.out, entry)]) {
      const module = await import(pathToFileURL(file).href);
      assert.equal(module.result, "undefined");
    }
  } finally {
    console.log = originalLog;
  }
  assert.deepEqual(capturedOutput, []);
}
