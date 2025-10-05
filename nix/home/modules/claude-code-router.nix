{ config, lib, pkgs, ... }:

let
  cfg = config.programs.claudeCodeRouter;
  json = pkgs.formats.json {};
  homeDir = config.home.homeDirectory;

  # Path relative to this module file: nix/home/modules -> nix/home/claude-code-router/transformers
  defaultTransformersSrc = ../claude-code-router/transformers;

  transformersPkg = pkgs.stdenvNoCC.mkDerivation {
    pname = "claude-code-router-transformers";
    version = "unstable";
    src = defaultTransformersSrc;
    installPhase = ''
      mkdir -p $out/transformers
      cp -r $src/* $out/transformers/
    '';
  };

  configJson = json.generate "claude-code-router.json" ({
    transformers = [
      {
        path = "${homeDir}/.claude-code-router/transformers/openai-reasoning.js";
        options = { patterns = cfg.reasoningModelPatterns; };
      }
      {
        path = "${homeDir}/.claude-code-router/transformers/system-replace.js";
        options = cfg.systemReplace;
      }
    ];

    Providers = lib.mapAttrsToList (name: p: {
      inherit name;
      api_base_url = p.apiBaseUrl;
      models = p.models;
      transformer = { use = p.useTransformers; };
    }) cfg.providers;

    Router = cfg.router;
    Tracing = { enabled = cfg.tracing; };
    TransformerOptions = { "system-replace" = cfg.systemReplace; };
    HOST = cfg.host;
    PORT = cfg.port;
    NON_INTERACTIVE_MODE = cfg.nonInteractive;
  });
in {
  options.programs.claudeCodeRouter = with lib; {
    enable = mkEnableOption "claude-code-router files and config";

    host = mkOption { type = types.str; default = "127.0.0.1"; };
    port = mkOption { type = types.port; default = 3456; };
    tracing = mkOption { type = types.bool; default = true; };
    nonInteractive = mkOption { type = types.bool; default = false; };

    reasoningModelPatterns = mkOption {
      type = types.listOf types.str;
      default = [];
      description = "Regex patterns for OpenAI reasoning models (matched against model name).";
    };

    systemReplace = mkOption {
      type = types.submodule {
        options = {
          search = mkOption { type = types.str; default = "Claude Code"; };
          replace = mkOption { type = types.str; default = "OpenAI Code"; };
          regex = mkOption { type = types.bool; default = false; };
        };
      };
      default = {};
      description = "Options for the system-replace transformer.";
    };

    providers = mkOption {
      type = types.attrsOf (types.submodule {
        options = {
          apiBaseUrl = mkOption { type = types.str; };
          models = mkOption { type = types.listOf types.str; default = []; };
          useTransformers = mkOption { type = types.listOf types.str; default = []; };
        };
      });
      default = { };
      description = "Providers keyed by name. API keys should be supplied via environment, not here.";
    };

    router = mkOption {
      type = types.submodule {
        options = {
          default = mkOption { type = types.str; default = ""; };
          background = mkOption { type = types.str; default = ""; };
          think = mkOption { type = types.str; default = ""; };
          longContext = mkOption { type = types.str; default = ""; };
          webSearch = mkOption { type = types.str; default = ""; };
        };
      };
      default = { };
      description = "Routing targets for various task types.";
    };

  };

  config = lib.mkIf cfg.enable {
    # Install transformers and generated config.json
    home.file.".claude-code-router/transformers".source = "${transformersPkg}/transformers";
    home.file.".claude-code-router/config.json".source = configJson;

    # No service definitions; module only manages files
  };
}
