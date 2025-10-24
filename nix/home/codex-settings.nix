{
  model = "gpt-5-codex";
  # base_instructions_file = "/home/agentydragon/.codex/prompts/claude_code_with_applypatch.md";
  tui = {
    auto_mount_repo = true;
  };
  shell_environment_policy = {
    "inherit" = "all";
    "set" = { CODEX_AGENT = "1"; };
  };
  sandbox_mode = "workspace-write";
  sandbox_workspace_write = {
    writable_roots = [
      "/home/agentydragon/.pyenv"
      "/home/agentydragon/.cache/sccache"
      "/home/agentydragon/.cache/nix"
      "/nix"
      "/nix/var/nix"
    ];
    network_access = true;
    exclude_tmpdir_env_var = false;
    exclude_slash_tmp = false;
  };
}
