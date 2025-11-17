# Scan Prompt Philosophy

## Core Principle

**Goal: Find ALL instances of the issue (100% recall). Use automated tools strategically to gather candidates, then verify with appropriate level of scrutiny.**

All scan prompts in this directory follow a common philosophy: combine automated discovery with intelligent verification to achieve comprehensive cleanup.

## The Real Goal: 100% Recall

When running a scan, the objective is **not missing any real issues**. This means:

- **Automated tools are essential** for discovery - they gather candidates/starting points
- **Some patterns have 100% recall** - "can ONLY happen in places matching this grep/AST check"
- **Tools have different characteristics** - high-recall/low-precision, high-precision/low-recall
- **Agent uses intelligence** to combine tools effectively based on their reliability

## Understanding Tool Characteristics

Different automated tools have different reliability profiles:

### High Recall, High Precision (100%/100%)
**Example**: Finding all `cast()` calls
- Every `cast()` usage matches `grep "cast("` or AST check for Call nodes with func.id == 'cast'
- Very few false positives (only matches actual cast calls)
- **Strategy**: Run tool, verify all candidates

### High Recall, Low Precision (100%/30%)
**Example**: Finding trivial forwarders
- AST can find all single-return functions (100% recall)
- Many are legitimate wrappers (70% false positives)
- **Strategy**: Run tool, manually/LLM filter candidates

### Medium Recall, High Precision (60%/90%)
**Example**: Finding manual dict serialization
- Can search for `dict[str, Any]` + `.items()` patterns
- Misses clever variations but rarely wrong
- **Strategy**: Run tool, light verification, accept some misses

### Low Recall, Manual Required (30%/N/A)
**Example**: Finding "vague" field names
- Automation can flag short names, but misses contextual vagueness
- Human judgment required for what's "vague"
- **Strategy**: Use automation for hints, manual reading required

## The Automation Strategy

✅ **Correct Approach**:
```
1. Understand the issue pattern and its characteristics
2. Run automated scans to gather candidates (grep/AST/ruff/vulture/etc.)
3. Understand recall/precision of each tool for this pattern
4. Verify candidates with appropriate scrutiny:
   - High precision: light verification
   - Low precision: careful manual review or LLM filtering
5. Fix confirmed issues
6. For low-recall patterns: supplement with manual reading
```

❌ **Bad Approach**:
```
1. Run grep/AST scanner
2. Auto-fix everything it finds without verification
3. Declare "all clean!" (false confidence)
```

**Problems with bad approach**:
- Breaks good code (low precision without verification)
- Misses issues (low recall without supplemental reading)
- False confidence (assumes tool found everything)

## Automated Tools: Essential for Discovery

### What Automated Tools ARE Good For

1. **Finding candidates** - "Here are 50 places with `cast()`, go check them" (may be 100% recall!)
2. **Pattern discovery** - "These 10 files have similar structure"
3. **Preprocessing for LLM** - Generate skeleton files, extract specific patterns
4. **Consistency checking** - Find all uses of deprecated API (often 100% recall)
5. **Heuristic filtering** - Narrow down from 1000 files to 20 worth reading

### What Automated Tools NEED Help With

1. **Verification** - Determining if candidate is actually wrong (context and judgment required)
2. **Understanding intent** - Is this a workaround, migration, or antipattern?
3. **Subjective judgment** - Is documentation "useless"? Is a name "vague"? (human/LLM verification needed)
4. **Low-recall patterns** - May need supplemental manual reading to find all issues

## Scan Prompt Structure

Every scan prompt should follow this structure:

### 1. Pattern Description
Clear examples of BAD and GOOD code with explanations of why.

### 2. Detection Strategy

**Template**:
```markdown
## Detection Strategy

**Goal**: Find ALL instances (100% recall).

**Recall/Precision**: [Characterize the automated tools]
- Tool X has ~100% recall, ~Y% precision
- Tool Z has ~A% recall, ~B% precision

**Recommended approach**:
1. Run [specific tools: grep/AST/ruff/vulture/etc.] to gather candidates
2. [Verification strategy based on precision]:
   - High precision: Light verification
   - Low precision: Manual review or LLM filtering
3. Fix confirmed issues
4. [If low recall]: Supplement with manual reading of [specific areas]
```

**Include**:
- Specific useful tools (grep patterns, AST checks, linters, analyzers)
- Characterization of each tool's recall/precision for this pattern
- Clear verification strategy based on precision
- Acknowledgment if pattern requires manual reading (low recall)

**Avoid**:
- Full AST implementation code (high-level description is enough)
- Hardcoded lists of specific values to search for
- Claiming automation is sufficient without verification
- Suggesting automated fixes for low-precision patterns without review

### 3. Examples with Context

Show real examples with enough context to understand the fix.

## General vs. Specific

### ❌ BAD: Hardcoded Specific Cases
```bash
# Find these exact 47 function names that might be useless
rg "get_user_id|fetch_data|load_config|..."
```

**Problem**: Won't generalize to new code, misses different patterns

### ✅ GOOD: General Strategy
```markdown
Find functions where:
- Name is nearly identical to what it returns
- Single statement that just calls another function
- No validation, transformation, or error handling

Use grep to find single-statement functions as candidates, then manually review each.
```

**Benefit**: Agent/LLM can apply this strategy to any codebase

## Prioritize Recall: Don't Miss Issues

**Philosophy**: The goal is 100% recall. Use tools strategically to achieve it.

### ❌ Low Recall Approach (Misses Issues)
```
Only check files modified in last commit
Only look for exact pattern "cast(dict[str, Any], ...)"
Stop after finding 5 issues
```

**Result**: False confidence, missed issues

### ✅ High Recall Approach (Finds Everything)
```
Use grep/AST to find ALL cast() calls (100% recall for this pattern)
Verify each candidate (handle precision issue)
For low-recall patterns: supplement with manual reading
Continue until confident you've found everything
```

**Result**: Comprehensive cleanup, no missed issues

## LLM/Agent Usage

When using LLM agents to apply scan prompts:

### 1. Tool Selection Phase
1. **Understand pattern characteristics**: Does this pattern have high/low recall? High/low precision?
2. **Choose appropriate tools**: grep/AST/ruff/vulture/etc. based on pattern
3. **Set expectations**: Know what each tool will find/miss

### 2. Discovery Phase
1. **Run automated scans**: Use grep/AST/linters to gather ALL candidates (aim for 100% recall where possible)
2. **Understand tool output**: Did tool likely find everything? Or just hints?
3. **Provide context**: Fetch surrounding code for each candidate

### 3. Verification Phase
1. **Match verification to precision**:
   - High precision tool: Light verification ("does this actually match pattern?")
   - Low precision tool: Deep verification ("is this actually problematic?")
2. **Check false positives**: Is this actually bad code or acceptable?
3. **Understand intent**: Why was it written this way? Migration? Workaround?

### 4. Fix Phase
1. **Fix confirmed issues**: Only fix what verification confirmed
2. **Preserve intent**: If code exists for a reason, document instead of delete
3. **Consider supplemental reading**: For low-recall patterns, manually check areas tools might miss

## Helper Scripts: High-Level Descriptions

Instead of providing full implementations, give high-level descriptions:

```markdown
**AST-Based Discovery** (optional):

Build a tool that:
- Walks FunctionDef nodes
- Extracts signatures, types, docstrings
- Flags where docstring just repeats parameter names
- Reports candidates for manual review

Strong coding LLM can reconstruct from this description.
```

**Benefits**:
- Prompts stay concise
- Agents can implement in whatever language/tool makes sense
- Avoids maintenance of sample code
- Emphasizes that implementation is a means, not the goal

## Example: Code Skeleton Generation

**Instead of**: Full working script to strip function bodies

**Provide**: High-level description of what to build:
```markdown
Create helper that strips function bodies, preserving signatures and docs:
1. Parse file with AST
2. For each function, extract signature + docstring
3. Output minimal skeleton (sig + docstring + ...)
4. Feed skeleton to LLM for review

LLM sees context without implementation noise.
```

## Anti-Patterns in Scan Prompts

### ❌ Don't Do This

1. **Ignore tool characteristics**: "Just run this tool" (without explaining recall/precision)
2. **Provide full implementations**: 100+ lines of AST walker code in the prompt
3. **Hardcode specific values**: List of 50 function names to search for
4. **Skip verification for low-precision tools**: "Auto-fix all grep results"
5. **Claim completeness without justification**: "If grep finds nothing, you're done" (when grep has low recall)

### ✅ Do This Instead

1. **Characterize tool reliability**: "grep for cast() has ~100% recall, ~95% precision"
2. **High-level descriptions**: "Build AST tool that finds X pattern"
3. **General strategies**: "Look for functions where name matches return"
4. **Match verification to precision**: "High precision: light verification. Low precision: deep review"
5. **Acknowledge recall limitations**: "This pattern has ~60% recall; supplement with manual reading of [areas]"

## Summary

**Core Loop**:
1. Understand pattern characteristics (recall/precision of available tools)
2. Run automated scans to gather candidates (aim for 100% recall)
3. Verify candidates with appropriate scrutiny (based on precision)
4. Fix confirmed issues
5. For low-recall patterns: supplement with manual reading

**Philosophy**:
- **Goal is 100% recall** - don't miss any real issues
- **Automated tools are essential** - use them strategically based on their characteristics
- **Some patterns have 100% recall** - grep/AST can find all instances
- **Agent uses intelligence** - combines tools, understands their limitations, verifies appropriately
- **Verification matches precision** - high precision = light verification, low precision = deep review

**Tool Characteristics Matter**:
- High recall, high precision: Run tool, verify all → Done
- High recall, low precision: Run tool, filter false positives → Done
- Low recall: Run tool, verify candidates → Supplement with manual reading
- Manual only: Use automation for hints, but expect to find issues by reading

**Result**:
- Comprehensive cleanup (100% recall goal)
- No missed issues (proper tool selection)
- No broken code (appropriate verification)
- Understanding of codebase (verification requires context)
