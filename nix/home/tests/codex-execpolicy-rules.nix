# Test Codex execpolicy rule generation from the shared allowed-commands SSOT.
#
# Run: nix-instantiate --eval --strict nix/home/tests/codex-execpolicy-rules.nix

let
  pkgs = import <nixpkgs> { };
  inherit (pkgs) lib;

  allowed = import ../allowed-commands.nix;
  generated = import ../codex/execpolicy-rules.nix { inherit lib; };
in
{
  test_rule_count_matches_ssot = {
    expr = builtins.length generated.rules;
    expected = builtins.length allowed.noSudo;
  };

  test_has_git_status_rule = {
    expr = builtins.elem "prefix_rule(pattern=[\"git\",\"status\"], decision=\"allow\")" generated.rules;
    expected = true;
  };

  test_has_header_pointer_to_checker = {
    expr = lib.hasInfix "codex-execpolicy check --pretty" generated.text;
    expected = true;
  };
}
