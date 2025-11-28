# Grader Improvements: Docker Access + Justification Requirements

## Implementation Status: ✅ COMPLETE

**What was implemented**:
1. ✅ Docker runtime server mounted (`agent_runners.py:282` - `await wiring.attach(comp)`)
2. ✅ Prompt updated with "READ THE CODE FIRST" directive and proactive inspection workflow
3. ✅ Required justifications added (unknown issues, partial coverage, line range discrepancies)
4. ✅ Line range flexibility (±3 lines tolerance) documented in matching guidance

**Key change**: Grader now has `runtime/exec` tools (`cat`, `sed -n`, `head`, `tail`) to inspect actual code and make evidence-based matching decisions instead of text-similarity guessing.

## Expected Impact

### For the Cheat Critique Test

Previously: **0.45 recall** (8/17 matched)
- 7 issues marked "unknown" with only the comment: "no canonical overlap by file/lines"
- No justification for why line ranges that were only 1-3 lines different were rejected

Expected after changes: **0.80-0.95 recall**
- The grader can now inspect code at adjusted line ranges
- ±3 line tolerance should catch most of the "expanded for context" adjustments
- Detailed justifications will reveal remaining issues

### Specific Cases Expected to Improve

Previously marked "unknown" with only "no canonical overlap by file/lines":
- cheat-005, -006, -007, -008, -012: ±3 tolerance + code inspection should reveal semantic matches
- cheat-009, -011: True unknowns (different files or genuinely novel issues)

## Testing

Verify improvements on cheat critique test:
```bash
cd adgn
direnv exec . adgn-properties2 specimen-grade ducktape/2025-11-22-01 \
  --critique src/adgn/props/specimens/ducktape/2025-11-22-01/cheat_critique.jsonnet

# Check for Docker exec tool calls in transcript
jq 'select(.name | startswith("runtime_exec"))' \
  src/adgn/props/specimens/ducktape/2025-11-22-01/grader_*/grader/events.jsonl
```

Expected: recall improves from 0.45 to 0.80-0.95, with evidence-based justifications for unknowns/partial coverage.

## Future Improvements (if recall still <0.90)

- Path normalization (`adgn/tests/...` vs `tests/...` equivalence)
- Fuzzy file matching patterns
- Explicit embedding similarity thresholds (>0.8) to override line mismatches
