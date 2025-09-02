## [Imports at the top](../../definitions/python/imports-top.md)

Many inline imports appear inside functions across modules in `wt/`; imports should live at module top unless a narrowly justified exception applies (cycle break, heavy import deferral, plugin/hot-reload).

- **wt/wt/cli.py**: 101, 158, 193, 198, 206, 253
- **wt/wt/client/handlers.py**: 10, 16, 50, 75, 86, 89, 94, 97, 104, 120, 127, 134, 136, 142, 152, 164–168, 194, 196, 201, 214, 220, 226, 238, 240, 242–243, 249, 254, 263, 277, 298, 301–302, 310, 342
- **wt/wt/client/shell_utils.py**: 9, 16
- **wt/wt/client/worktree_utils.py**: 83, 108–109, 148
- **wt/wt/client/wt_client.py**: 42, 67, 99, 168
- **wt/wt/server/github_client.py**: 109
- **wt/wt/server/copy_strategies.py**: 123, 139
- **wt/wt/plugins.py**: 41, 46
- **wt/wt/server/worktree_service.py**: 105, 197, 214, 264, 281, 293, 300–301, 388, 445, 490, 507, 513

## [Use StrEnum for string‑valued enums](../../definitions/python/strenum.md)

- **wt/wt/shared/github_models.py**: 13–18, 49–52, 60–62
- **wt/wt/shared/configuration.py**: 21-27

## [Markdown inline formatting for code identifiers, flags, paths, and URIs](../../definitions/markdown/inline-formatting.md)

- **wt/ARCHITECTURE.md**: 256, 259 have plain "WT_DIR" references
- **wt/WORKTREE_IDEAS.md**: 7, 16 have plain "WT_DIR" references
- **wt/README.md**: 16, 18, 190 have plain "PATH" / env var references

## [Pass Path objects to PathLike APIs (no str())](../../definitions/python/pathlike.md)

- **wt/wt/server/copy_strategies.py**:
  - Basic: 46, 63, 111
  - Also `_get_copyable_entries` casts `Path` to `str` while it's used for the purpose of passing into `subprocess.run`; should just return unconverted `Path`
- **wt/wt/server/worktree_service.py**: 337
- **wt/wt/shared/git_utils.py**: 29

## [Forbid dynamic attribute access and catching AttributeError](../../definitions/python/forbid-dynamic-attrs.md) 

- `getattr(pygit2, "GIT_STATUS_...", 0)` should be plain `pygit2.GIT_STATUS_...` (see property link above)
  - **wt/wt/server/git_manager.py**: 116–123.
  - **wt/wt/server/worktree_service.py**: 143

