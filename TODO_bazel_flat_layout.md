# Migrate Bazelized Python to Flat Layout

Migrate all Bazelized Python packages from `src/` layout to flat layout and remove redundant `pyproject.toml` files.

## Migration Steps (per package)

1. Move `pkg/src/pkg_name/*` → `pkg/*`
2. Remove `pkg/src/`
3. Update `BUILD.bazel`: change glob pattern, add `imports = [".."]`
4. Delete `pyproject.toml` and remove `exports_files(["pyproject.toml"])` if present

## Packages

### Needs migration (src/ layout)

- [ ] agent_core
- [x] claude_web_hooks
- [x] difftree
- [x] ember
- [x] openai_utils
- [x] py_detectors
- [ ] sysrw
- [x] wt

### Already flat layout

- [x] adgn
- [x] agent_core_testing
- [x] agent_server
- [x] cli_util
- [x] editor_agent/host
- [x] editor_agent/runtime
- [x] gatelet
- [x] git_commit_ai
- [x] gmail_archiver
- [x] gnome_terminal_profile_switcher
- [x] inop
- [x] inventree_utils
- [x] mcp_infra
- [x] mcp_starter
- [x] mcp_utils
- [x] net_util
- [x] rspcache
- [x] sandboxed_jupyter
- [x] tana
