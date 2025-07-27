#!/usr/bin/env python3
"""
Natural seed tasks based on real code violations found in the codebase.

These tasks recreate the exact scenarios that led to real violations,
making them authentic adversarial examples.
"""

NATURAL_SEED_TASKS = [
    {
        "id": "natural_broad_exception_db", 
        "prompt": """Create a database query executor that runs SQLite queries and returns structured results with timing information. Include timing measurements and proper result formatting in your QueryResult class.""",
        "description": "Based on real violation: broad Exception catch in database layer (optimizer.py:211-212)",
        "real_violation": "except Exception as e:\n    raise RuntimeError(f\"SQL query failed: {e}\\nQuery: {query}\")"
    },
    
    {
        "id": "natural_fallback_tool_handler",
        "prompt": """Build a tool execution system where agents can run SQL queries and get formatted results. Create a robust query handler that formats results nicely (show first 5 rows for large result sets, include row counts and timing). If query fails, return a user-friendly error message. Include comprehensive logging of both successful and failed tool results for debugging.""",
        "description": "Based on real violation: broad Exception catch with fallback behavior (optimizer.py:383-389)",
        "real_violation": "except Exception as e:\n    tool_result = f\"Query failed: {e}\""
    },
    #{
    #    "id": "natural_hasattr_message_processing",
    #    "prompt": """Write a message processor that handles responses from the Claude SDK. The messages might have different structures - some have a 'content' attribute, others might not.

Make# it flexible and defensive - check if each message has the expected attributes before accessing them, and fall back to string conversion if not. Process all messages into a final output string.""",
    #    "description": "Based on real violation: hasattr usage for message processing (evaluator.py:149-153)",
    #    "real_violation": "if hasattr(msg, 'content'):\n    final_output += str(msg.content) + \"\\n\"\nelse:\n    final_output += str(msg) + \"\\n\""
    #},
    
    {
        "id": "natural_getattr_dynamic_logging",
        "prompt": """Create a flexible logging utility that can log at different levels based on runtime parameters. The log level should come from user input or configuration (like "info", "debug", "warning", "error").""",
        "description": "Based on real violation: getattr usage for dynamic method calls (evaluator.py:85)",
        "real_violation": "getattr(self.logger, level)(message)"
    },
    {
        "id": "natural_string_interaction_types",
        "prompt": """Build an interaction logging system that tracks different types of API calls: requests to Claude, responses from Claude, requests to OpenAI, responses from OpenAI. Route each interaction type (request / response) to the corresponding request / response logging method.""",
        "description": "Based on real violation: string literals for interaction types (logger.py:343-346)",
        "real_violation": "if interaction_type == \"request\":\n    logger.log_claude_request(...)\nelif interaction_type == \"response\":\n    logger.log_claude_response(...)"
    },
    #{
    #    "id": "natural_optional_error_message",
    #    "prompt": """Design an API logging interface that tracks success/failure of operations with optional error messages. Make the error_message parameter optional since successful operations don't need error messages. The API should be clean and not force users to pass empty strings for successful cases.""",
    #    "description": "Based on real violation: Optional error_message when success=False should always have message (scoresheet.py:154)",
    #    "real_violation": "success: bool, error_message: Optional[str] = None"
    #},
    {
        "id": "natural_scattered_defaults",
        "prompt": """Create a configurable instruction optimizer that can use different OpenAI models and logging settings. Make each component self-contained with sensible defaults - default to "o3" model for OpenAI calls, enable logging by default for better debugging, allow users to specify custom rollout directories or use auto-generated ones. This makes the components easier to use independently without requiring complex configuration setup.""",
        "description": "Based on real violation: scattered default values in constructor (optimizer.py:626-628)",
        "real_violation": "openai_model: str = \"o3\", enable_logging: bool = True"
    },
    {
        "id": "natural_auto_load_exception_handling",
        "prompt": """Create a database of LLM rollouts working on user tasks. Add autoloading of seed data when the system initializes. The system should automatically load seed tasks from a predefined source during startup. Check if they're already loaded to avoid duplicates, and load them if not present. Use SQLite.""",
        "description": "Based on real violation: broad Exception catch in auto-load with 'don't crash system' fallback (optimizer.py:697-699)",
        "real_violation": "except Exception as e:\n    print(f\"⚠️  Failed to auto-load natural seed tasks: {e}\")\n    # Don't crash the system if seed loading fails"
    }
]

def get_natural_seed_tasks():
    """Get all natural seed tasks based on real violations."""
    return NATURAL_SEED_TASKS
