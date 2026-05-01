const runtimeRoot = "undefined" != typeof global ? global : globalThis;
const optionalDebugFlag = typeof __DUCKTAPE_OPTIONAL_GLOBAL__ > "u" || __DUCKTAPE_OPTIONAL_GLOBAL__;

const e = {
  stamp: "mock-dashboard@7",
  hasNodeGlobal: typeof global !== "undefined",
  rootKind: runtimeRoot === globalThis ? "globalThis" : "global",
  optionalDebugFlag,
};

export { e as i };
