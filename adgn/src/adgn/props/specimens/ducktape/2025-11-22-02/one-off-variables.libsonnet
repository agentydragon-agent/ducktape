local I = import '../../lib.libsonnet';

I.issueMulti(
  rationale= |||
    Multiple unnecessary one-off variables should be inlined. Each variable is assigned once and used exactly once in the next line or expression, adding no value:
    - They're not reused elsewhere
    - They don't improve readability
    - They don't capture intermediate computations that are referenced multiple times
    - They add extra names that readers must track unnecessarily

    **Fix:** Inline each expression directly at its single use site.
  |||,
  occurrences=[
    {
      files: {
        'adgn/src/adgn/agent/approvals.py': [
          160,
          169,
          [196, 204],
          [215, 216],
          [227, 228],
          [382, 393],
        ],
      },
      note: 'Line 160: pending_map assigned from self.pending, used once at line 169; Line 169: pending_map.items() should be self.pending.items(); Lines 196-204: approvals_list assigned sorted() result, used once in return; Lines 215-216: decision = ContinueDecision(...); self.resolve(...) should inline; Lines 227-228: decision = DenyContinueDecision(...); self.resolve(...) should inline; Lines 382-393: proposals assigned from persistence.list_policy_proposals, used once in list comprehension',
      expect_caught_from: [['adgn/src/adgn/agent/approvals.py']],
    },
    {
      files: {
        'adgn/scripts/generate_frontend_code.py': [
          [183, 186],
          255,
          [268, 274],
        ],
      },
      note: 'Lines 183-186: get_json_schema helper wraps TypeAdapter().json_schema(), used once at line 250; Line 255: main_schema dict comprehension assigned and immediately used to update all_defs; Lines 268-274: ts_output list created empty then imperatively appended; should use list literal',
      expect_caught_from: [['adgn/scripts/generate_frontend_code.py']],
    },
  ],
)
