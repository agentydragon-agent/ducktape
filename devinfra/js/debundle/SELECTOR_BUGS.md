# Selector Bugs And Gaps

Selector issues found while porting a downstream debundle spec, or reported by
code review. Examples are intentionally generic and anonymized. Every entry
carries a **Status** distinguishing runtime reproduction, source-confirmed
omissions, and unverified reports. An entry is deleted when its fix lands with a test, or when it is
disproved.

## Unknown Hole Keywords Match As Identifiers

Status: open (reproduced 2026-09-24). Nothing checks for unknown hole
keywords, so a hole keyword the binary does not know is a plain free identifier
on every path, including `match-selector`. A selector written for a newer hole vocabulary and run by an
older pinned debundler reports `no_match` or `ambiguous` instead of `invalid`.

The fix is a design decision first: an old binary cannot recognise a keyword it
has never seen, only a name of a reserved shape. <SPEC.md> § Matching rule 1
needs a reservation rule for hole-shaped names that every future hole keyword
falls inside and that real chunk identifiers do not (an all-caps rule would
catch globals such as `JSON` and `URL`). A reserved name the binary does not
implement is then `invalid` with "unsupported selector hole", on every command.

## Invalid Regex Predicate Matches Nothing

Status: source-confirmed silent compile failure; CLI reproduction still needed.
`selectors/matching/selector_match.rs` builds regex predicates with
`if let Ok(compiled) = Regex::new(pattern)`, silently omitting invalid patterns.
`source_match/parse_validate.rs::parse_selector_module` parses JavaScript and
validates `ANYTHING` positions, not regex syntax; `unsupported_needle_construct`
checks predicate shape/position, not the pattern's validity. Add a CLI fixture
with `STR_LITERAL_MATCHING_RE("[")` and require `invalid`, not `no_match`, before
choosing the shared validation boundary.

## Solver Domain Encoding Ignores Id Gaps

Status: unreproduced (code review 2026-09-30, not verified).
`selectors/resolution/selector_constraint_backend.rs` `ensure_full_domain_contains` returns silently
when `usize::try_from` fails or when `index > values.len()`, and appends only when
`index == values.len()`. A gap in encoded ids drops the value from the full
domain instead of raising. Reachability is unverified: first trace
`DomainValueDictionary` interning and callers `add_allowed_tuples` /
`intern_encoded_allowed_binary_row_set`. If contiguous allocation is an invariant,
assert it; do not report a reachable dropped-candidate bug without that evidence.

## Too-Broad Count Can Overstate Places

Status: unreproduced (code review 2026-09-30, not verified). `Rejection::check_count`
in `selectors/resolution/selector_resolve.rs` caps and reports `rows.len()`, but `narrow_by_references`
calls it on collected rows that `project_collected` dedupes only later (`distinct`),
and rows can repeat one place with different `free_bindings`. The `too_broad`
message "matches N places" can overcount. Fix: count distinct places.
