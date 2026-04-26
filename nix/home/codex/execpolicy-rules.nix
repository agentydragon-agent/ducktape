# Generate Codex execpolicy rules from the shared allowed-commands SSOT.
#
# Codex execpolicy is prefix-based, so we intentionally fail closed if the SSOT
# grows an `exact` entry that would otherwise be silently widened.
{ lib }:
let
  allowed = import ../allowed-commands.nix;

  tokenize = cmd: builtins.filter (part: part != "") (lib.splitString " " cmd);

  renderRule =
    entry:
    if entry.type != "prefix" then
      throw ''
        Codex execpolicy generation only supports `type = "prefix"` entries.
        Refusing to widen `${entry.cmd}` from allowed-commands.nix into a prefix rule.
      ''
    else
      "prefix_rule(pattern=${builtins.toJSON (tokenize entry.cmd)}, decision=\"allow\")";

  header = ''
    # Auto-generated from nix/home/allowed-commands.nix.
    # Codex loads *.rules from $CODEX_HOME/rules/ automatically.
    #
    # Syntax quickstart:
    #   prefix_rule(pattern=["git", "status"], decision="allow")
    #   prefix_rule(pattern=["git", "commit"], decision="prompt", justification="history-changing")
    #   prefix_rule(pattern=["rm"], decision="forbidden", justification="destructive; use a safer alternative")
    #
    # Test this file locally:
    #   codex-execpolicy check --pretty --rules "$CODEX_HOME/rules/default.rules" -- git status
    #   codex-execpolicy check --pretty --rules "$CODEX_HOME/rules/default.rules" -- bash -lc 'git status'
    #
    # Codex treats matching `decision="allow"` rules as sandbox-bypassing for
    # the matched command prefix, so keep this file limited to safe commands.
    #
    # `match=` / `not_match=` are load-time examples, not exact-match enforcement.
    # This generator only emits allow rules for shared `prefix` commands.
  '';

  rules = map renderRule allowed.noSudo;
in
{
  inherit rules;
  text = lib.concatLines ([ header ] ++ rules);
}
