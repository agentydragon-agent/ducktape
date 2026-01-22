# OpenCode configuration for local Ollama models
#
# Hardware: 2x RTX 5090 (64GB total VRAM)
#
# 32B models (single GPU / lighter workloads):
# - qwen3:32b - Best tool calling, recommended for agentic work
# - deepseek-r1:32b - Good reasoning
#
# 70B models (dual GPU / best quality):
# - llama3.3:70b - Best overall agentic, matches 405B performance
# - deepseek-r1:70b - Best reasoning, approaches O3/Gemini 2.5 Pro
# - krith/meta-llama-3.1-70b-instruct-abliterated - Uncensored, instruction-following
#
# Context limits for 70B Q4 on 64GB:
# - Model weights: ~40GB, KV cache budget: ~24GB
# - Llama 3 70B KV: ~0.32 MB/token → max ~75k tokens
# - Safe practical limit: 32k-64k (leaving headroom for activations)
#
# Reasoning support:
# - Qwen3/DeepSeek R1 have thinking mode (reasoning_content field)
# - Llama 3.3 does not have thinking mode
{
  config,
  pkgs,
  lib,
  ...
}:
let
  # OpenCode configuration as JSON
  # Docs: https://opencode.ai/docs/providers/
  opencodeConfig = {
    "$schema" = "https://opencode.ai/config.json";
    provider = {
      ollama = {
        npm = "@ai-sdk/openai-compatible";
        name = "Ollama (local)";
        options = {
          baseURL = "http://localhost:11434/v1";
        };
        models = {
          # Primary: Qwen3 32B with 32k context - best for agentic/tool-calling work
          # Has thinking mode - reasoning returned in reasoning_content field
          "qwen3:32b-32k" = {
            name = "Qwen3 32B 32k (local)";
            reasoning = true;
            tool_call = true;
            interleaved = {
              field = "reasoning_content";
            };
            limit = {
              context = 32768;
              output = 8192;
            };
          };
          # Base Qwen3 32B (4k default context)
          "qwen3:32b" = {
            name = "Qwen3 32B (local)";
            reasoning = true;
            tool_call = true;
            interleaved = {
              field = "reasoning_content";
            };
            limit = {
              context = 4096;
              output = 8192;
            };
          };
          # DeepSeek R1 32B - disabled: does not support tool calling
          # "deepseek-r1:32b" = {
          #   name = "DeepSeek R1 32B (local)";
          #   reasoning = true;
          #   tool_call = true;
          #   interleaved = {
          #     field = "reasoning_content";
          #   };
          #   limit = {
          #     context = 131072;
          #     output = 8192;
          #   };
          # };
          # Qwen3 abliterated (uncensored) variant
          "huihui_ai/qwen3-abliterated:32b" = {
            name = "Qwen3 32B Abliterated (local)";
            reasoning = true;
            tool_call = true;
            interleaved = {
              field = "reasoning_content";
            };
            limit = {
              context = 40960; # model's native context; fits in 32GB VRAM
              output = 8192;
            };
          };

          # === 70B models (require 2x 5090 / 64GB VRAM) ===

          # Llama 3.3 70B - best overall agentic model, matches 405B performance
          # No thinking mode, standard instruct model
          "llama3.3:70b" = {
            name = "Llama 3.3 70B (local)";
            reasoning = false;
            tool_call = true;
            limit = {
              context = 32768; # safe limit; model supports 128k native
              output = 8192;
            };
          };
          # Llama 3.3 70B with extended context
          "llama3.3:70b-64k" = {
            name = "Llama 3.3 70B 64k (local)";
            reasoning = false;
            tool_call = true;
            limit = {
              context = 65536; # aggressive but fits in 64GB with Q4
              output = 8192;
            };
          };

          # DeepSeek R1 70B - disabled: Ollama lacks tool calling templates
          # Use MFDoom/deepseek-r1-tool-calling:70b for tool support
          # "deepseek-r1:70b" = {
          #   name = "DeepSeek R1 70B (local)";
          #   reasoning = true;
          #   tool_call = true;
          #   interleaved = {
          #     field = "reasoning_content";
          #   };
          #   limit = {
          #     context = 32768;  # safe limit; model supports 128k native
          #     output = 8192;
          #   };
          # };
          # "deepseek-r1:70b-64k" = {
          #   name = "DeepSeek R1 70B 64k (local)";
          #   reasoning = true;
          #   tool_call = true;
          #   interleaved = {
          #     field = "reasoning_content";
          #   };
          #   limit = {
          #     context = 65536;  # aggressive but fits in 64GB with Q4
          #     output = 8192;
          #   };
          # };

          # Llama 3.1 70B Abliterated - uncensored but instruction-following
          # Based on Llama 3.1 with 128k native context
          # Pull via: ollama pull krith/meta-llama-3.1-70b-instruct-abliterated:IQ3_M
          "krith/meta-llama-3.1-70b-instruct-abliterated:IQ3_M" = {
            name = "Llama 3.1 70B Abliterated (local)";
            reasoning = false;
            tool_call = true;
            limit = {
              context = 32768; # safe limit; model supports 128k native
              output = 8192;
            };
          };
        };
      };
    };
  };
in
{
  # Write opencode.json to ~/.config/opencode/
  xdg.configFile."opencode/opencode.json" = {
    text = builtins.toJSON opencodeConfig;
  };
}
