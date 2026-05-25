//! Regression test for the namespace-aggregator TDZ hole.
//!
//! ## Shape
//!
//! A "namespace aggregator" is a module-top object built from
//! object-spread of submodule namespace objects:
//!
//! ```js
//! export const ids = { ...sub1, ...sub2 };
//! ```
//!
//! When the spec splits this into three modules (one for the
//! aggregator and one each per sub), the aggregator's body issues an
//! at-init read of `sub1` and `sub2`. ESM Phase-2 evaluates `sub1`
//! and `sub2` before `aggregator` because they are imports.
//!
//! The bug: when a sub-module ALSO reads a binding from the residual
//! at-init, and the residual reads the aggregator's `ids` at-init,
//! the resulting cycle is:
//!
//! ```text
//! residual --EagerUse--> aggregator (ids)
//! aggregator --EagerUse--> sub1     (...sub1)
//! sub1 --EagerUse--> residual       (helperFromResidual)
//! ```
//!
//! ESM DFS from residual:
//!
//! 1. residual on stack, recurse into aggregator.
//! 2. aggregator on stack, recurse into sub1.
//! 3. sub1 on stack, recurse into residual — already on stack;
//!    don't recurse.
//! 4. Done with sub1 deps → evaluate sub1 body. Sub1 reads
//!    `helperFromResidual` — residual has NOT yet run its
//!    `const helperFromResidual = ...` line. TDZ on the residual
//!    binding.
//!
//! For the aggregator-specific shape (this test), the same fix
//! family catches a closely related TDZ: a back-edge from a sub to
//! the aggregator's destination module. The cycle the gate must see:
//!
//! ```text
//! aggregator-module --EagerUse--> sub1-module
//! sub1-module --EagerUse--> aggregator-module (via residual)
//! ```
//!
//! ## Expected outcomes
//!
//! - **Before the fix**: pipeline accepts the spec; Node throws
//!   `ReferenceError: Cannot access 'ids' before initialization`
//!   (or analogous) when running the emitted entry.
//! - **After the fix**: the realizability gate sees the aggregator's
//!   eager read of the sub-modules as a constraining edge that
//!   participates in the cycle, and rejects the spec.

use debundle_e2e_support::*;

// `helperFromResidual` lives in the residual chunk (entry) and is
// read at-init by both `sub1`'s and `sub2`'s initializers. The
// aggregator `ids` is read at-init from the residual's
// `const consumed = ids.foo;` line. The fixture below produces the
// cycle: residual ↔ aggregator (via sub1 → helperFromResidual).
const NAMESPACE_AGGREGATOR_SOURCE: &str = r#"const helperFromResidual = "H";
const sub1 = { foo: helperFromResidual + "1" };
const sub2 = { bar: helperFromResidual + "2" };
const ids = { ...sub1, ...sub2 };
const consumed = ids.foo + "|" + ids.bar;
console.log(consumed);
export { ids, sub1, sub2, helperFromResidual };
"#;

fn opts_for_fixture() -> FixtureOpts<'static> {
    let mut opts = FixtureOpts::new(
        NAMESPACE_AGGREGATOR_SOURCE,
        vec![
            logical_module("ids/index", &[Member::new("ids")]),
            logical_module("ids/sub1", &[Member::new("sub1")]),
            logical_module("ids/sub2", &[Member::new("sub2")]),
        ],
    );
    opts.unassigned_mode = unassigned_mode_inline();
    opts
}

#[test]
fn namespace_aggregator_split_rejects_tdz_cycle() {
    // Cycle:
    //   residual → ids/index   (eager: `ids.foo`)
    //   ids/index → ids/sub1   (eager: `...sub1`)
    //   ids/sub1 → residual    (eager: `helperFromResidual`)
    //
    // The gate must see every leg as constraining. If the aggregator
    // leg is dropped (TDZ hole), the gate green-lights a spec whose
    // emitted JS throws under Node.
    expect_rejection(
        opts_for_fixture(),
        &["unrealizable", "cycle", "tdz", "cannot access"],
    );
}
