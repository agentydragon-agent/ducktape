# Scan Prompt Philosophy

## Core Principle

**Manual code reading is the primary method. Automated tools are discovery aids only.**

All scan prompts in this directory follow a common philosophy that prioritizes deep understanding over superficial pattern matching.

## Why Manual Reading First

Determining code quality issues requires:
- **Context understanding** - What's obvious from names and types? What's the domain?
- **Semantic analysis** - Does code add value or just add noise?
- **Intent recognition** - Is this temporary migration code or permanent antipattern?
- **Subjective judgment** - "Useless" or "vague" depends on audience and purpose

**Automated tools cannot make these judgments reliably.**

## The Automation Trap

❌ **Bad Approach**:
```
1. Run grep/AST scanner
2. Auto-fix everything it finds
3. Declare "all clean!"
```

**Problems**:
- High false positive rate (flags good code as bad)
- High false negative rate (misses real issues)
- False confidence (thinks it found everything)
- Context-blind (doesn't understand why code exists)

✅ **Good Approach**:
```
1. Manually read code to understand patterns
2. Use automated tools to discover candidates
3. Manually verify each candidate with full context
4. Fix confirmed issues with understanding of intent
5. Accept that manual reading may find issues tools missed
```

## Automated Tools: Discovery Aids Only

### What Automated Tools ARE Good For

1. **Finding candidates** - "Here are 50 places with `cast()`, go check them"
2. **Pattern discovery** - "These 10 files have similar structure"
3. **Preprocessing for LLM** - Generate skeleton files, extract specific patterns
4. **Consistency checking** - Find all uses of deprecated API
5. **Heuristic filtering** - Narrow down from 1000 files to 20 worth reading

### What Automated Tools CANNOT Do

1. **Determine if something is actually wrong** - Needs context and judgment
2. **Understand intent** - Is this a workaround, migration, or antipattern?
3. **Make subjective calls** - Is documentation "useless"? Is a name "vague"?
4. **Replace reading code** - You still need to read and understand

## Scan Prompt Structure

Every scan prompt should follow this structure:

### 1. Pattern Description
Clear examples of BAD and GOOD code with explanations of why.

### 2. Detection Strategy

**Start with**:
```markdown
## Detection Strategy

**Primary Method**: Manual code reading. Understand the codebase, look for patterns.

**Why automation is insufficient**: [Explain specific limitations]

### Discovery Approach

[Describe how to use tools to help find candidates]
```

**Include**:
- Clear statement that manual reading is primary
- Explanation of why automation isn't enough for this specific pattern
- Discovery tools as aids (grep patterns, AST helpers, LLM preprocessing)
- Explicit warnings about false positives
- Emphasis on manual verification

**Avoid**:
- Full AST implementation code (high-level description is enough)
- Hardcoded lists of specific values to search for
- Implying automated tools can definitively find all issues
- Suggesting automated fixes without manual verification

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

## Prefer High Recall, Accept Manual Work

**Philosophy**: Better to do more work that finds nothing than miss issues through lazy patterns.

### ❌ Lazy Approach
```
Only check files modified in last commit
Only look for exact pattern "cast(dict[str, Any], ...)"
Stop after finding 5 issues
```

**Result**: False confidence, missed issues

### ✅ Thorough Approach
```
Read all Python files in target directory
Look for any use of cast(), then verify each
Continue until entire area is reviewed
Accept that manual reading may reveal issues tools missed
```

**Result**: Actual confidence, comprehensive cleanup

## LLM/Agent Usage

When using LLM agents to apply scan prompts:

### Discovery Phase
1. **Generate candidates**: Use grep/AST to create list of potential issues
2. **Provide context**: Show surrounding code, not just the line with pattern
3. **Request reasoning**: Ask LLM to explain why each candidate might be problematic

### Verification Phase
1. **Manual review**: Human or LLM reads each candidate with full context
2. **Check false positives**: Is this actually bad code or acceptable?
3. **Understand intent**: Why was it written this way? Migration? Workaround?

### Fix Phase
1. **Targeted fixes**: Only fix confirmed issues
2. **Preserve intent**: If code exists for a reason, document instead of delete
3. **Test thoroughly**: Automated fixes still need testing

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

1. **Claim automation is definitive**: "Run this grep to find all issues"
2. **Provide full implementations**: 100+ lines of AST walker code
3. **Hardcode specific values**: List of 50 function names to search for
4. **Skip manual verification**: "Auto-fix all grep results"
5. **Imply completeness**: "If grep finds nothing, you're done"

### ✅ Do This Instead

1. **Emphasize manual work**: "Primary method: read code"
2. **High-level descriptions**: "Build AST tool that finds X pattern"
3. **General strategies**: "Look for functions where name matches return"
4. **Require verification**: "Manually verify each candidate"
5. **Accept incompleteness**: "Manual reading may find issues tools miss"

## Summary

**Core Loop**:
1. Read code manually to understand patterns
2. Use tools to help discover more candidates
3. Manually verify each candidate with context
4. Fix with understanding, not automation
5. Accept that manual reading is necessary

**Philosophy**:
- Prefer doing work over false confidence
- Automated tools amplify human judgment, don't replace it
- General strategies beat specific hardcoded patterns
- High recall with manual filtering beats low recall with auto-fix

**Result**:
- Actually find and fix issues
- Understand the codebase better
- Build intuition for quality
- Create maintainable, intentional code
