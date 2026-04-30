import { c as e } from "./SharedFormat.js";

const o = (t) => {
  const o2 = { text: e(t) };
  globalThis.__mockBundleState.chip = o2;
  document.querySelector("#chip").textContent = o2.text;
  return o2;
};

export { o as s };
