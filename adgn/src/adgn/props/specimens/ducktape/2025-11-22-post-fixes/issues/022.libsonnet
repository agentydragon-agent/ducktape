local I = import '../../specimens/lib.libsonnet';

// iss-022: Duplicated XDG user data directory path construction

I.issueOneOccurrence(
  rationale= |||
    The code constructs XDG user data directory paths (using `user_data_dir("adgn", ...)`)
    in multiple places instead of defining these paths once in a central location.

    **Current implementation:** Each module independently calls `user_data_dir("adgn", "agentydragon")`
    and constructs paths like `DEFAULT_DB_PATH = Path(...) / "mcp-bridge.db"` (mcp_bridge/cli.py, line 36).

    **Problems:**
    1. Duplication: Same platformdirs call in multiple files
    2. Inconsistency risk: Easy to use different app name/author
    3. Hard to change: Must update multiple files
    4. No discoverability: Can't easily find all data paths
    5. Testing difficulty: Can't easily override base directory

    **The correct approach:**
    Create a central paths module (e.g., `adgn/paths.py`) that defines XDG directories once
    (USER_DATA_DIR, USER_CACHE_DIR, USER_CONFIG_DIR) and specific application paths
    (MCP_BRIDGE_DB, RESPONSES_CACHE_DB, AUTH_TOKENS_FILE, etc.). Import these constants
    throughout the codebase.

    **Benefits:**
    1. Single source of truth for all paths
    2. Guaranteed consistency in app name/author
    3. Easy to add environment variable overrides once
    4. Testable: can patch the paths module
    5. Follows XDG Base Directory Specification correctly across platforms
  |||,
  properties=['single-source-of-truth', 'centralize-config'],
  filesToRanges={
    'adgn/src/adgn/agent/mcp_bridge/cli.py': [
      [36, 36],  // user_data_dir("adgn", "agentydragon") for DEFAULT_DB_PATH
    ],
  },
  gap_note= |||
    This finding illustrates **"centralize-config"**: application-wide configuration
    (paths, constants, defaults) should be defined in a central location, not scattered
    throughout the codebase.

    Benefits of centralized configuration:
    - Single source of truth for defaults
    - Easy to find and understand all config points
    - Simple to override for testing or different environments
    - Consistent behavior across modules

    This principle applies to:
    - File paths (XDG directories, data files, config files)
    - Constants (timeouts, buffer sizes, limits)
    - Default values (model names, API endpoints)
    - Feature flags (enabled/disabled features)

    Related to "single-source-of-truth": don't duplicate configuration values.
    When you need the same value in multiple places, import it from one canonical
    location.

    Common patterns:
    - `config.py` or `settings.py` - application settings
    - `paths.py` - file system paths
    - `constants.py` - magic numbers and strings
    - `defaults.py` - default values for optional parameters
  |||,
)
