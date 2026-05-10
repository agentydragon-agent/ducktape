//! Pin matching of multi-line IIFE anonymous statements.
//!
//! Tana's actual companions are not single-line `console.log`
//! calls; they include multi-line IIFE preludes like the Sentry
//! debug-id wrapper:
//!
//! ```js
//! !(function () {
//!   try {
//!     var e = "undefined" != typeof window ? window : globalThis,
//!       n = new e.Error().stack;
//!     n && (e._sentryDebugIds = e._sentryDebugIds || {},
//!           e._sentryDebugIds[n] = "...");
//!   } catch (e) {}
//! })();
//! ```
//!
//! This test pins:
//!   * the `match` source can be a multi-line block scalar
//!   * the parser accepts the wrapped IIFE as a single
//!     ExpressionStatement
//!   * `EqIgnoreSpan` ignores whitespace differences (the YAML
//!     block scalar's indentation is stripped, the chunk's
//!     formatting is whatever the prettifier produced) and
//!     compares structurally
//!   * the resolver finds exactly one match
//!
//! Without this guard, an upstream re-prettify that touched the
//! IIFE's indentation would silently desynchronize selectors
//! from chunk source.

use debundle_e2e_support::*;

#[test]
fn multi_line_iife_anon_statement_matches_modulo_whitespace() {
    let fixture = run_fixture(FixtureOpts::new(
        // Source mirrors the Tana Sentry-prelude shape (lines
        // 1-17 in `static/index-DI2GynTv.js`): a `!`-prefixed
        // IIFE expression statement that walks `globalThis` to
        // attach a debug id.
        r#"!(function () {
  try {
    var e =
        "undefined" != typeof window
          ? window
          : "undefined" != typeof globalThis
            ? globalThis
            : {},
      n = new e.Error().stack;
    n && ((e._sentryDebugIds = e._sentryDebugIds || {}), (e._sentryDebugIds[n] = "test-debug-id"));
  } catch (e) {}
})();
var X = (() => "x")();
const Existing = "existing";
console.log(Existing);
export { X, Existing };
"#,
        vec![logical_module_with_anon(
            "x_module",
            &[Member::new("X")],
            // Selector source mirrors the IIFE shape but with
            // different indentation than the chunk source — the
            // resolver's `EqIgnoreSpan` comparison must look
            // through that.
            &[r#"!(function () {
    try {
        var e =
                "undefined" != typeof window
                    ? window
                    : "undefined" != typeof globalThis
                        ? globalThis
                        : {},
            n = new e.Error().stack;
        n && ((e._sentryDebugIds = e._sentryDebugIds || {}), (e._sentryDebugIds[n] = "test-debug-id"));
    } catch (e) {}
})();"#],
        )],
    ));

    // The peeled module carries the IIFE alongside the var X
    // declaration.
    assert_module_source(
        &fixture.out_root,
        "static/app/modules/x_module.js",
        &["_sentryDebugIds", "var X"],
        &[],
    );

    // Residual no longer carries the IIFE.
    assert_module_source(
        &fixture.out_root,
        "static/app/modules/residual/unhandled.js",
        &[],
        &["_sentryDebugIds", "var X"],
    );

    // End-to-end: the IIFE's try/catch swallows any error from
    // touching `globalThis`, so the module loads cleanly. Then
    // `console.log(Existing)` runs from residual.
    assert_entry_output(&fixture, "existing\n");
}
