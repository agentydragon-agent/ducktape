# Agent Definitions

This directory contains agent definition packages synced to the database and deployed to containers.

## Documentation Audience

**How docs reach agents:** The default `print_bootstrap()` in init scripts reads and prints all `.md` files from `/workspace/docs/`. This means whatever is in an agent's `docs/` directory gets injected into its transcript automatically.

**Audience is determined by directory structure:**
- `critic/docs/` → only critic agents see this
- `grader/docs/` → only grader agents see this
- `common/docs/` → agents that symlink their `docs/` to `common/docs/` see this

**Write for the audiences who will actually read the doc.** A doc can target multiple audiences, but if it does, all content must be relevant to all of them. Don't include content that's only useful to some readers — either split the doc or leave that content out.

**Example - wrong (irrelevant to the audience):**
> The runtime enforces a limit via `adgn.mcp.exec.models.MAX_BYTES_CAP`. BootstrapHandler checks for TruncatedStream in the BaseExecResult and raises InitFailedError.

This leaks infrastructure details that definition authors can't act on.

**Example - right (actionable for the audience):**
> Your init script output must stay under the limit defined by `adgn.mcp.exec.models.MAX_BYTES_CAP`. If exceeded, the agent run fails immediately. To stay under the limit: print less in init, or move large content to `/workspace/docs/` for on-demand reading.

## ⚠️ WARNING: Symlinks Everywhere

**This directory structure contains BOTH file AND directory symlinks.**

Before editing ANY file in `agent_defs/`, run:
```bash
ls -laR agent_defs/ | head -100
```

**Common traps:**
- `improvement/docs` is a symlink to `../common/docs` — writing to `improvement/docs/foo.md` actually writes to `common/docs/foo.md`
- Many files like `dead_code/init` are symlinks to `../critic/init`
- The Write tool follows symlinks — you may edit a different file than intended

**Safe workflow:**
1. Run `ls -la` on the specific directory before any write
2. Check if the target file or its parent directory is a symlink
3. If editing a symlinked file, decide: edit the source, or replace symlink with a real file?

## Definition Authoring

@common/docs/writing_agent_definitions.md

## Agent Types

**Primary agents:** `critic/`, `grader/`, `clustering/`, `improvement/`, `prompt_optimizer/`

**Critic-based detectors:** `dead_code/`, `high_recall_critic/`, `flag_propagation/`, `contract_truthfulness/` — inherit from critic via symlinks.

**Shared content:** `common/docs/`, `common/examples/` — referenced via symlinks from agent definitions.

## Symlink Convention

Agent definitions use symlinks to share common content:

```
critic/docs -> ../common/docs
dead_code/init -> ../critic/init
dead_code/bin -> ../critic/bin
```

When packed for deployment, external symlinks are resolved — target content is included in the archive.

## Link Style in Markdown

Use backtick code spans for file references. Do NOT use markdown links with duplicate paths.

**Correct:**
```markdown
See `docs/schema_docs.md` for details.
```

**Incorrect:**
```markdown
See [docs/schema_docs.md](docs/schema_docs.md) for details.
```

The backtick style is preferred: shorter, no duplication, works in container context.

## Validation

```bash
adgn-properties agent-definition validate critic/
adgn-properties db sync
```
