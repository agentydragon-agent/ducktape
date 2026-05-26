//! Static purity-whitelist tables for the expression classifier.
//!
//! Each constant is a `&[...]` of known-pure operations keyed by
//! (receiver, property) or bare name. New entries land only with a spec
//! citation showing no user-callback path; "common in practice" is not
//! sufficient.

/// Builtins that can install an accessor or rewire the prototype chain
/// of their first argument. Any candidate appearing as the first
/// positional arg of one of these calls is disqualified from
/// PlainData status. `Object.assign(X, ...)` writes data properties
/// to X but doesn't install accessors; conservatively included so the
/// rule is "X must not be written through, period" without per-builtin
/// reasoning about which kinds of properties end up on X.
pub(super) const PLAIN_DATA_HOSTILE_BUILTINS: &[(&str, &str)] = &[
    ("Object", "defineProperty"),
    ("Object", "defineProperties"),
    ("Object", "setPrototypeOf"),
    ("Object", "assign"),
    ("Reflect", "defineProperty"),
    ("Reflect", "set"),
    ("Reflect", "setPrototypeOf"),
    ("Reflect", "deleteProperty"),
];

/// Static-property reads on these globals are Pure (no
/// observable side effect, no getter to fire). Indexed as
/// `(receiver_ident, property_name)`.
pub(super) const PURE_STATIC_PROPS: &[(&str, &str)] = &[
    ("Math", "PI"),
    ("Math", "E"),
    ("Math", "LN2"),
    ("Math", "LN10"),
    ("Math", "LOG2E"),
    ("Math", "LOG10E"),
    ("Math", "SQRT2"),
    ("Math", "SQRT1_2"),
    ("Number", "EPSILON"),
    ("Number", "MAX_SAFE_INTEGER"),
    ("Number", "MIN_SAFE_INTEGER"),
    ("Number", "MAX_VALUE"),
    ("Number", "MIN_VALUE"),
    ("Number", "POSITIVE_INFINITY"),
    ("Number", "NEGATIVE_INFINITY"),
    ("Number", "NaN"),
    ("Symbol", "iterator"),
    ("Symbol", "asyncIterator"),
    ("Symbol", "toStringTag"),
    ("Symbol", "toPrimitive"),
    ("Symbol", "hasInstance"),
    ("Symbol", "species"),
    ("Symbol", "isConcatSpreadable"),
    ("Symbol", "match"),
    ("Symbol", "replace"),
    ("Symbol", "search"),
    ("Symbol", "split"),
];

/// Static methods that are Pure regardless of argument values.
/// Everything in this table must satisfy: per ECMA-262, the call
/// fires no user-defined code on any argument type — no `ToNumber`
/// / `ToString` / `ToPrimitive` / `ToPropertyKey` coercion, no
/// iterator protocol, no proxy trap, no own-property `[[Get]]`,
/// no mutation of any reachable object. See docs/design.md A8 for the
/// admission contract; AGENTS.md "Pure-call whitelist soundness"
/// for the agent-facing rule. New entries land only with a spec
/// citation showing no user-callback path; "common in practice"
/// is not sufficient.
pub(super) const PURE_STATIC_CALLS: &[(&str, &str)] = &[
    // Type predicate — checks the IsArray internal slot. Spec
    // explicitly says: "does not perform a call to ToObject on its
    // argument".
    ("Array", "isArray"),
    // Number predicates — `Type(arg) is not Number ⇒ false`,
    // otherwise inspect the value. No coercion path.
    ("Number", "isFinite"),
    ("Number", "isInteger"),
    ("Number", "isNaN"),
    ("Number", "isSafeInteger"),
];

/// Pure global callables (no receiver). Same admission contract as
/// `PURE_STATIC_CALLS`: the call must fire no user code on any
/// argument value.
pub(super) const PURE_GLOBAL_CALLS: &[&str] = &[
    // ToBoolean is type-cased and fires no callbacks (objects are
    // unconditionally `true`; primitives are checked structurally).
    "Boolean",
];

/// Pure global callables when every argument is a primitive
/// literal (`Lit::Str` / `Lit::Num` / `Lit::Bool` / `Lit::Null` /
/// `Lit::BigInt`). The non-literal-arg form falls through to
/// `Unknown` because the spec-defined coercion path (`ToString`,
/// `ToNumber`, …) on a non-primitive value can fire user-defined
/// `[Symbol.toPrimitive]` / `valueOf` / `toString` and
/// observably modify state.
///
/// Soundness contract per entry:
/// * `Symbol`: ECMA-262 §20.4.1.1 — `Symbol(description)` does
///   `ToString(description)` (or skips it if description is undefined)
///   and returns a fresh symbol. `ToString` on a primitive literal
///   runs no user code, so the call has no observable side effect
///   beyond the fresh symbol. `Symbol` without `new`; `new Symbol(...)`
///   throws TypeError, but `new`-call form is `Expr::New` not
///   `Expr::Call`, so this rule never fires for it.
pub(super) const PURE_GLOBAL_CALLS_WITH_PRIMITIVE_ARGS: &[&str] = &["Symbol"];

/// Built-in container constructors whose `new X()` (no args)
/// form is pure. ECMA-262 spec for each construct algorithm:
/// step 1 short-circuits when iterable/length is undefined,
/// returning a fresh empty container without invoking any user
/// code (no iterator protocol, no getters fired). Same admission
/// contract as `PURE_GLOBAL_CALLS`. `Set` / `Map` also accept
/// an Array-literal iterable; see `PURE_BUILTIN_NEW_ARRAY_ITERABLE`.
pub(super) const PURE_BUILTIN_NEW_NO_ARGS: &[&str] = &["Map", "Set", "WeakMap", "WeakSet", "Array"];

/// Built-in container constructors whose 1-arg form is pure when
/// the argument is an Array literal with all-Pure elements (no holes;
/// spreads only when the source is itself a fresh Array literal or a
/// pure conditional between fresh Array literals):
///
/// * `Set`: `new Set([elt, ...])` — ECMA-262 §24.2.1.1 iterates
///   the iterable via the built-in Array iterator (no user code
///   on a fresh array literal) and calls `Set.prototype.add` per
///   element. SameValueZero on primitive keys fires no user
///   code; on object keys it's reference equality. Fresh array
///   of Pure elements ⇒ pure.
/// * `Map`: `new Map([[k, v], ...])` — ECMA-262 §24.1.1.1 same
///   iterator path on the outer Array, then `Get(entry, "0")` /
///   `Get(entry, "1")` (own data properties on a fresh entry
///   array, no getter), then `Map.prototype.set`. Pure when
///   every entry is itself a 2-element Array literal with Pure
///   key + value. Fresh-array spreads are flattened under the same
///   entry rule.
/// * `WeakSet` / `WeakMap`: NOT covered — they additionally
///   require object keys; primitives throw. Allowing them would
///   require verifying every element/key has object value class,
///   which the classifier doesn't track.
///
/// Stricter than just "Pure arg" because:
///   - `new Set(somePureFn())` could produce a non-iterable at
///     runtime (TypeError at `[Symbol.iterator]()`), which is
///     observable from the caller's standpoint.
///   - `new Set(spreadable)` invokes the iterable's
///     `[Symbol.iterator]()`, which can fire user code on
///     anything other than a literal array.
pub(super) const PURE_BUILTIN_NEW_ARRAY_ITERABLE: &[&str] = &["Map", "Set"];

/// Static-property READS on these globals are Pure: the property
/// is an own data property of the receiver per ECMA-262 (no getter
/// fires) and accessing it has no observable side effect.
///
/// **Function-valued.** The resolved value is a callable. CALLING
/// it is NOT pure unless the same `(receiver, name)` pair also
/// appears in `PURE_STATIC_CALLS`. Every entry here MUST have both
/// a positive `static_function_ref_*_alias_is_pure` test AND a
/// negative `static_function_ref_*_call_remains_unknown` test
/// pinning that distinction. See AGENTS.md "Pure-call whitelist
/// soundness".
pub(super) const PURE_STATIC_FUNCTION_REFS: &[(&str, &str)] = &[
    // All entries below are own data properties of the `Object`
    // built-in per ECMA-262 §20.1.2 — reads fire no getter. The
    // CALL of each is unsafe in distinct ways and intentionally
    // NOT in `PURE_STATIC_CALLS`:
    //   - `Object.defineProperty(t, k, d)` mutates `t`.
    //   - `Object.freeze(o)` mutates `o`'s descriptor table.
    //   - `Object.values(o)` / `Object.keys(o)` invoke
    //     `[[OwnPropertyKeys]]` and (for values) `[[Get]]` per
    //     key — fires user getters and Proxy traps.
    // The bare alias form `const define = Object.defineProperty;`
    // appears in real specs as a renamed shortcut.
    ("Object", "defineProperty"),
    ("Object", "defineProperties"),
    ("Object", "freeze"),
    ("Object", "values"),
    ("Object", "keys"),
    ("Object", "entries"),
    ("Object", "fromEntries"),
    ("Object", "getOwnPropertyDescriptor"),
    ("Object", "getOwnPropertyDescriptors"),
    ("Object", "getOwnPropertyNames"),
    ("Object", "getOwnPropertySymbols"),
    ("Object", "getPrototypeOf"),
    ("Object", "setPrototypeOf"),
    ("Object", "create"),
    ("Object", "assign"),
    ("Object", "is"),
    ("Object", "isFrozen"),
    ("Object", "isSealed"),
    ("Object", "isExtensible"),
    ("Object", "preventExtensions"),
    ("Object", "seal"),
    ("Object", "hasOwn"),
];

/// Static `Object` methods that are Pure when called with a single
/// argument that is structurally a fresh plain-data object/array
/// literal (no accessors / methods / `__proto__` / computed keys /
/// spread of non-plain-data sources) OR a chunk-top binding that has
/// admitted as `ChunkBinding::PlainData` (whose plain-data shape is
/// enforced syntactically by `collect_plain_data_bindings` and whose
/// post-init accessor-installation is rejected by
/// `PlainDataWriteScanner`).
///
/// The contract is stricter than `PURE_STATIC_CALLS` because every
/// member here either invokes `[[Get]]` on own keys (which fires user
/// getters / Proxy traps on a general argument) or mutates descriptor
/// state (`freeze`). Restricting the argument shape to a fresh plain-
/// data receiver — verified syntactically at the call site — closes
/// both holes: no own-key access can fire a user accessor (none
/// exist), and the mutation in `freeze`'s case targets a value that
/// is not aliased through any user-observable channel before the
/// call.
///
/// Soundness contract per entry:
///
/// * `Object.keys(O)` — ECMA-262 §20.1.2.17 calls `ToObject(O)`
///   (no coercion on an object), then `EnumerableOwnPropertyNames(O,
///   "key")`. The latter calls `[[OwnPropertyKeys]]` (for an
///   ordinary plain object: returns the integer-index keys then
///   string keys in insertion order, no user code) and per-key
///   `[[GetOwnProperty]]` to check `[[Enumerable]]` — also a
///   structural read with no user code on a fresh plain literal /
///   PlainData binding.
/// * `Object.values(O)` / `Object.entries(O)` — same as `keys` but
///   additionally call `[[Get]]` on each own key. For an ordinary
///   plain-data receiver every own key resolves to a data property
///   ($\Rightarrow$ no accessor fires). PlainData receivers carry
///   the same guarantee by the chunk-wide write scan
///   (`PlainDataWriteScanner` rejects any
///   `Object.defineProperty(X, …)` /
///   `Object.setPrototypeOf(X, …)` that could install an accessor
///   post-init).
/// * `Object.freeze(O)` — ECMA-262 §20.1.2.6 calls
///   `SetIntegrityLevel(O, "frozen")` which sets `[[Extensible]]`
///   to false and rewrites each own property descriptor to non-
///   configurable (and non-writable for data properties). No
///   `[[Get]]` is performed, no user code fires. The mutation is
///   on the just-allocated literal (for the literal form) or on a
///   binding whose only producer/consumer is the chunk being
///   debundled (for the PlainData form), so it cannot perturb
///   user-observable state outside the call.
/// * `Object.fromEntries(I)` — ECMA-262 §20.1.2.7 invokes
///   `I[@@iterator]()`. For a fresh `Array` literal with no spread,
///   that resolves to the built-in Array iterator, which `[[Get]]`s
///   indices `0..length` (own data properties on a fresh array,
///   no user code) and stops. Each yielded entry must itself be a
///   2-element Array literal whose [0]/[1] reads are own data
///   properties (gated by `is_fresh_entry_array_for_from_entries`).
///   Both gates together rule out the
///   "non-iterable argument throws TypeError" path that breaks
///   purity for arbitrary arg shapes (the throw is observable). For
///   a PlainData Object binding the call would throw, so PlainData
///   shapes are admitted only for the non-fromEntries methods.
///
/// Out of scope (not admitted here; flagged for follow-up review):
///
/// * `Object.assign(target, src)` — mutates `target` AND calls
///   `[[OwnPropertyKeys]]`/`[[Get]]` on `src`. The target-mutation
///   half rules out the literal-arg shortcut: even with two literal
///   args, `Object.assign({}, …)` returns the first arg mutated,
///   which is observable only if the result is captured — but the
///   mutation itself is invisible without the capture, so this is
///   safely pure-of-result. Skipped here to keep the rule tight;
///   the `assign` path needs its own argument-count + result-shape
///   analysis.
/// * `Object.getOwnPropertyNames(O)` / `getPrototypeOf(O)` /
///   `getOwnPropertyDescriptor(O, k)` — same shape as `keys` but
///   produces a richer return value. Could ride on the same gate
///   in a follow-up; out for v1 to minimize the audit surface.
/// * `Array.from(I[, mapFn])` — sound only when `mapFn` is absent
///   (a `mapFn` invokes user code per element). Skipped here to
///   avoid the per-call argument-count gate.
pub(super) const PURE_OBJECT_CALLS_ON_PLAIN_DATA: &[(&str, &str)] = &[
    ("Object", "keys"),
    ("Object", "values"),
    ("Object", "entries"),
    ("Object", "freeze"),
    ("Object", "fromEntries"),
];

/// Receiver / global-callable names whose whitelist firing depends
/// on the chunk not having shadowed them at top level.
/// `analyze_chunk` populates the shadowed-globals set, and
/// the classifier suppresses whitelist hits for any name in it —
/// e.g. `const Math = …` makes `Math.PI` fall back to `Unknown`.
pub(crate) const WHITELIST_RECEIVERS: &[&str] =
    &["Math", "Array", "Symbol", "Number", "Boolean", "Object"];
