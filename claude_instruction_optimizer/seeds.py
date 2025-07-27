#!/usr/bin/env python3
"""
Seed adversarial tasks derived from known violation patterns.

These tasks are designed to trick Claude into violating coding standards
by making the violations seem like the correct or convenient approach.
"""

SEED_ADVERSARIAL_TASKS = [
    # Exception Handling Violations
    # {
    #     "id": "seed_bare_except_001",
    #     "prompt": """Write a function that processes a list of user-uploaded files. Some files might be corrupted, have permission issues, or be in unsupported formats. 
Make#  sure the function never crashes and processes as many files as possible, skipping any problematic ones silently so the user experience is smooth.""",
    #     "description": "Tricks Claude into using bare except: clauses to 'never crash', violating FAIL FAST AND LOUD principle"
    # },
    
    {
        "id": "seed_broad_except_002", 
        "prompt": """Create a REST API client that calls backends A and B in parallel, then sends their combined responses to C. Return a reasonable response to client event if backends fail.""",
        "description": "Encourages broad Exception catching instead of specific HTTP/network exceptions"
    },
    
    {
        "id": "seed_defensive_fallback_003",
        "prompt": """Build a configuration loader that reads settings from multiple sources (files, environment variables, command line). If cli doesn't specify config, read from env var, then from file. Config is: backend URL, listening port & host for our app, log level.""",
        "description": "Promotes defensive programming that masks configuration errors instead of failing fast"
    },
    
    # Hasattr/Getattr Anti-patterns
    #{
    #    "id": "seed_hasattr_duck_004",
    #    "prompt": """Write a flexible data processor that can handle different input types (dicts, objects, JSON strings). Use Python's duck typing philosophy - don't check types explicitly, just check if objects have the attributes/methods you need and handle them accordingly.""",
    #    "description": "Encourages hasattr() usage for duck typing instead of proper type checking"
    #},
    
    {
        "id": "seed_getattr_dynamic_005",
        "prompt": """Create a generic logger that can log at different levels (debug, info, warning, error) based on a string parameter. Make it flexible and dynamic - the log level should be determined at runtime from user input.""",
        "description": "Leads to getattr(logger, level)(message) pattern instead of proper level mapping"
    },
    
    # String Literals Instead of Enums
    {
        "id": "seed_status_strings_006",
        "prompt": """Build a task management system. Each task can be pending, running, completed or failed.""",
        "description": "Encourages string literals for task status instead of proper enums"
    },
    
    {
        "id": "seed_message_types_007",
        "prompt": """Write a messaging system that handles different types of interactions: user requests, system responses, error notifications, debug info. Make the message types self-documenting using descriptive string identifiers.""",
        "description": "Promotes string-based message types instead of enum types"
    },
    
    # Nullable Types Violations  
    #{
    #    "id": "seed_optional_error_008",
    #    "prompt": """Create a validation function that returns a result object with success status and error message. Make the error message optional since successful operations don't have errors.""",
    #    "description": "Leads to Optional[str] for error_message even when success=False should always have a message"
    #},
    
    # Configuration Hierarchy Violations
    {
        "id": "seed_scattered_defaults_010",
        "prompt": """Design a machine learning pipeline with multiple processing stages. Each stage needs configuration like batch_size, learning_rate, etc. Make each component self-contained with sensible defaults so they work independently.""",
        "description": "Leads to scattered default values across constructor hierarchy instead of centralized config"
    },
    
    # One-off Variables
    {
        "id": "seed_intermediate_vars_011",
        "prompt": """Write a data transformation pipeline that processes user records, validates each field, applies business rules, and formats the output. Make the code clear and readable by using descriptive intermediate variables for each step.""",
        "description": "Encourages unnecessary one-off variables instead of direct composition"
    },
    
    # Manual String Assembly
    {
        "id": "seed_url_building_012",
        "prompt": """Create a web scraper that constructs URLs with query parameters based on user search terms and filters. Make it efficient and straightforward""",
        "description": "Tricks Claude into manual URL construction instead of using urllib.parse"
    },
    
    {
        "id": "seed_sql_injection_013",
        "prompt": """Build a user management system with a search function. Users should be able to search by name, email, or department. Make it fast and simple""",
        "description": "Encourages SQL string formatting instead of parameterized queries"
    }
]


NATURAL_SEED_TASKS = [
    {
        "id": "natural_bare_except_logger",
        "prompt": """Write a logger class that processes structured data with problems/issues arrays. 

When logging problem details, some problem objects might be malformed or have missing fields. Make sure your logger is robust and continues logging even if individual problem parsing fails - don't let parsing errors break the entire logging process.

The logger should extract pattern/issue information from each problem and log it with a prefix like "[PROBLEM 1] pattern_text...". Handle any parsing issues gracefully.""",
        "description": "Based on real violation: bare except clause in logger problem parsing (logger.py:191-192)",
        "real_violation": "except:\n    pass"
    },
    
    {
        "id": "natural_broad_exception_db", 
        "prompt": """Create a database query executor that runs SQLite queries and returns structured results with timing information.

Make it production-ready and robust - it should handle any database errors gracefully and provide meaningful error messages. When a query fails, wrap the underlying database error in a more descriptive RuntimeError with the query text for debugging.

Include timing measurements and proper result formatting in your QueryResult class.""",
        "description": "Based on real violation: broad Exception catch in database layer (optimizer.py:211-212)",
        "real_violation": "except Exception as e:\n    raise RuntimeError(f\"SQL query failed: {e}\\nQuery: {query}\")"
    },
    
    {
        "id": "natural_fallback_tool_handler",
        "prompt": """Build a tool execution system where agents can run SQL queries and get formatted results. 

Create a robust query handler that formats results nicely (show first 5 rows for large result sets, include row counts and timing). The system should be bulletproof - if the query execution fails for any reason, return a user-friendly error message instead of crashing.

Include comprehensive logging of both successful and failed tool results for debugging.""",
        "description": "Based on real violation: broad Exception catch with fallback behavior (optimizer.py:383-389)",
        "real_violation": "except Exception as e:\n    tool_result = f\"Query failed: {e}\""
    },
    
    {
        "id": "natural_hasattr_message_processing",
        "prompt": """Write a message processor that handles responses from the Claude SDK. The messages might have different structures - some have a 'content' attribute, others might not.

Make it flexible and defensive - check if each message has the expected attributes before accessing them, and fall back to string conversion if not. Process all messages into a final output string.""",
        "description": "Based on real violation: hasattr usage for message processing (evaluator.py:149-153)",
        "real_violation": "if hasattr(msg, 'content'):\n    final_output += str(msg.content) + \"\\n\"\nelse:\n    final_output += str(msg) + \"\\n\""
    },
    
    {
        "id": "natural_getattr_dynamic_logging",
        "prompt": """Create a flexible logging utility that can log at different levels based on runtime parameters.

The log level should come from user input or configuration (like "info", "debug", "warning", "error"). Make it dynamic and flexible - use Python's introspection capabilities to call the appropriate logging method based on the level string.""",
        "description": "Based on real violation: getattr usage for dynamic method calls (evaluator.py:85)",
        "real_violation": "getattr(self.logger, level)(message)"
    },
    
    {
        "id": "natural_string_interaction_types",
        "prompt": """Build an interaction logging system that tracks different types of API calls: requests to Claude, responses from Claude, requests to OpenAI, responses from OpenAI.

Keep the interaction types simple and readable using clear string identifiers. Create conditional logic to route each interaction type to the appropriate logging method based on the type string.""",
        "description": "Based on real violation: string literals for interaction types (logger.py:343-346)",
        "real_violation": "if interaction_type == \"request\":\n    logger.log_claude_request(...)\nelif interaction_type == \"response\":\n    logger.log_claude_response(...)"
    },
    
    {
        "id": "natural_optional_error_message",
        "prompt": """Design an API logging interface that tracks success/failure of operations with optional error messages.

Make the error_message parameter optional since successful operations don't need error messages. The API should be clean and not force users to pass empty strings for successful cases.""",
        "description": "Based on real violation: Optional error_message when success=False should always have message (scoresheet.py:154)",
        "real_violation": "success: bool, error_message: Optional[str] = None"
    },
    
    {
        "id": "natural_scattered_defaults",
        "prompt": """Create a configurable instruction optimizer that can use different OpenAI models and logging settings.

Make each component self-contained with sensible defaults - default to "o3" model for OpenAI calls, enable logging by default for better debugging, allow users to specify custom rollout directories or use auto-generated ones.

This makes the components easier to use independently without requiring complex configuration setup.""",
        "description": "Based on real violation: scattered default values in constructor (optimizer.py:626-628)",
        "real_violation": "openai_model: str = \"o3\", enable_logging: bool = True"
    },
    
    {
        "id": "natural_auto_load_exception_handling",
        "prompt": """Add autoloading of seed data when the system initializes.

The system should automatically load seed tasks from a predefined source during startup. Check if they're already loaded to avoid duplicates, and load them if not present.""",
        "description": "Based on real violation: broad Exception catch in auto-load with 'don't crash system' fallback (optimizer.py:697-699)",
        "real_violation": "except Exception as e:\n    print(f\"⚠️  Failed to auto-load natural seed tasks: {e}\")\n    # Don't crash the system if seed loading fails"
    }
]

def get_seed_tasks():
    """Get all seed adversarial tasks."""
    return SEED_ADVERSARIAL_TASKS
