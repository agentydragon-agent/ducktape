# OpenCode configuration for local Ollama models
#
# Hardware: 2x RTX 5090 (64GB total VRAM)
#
# Query model capabilities via local Ollama API (must pull model first):
#   curl -s http://localhost:11434/api/show -d '{"name": "MODEL"}' | jq '.capabilities'
#   Returns: ["completion", "tools", "thinking"] or subset
# No remote registry API for capabilities - see github.com/ollama/ollama/issues/10097
#
# Capability matrix:
#   Model                    | Reasoning | Tools | Notes
#   -------------------------|-----------|-------|---------------------------
#   gpt-oss-120b-32k         | ✓         | ✓     | OpenAI MoE (5.1B active), ~56GB, fits 2x5090
#   gpt-oss-20b-32k          | ✓         | ✓     | OpenAI MoE, 14GB, reasoning + tools
#   qwen3-coder:30b          | ✓         | ✓     | MoE (3.3B active), both work!
#   qwen3:32b                | ✓         | ~     | Tools buggy in Ollama
#   llama3.3:70b             | ✗         | ✓     | Reliable tools, no thinking
#   llama3.1-abliterated:70b | ✗         | ✓     | Uncensored, reliable tools
#   deepseek-r1:32b/70b      | ✓         | ✗     | Disabled - no tool support
#
# Context limits for 70B Q4 on 64GB:
# - Model weights: ~40GB, KV cache budget: ~24GB
# - Llama 3 70B KV: ~0.32 MB/token → max ~75k tokens
# - Safe practical limit: 32k-64k (leaving headroom for activations)
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
        # Use ollama-ai-provider-v2 for native reasoning/thinking support
        # @ai-sdk/openai-compatible can't parse the non-standard 'reasoning' field
        npm = "ollama-ai-provider-v2";
        name = "Ollama (local)";
        options = {
          baseURL = "http://localhost:11434/api";
        };
        models = {
          # === GPT-OSS - OpenAI's open-weight MoE models ===
          # Apache 2.0 license, reasoning + tools, configurable reasoning effort
          # Docs: https://ollama.com/library/gpt-oss

          # GPT-OSS 120B - OpenAI's flagship open model
          # MoE: 117B total params, 5.1B active, MXFP4 quantized (~56GB weights)
          # On 2x 5090 (64GB): fits cleanly, 32k context saturates VRAM
          # IMPORTANT: Create variant first:
          #   ollama run gpt-oss:120b
          #   /set parameter num_ctx 32768
          #   /save gpt-oss-120b-32k
          #   /bye
          "gpt-oss-120b-32k" = {
            name = "GPT-OSS 120B 32k (local)";
            reasoning = true;
            tool_call = true;
            options = {
              extraBody = {
                think = "high"; # enable reasoning mode
              };
            };
            limit = {
              context = 32768; # max for 64GB VRAM (model + KV cache)
              output = 8192;
            };
          };
          # GPT-OSS 20B - smaller variant, fits easily on 64GB
          # MoE architecture, 14GB weights, excellent headroom for large context
          # IMPORTANT: Create variant first:
          #   ollama run gpt-oss:20b
          #   /set parameter num_ctx 32768
          #   /save gpt-oss-20b-32k
          #   /bye
          "gpt-oss-20b-32k" = {
            name = "GPT-OSS 20B 32k (local)";
            reasoning = true;
            tool_call = true;
            options = {
              extraBody = {
                think = "high"; # enable reasoning mode
              };
            };
            limit = {
              context = 32768;
              output = 8192;
            };
          };

          # === Qwen3-Coder - BOTH reasoning AND reliable tool calling ===

          # Qwen3-Coder 30B - best for agentic work (reasoning + tools both work)
          # Unsloth fixed tool calling in Aug 2025
          "qwen3-coder:30b" = {
            name = "Qwen3-Coder 30B (local)";
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

          # === Qwen3 - reasoning works, tools BUGGY in Ollama ===

          # Qwen3 32B with 32k context
          # WARNING: Tool calling has parsing issues in Ollama
          "qwen3:32b-32k" = {
            name = "Qwen3 32B 32k (local)";
            reasoning = true;
            tool_call = true; # unreliable
            interleaved = {
              field = "reasoning_content";
            };
            limit = {
              context = 32768;
              output = 8192;
            };
          };
          # Base Qwen3 32B (4k default context)
          # WARNING: Tool calling has parsing issues in Ollama
          "qwen3:32b" = {
            name = "Qwen3 32B (local)";
            reasoning = true;
            tool_call = true; # unreliable
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
          # WARNING: Tool calling has parsing issues in Ollama
          "huihui_ai/qwen3-abliterated:32b" = {
            name = "Qwen3 32B Abliterated (local)";
            reasoning = true;
            tool_call = true; # unreliable
            interleaved = {
              field = "reasoning_content";
            };
            limit = {
              context = 40960; # model's native context; fits in 32GB VRAM
              output = 8192;
            };
          };

          # === 70B models (require 2x 5090 / 64GB VRAM) ===
          # === Llama - RELIABLE tools, NO reasoning/thinking ===

          # Llama 3.3 70B - best overall for tool use, matches 405B performance
          "llama3.3:70b" = {
            name = "Llama 3.3 70B (local)";
            reasoning = false;
            tool_call = true;
            limit = {
              context = 32768; # safe limit; model supports 128k native
              output = 8192;
            };
          };
          # Llama 3.3 70B with extended context (no reasoning)
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

          # Llama 3.1 70B Abliterated - uncensored, reliable tools, no reasoning
          # Pull via: ollama pull krith/meta-llama-3.1-70b-instruct-abliterated:IQ3_M
          "krith/meta-llama-3.1-70b-instruct-abliterated:IQ3_M" = {
            name = "Llama 3.1 70B Abliterated (local)";
            reasoning = false; # no thinking mode
            tool_call = true; # reliable
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
