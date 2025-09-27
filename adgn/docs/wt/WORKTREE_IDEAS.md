# WT Ideas and Notes

## The Beautiful Over-Engineering Temptation
```bash
# Define reusable command templates
wt template diff-configs "diff {a}/config.yaml {b}/config.yaml"
wt template copy-experiments "cp -r {a}/experiments/ {b}/"
wt template run-in "cd {a} && {cmd}"

# Use templates with worktree substitution
wt diff-configs main feature
wt copy-experiments old-experiment new-experiment  
wt run-in feature "python test.py"

# Multi-worktree operations
wt template multi-diff "diff {a}/foo {b}/foo {c}/foo"
wt multi-diff main feature-1 feature-2
```

### Why This Is Sexy But Dangerous
- Reminds me of 4 different esoteric programming languages
- Definitely somewhere nontrivial on the language complexity scale
- Would be absolutely ridiculous rabbit hole for a productivity tool
- But SO beautiful and tempting for an ADHD brain
- High reward episode for LLM collaboration 

### Practical Multi-Worktree Operations (Maybe Later)
```bash
# Multi-path operations
wt path main feature /config.yaml  # Returns both paths for diff
diff $(wt path main feature /config.yaml)

# Bulk operations
wt foreach "git status"  # Run command in all worktrees
wt map feature-* "python test.py"  # Run in matching worktrees
```

## Advanced Path Operations

### Path Resolution Ideas
```bash
# Current design we're implementing
wt path <x> /foo/bar          # <x root>/foo/bar
wt path <x> /foo/bar --relative  # Relative to pwd

# Future extensions
wt path --common main feature    # Common ancestor path
wt path --diff main feature     # Paths that differ between worktrees
wt glob feature-* /src/*.py     # Glob across multiple worktrees
```

## Workflow Shortcuts

### Copy and Branch Patterns
```bash
# What we're implementing
wt cp <x> <y>                   # Copy worktree x to new worktree y

# Future extensions  
wt cp <x> <y> --clean           # Copy structure but clean git state
wt cp <x> <y> --link            # Hard link shared files
wt merge-back <x>               # Merge worktree back to master and cleanup
```

## Note to Future Self
Remember: The goal is building a productivity tool for ML research, not a programming language. Ship the practical version first, then maybe explore the beautiful abstractions when they solve real problems we actually encounter.

