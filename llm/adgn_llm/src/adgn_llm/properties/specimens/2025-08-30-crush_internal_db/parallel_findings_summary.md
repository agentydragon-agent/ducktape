# Parallel critics findings summary

This summarizes final-only outputs from parallel Codex critic runs under:
- /Users/mpokorny/code/ducktape/llm/adgn_llm/specimens/2025-08-30-crush_internal_db/parallel_all

Each section lists only reported findings for that chunk; files/subdirs with no issues are grouped at the end.

## internal/llm (Markdown prompt formatting issues)
- internal/llm/prompt/anthropic.md
  - CRUSH.md should be inline code. Lines: 7, 13, 96
  - Commands should be inline code (e.g., npm run lint, npm run typecheck, ruff). Line: 96
  - Paths should be inline code (package.json, cargo.toml). Line: 80
- internal/llm/prompt/gemini.md
  - CRUSH.md should be inline code. Lines: 7, 13
  - Quoted paths should be code spans (package.json, Cargo.toml, requirements.txt, build.gradle). Line: 18
  - Quoted commands should be inline code (tsc, npm run lint, ruff check .). Line: 41
- internal/llm/prompt/init.md
  - Multiline content wrapped in a single backtick; use a fenced code block. Line: 1 (spans multiple lines)
  - CRUSH.md is bolded; should be inline code. Lines: 1, 7
- internal/llm/prompt/openai.md
  - CRUSH.md should be inline code. Lines: 10, 16
  - Identifiers referenced in prose should be inline code (file_path, old_string, new_string). Line: 25
  - Paths should be inline code (package.json, cargo.toml). Line: 36
  - Path should be inline code (.pre-commit-config.yaml). Line: 55
  - Commands should be inline code (npm run lint, npm run typecheck, ruff). Line: 72
- internal/llm/prompt/v2.md
  - CRUSH.md should be inline code. Lines: 119, 125, 196
  - Paths should be inline code (package.json, cargo.toml). Line: 180
  - Commands should be inline code (npm run lint, npm run typecheck, ruff). Line: 196

## internal/lsp
- internal/lsp/client.go
  - Early bailout (loop guard): prefer early continue rather than wrapping the whole body. Lines: 426–434
- internal/lsp/watcher/watcher.go
  - No one-off variables: inline temporary isMatch used only for immediate branching/return. Lines: 570–577, 599–603, 621–623, 626–631, 656–658, 663–665, 671–673, 726–729
  - No unnecessary nesting: flatten trivial guard chains. Lines: 68–71, 76–79
  - Self-describing units: rename maxFileSize to maxFileSizeBytes. Line: 816

## internal/app
- internal/app/app.go
  - Early bailout (loop guard): use early continue in cleanup loop. Lines: 427–431
  - No unnecessary nesting: flatten nested trivial guards in MCP topic derivation. Lines: 312–321
  - No trivial pass-through wrappers: UpdateAgentModel forwards without added value. Lines: 253–255
  - Self-describing names: clarify units/meaning
    - readBts → readBytes (bytes). Lines: 211–213, 229–233
    - maxSize → maxSizeMB; maxAge → maxAgeDays. Lines: 111–118 (MB), 113–124 (days)
- internal/app/lsp_events.go
  - Early bailout: use early return instead of wrapping entire function body. Lines: 88–101

## e2e (tests)
- e2e/mock_openai_responses.go
  - No unnecessary line breaks: two consecutive blank lines at EOF; keep at most one. Lines: 219–220
- e2e/scenario.go
  - No unnecessary nesting: flatten nested guard around env parsing; combine using Atoi’s result. Lines: 197–201
- e2e/setup_helpers.go
  - Self-describing names: rename local b to a descriptive predicate (e.g., compressEnabled). Lines: 73–74

## No findings (grouped)
- internal/{tui,config,ansiext,cmd,csync,diff,env,format,fsext,history,logging,message,permission,profile,pubsub,session,shell,testutil,transform,version}
