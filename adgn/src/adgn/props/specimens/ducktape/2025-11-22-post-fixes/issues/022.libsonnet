local I = import '../../specimens/lib.libsonnet';

// iss-022: Duplicated XDG user data directory path construction

I.issueOneOccurrence(
  rationale= |||
    The code constructs XDG user data directory paths (using `user_data_dir("adgn", ...)`)
    in multiple places instead of defining these paths once in a central location.

    **Current implementation (mcp_bridge/cli.py, line 36):**
    ```python
    from platformdirs import user_data_dir

    # Default database path in XDG user data directory
    DEFAULT_DB_PATH = Path(user_data_dir("adgn", "agentydragon")) / "mcp-bridge.db"
    ```

    **Problems:**

    1. **Duplication**: Same `user_data_dir("adgn", "agentydragon")` call in multiple files
    2. **Inconsistency risk**: Easy to use different app name/author in different places
    3. **Hard to change**: Changing the base directory requires updating multiple files
    4. **No single source**: Can't easily find all data paths used by the application
    5. **Testing difficulty**: Can't easily override base directory for tests

    **The correct approach:**

    Define data directories once in a central module:

    ```python
    # src/adgn/paths.py or src/adgn/config/paths.py
    \"\"\"Centralized path configuration for adgn applications.\"\"\"
    from pathlib import Path
    from platformdirs import user_data_dir, user_cache_dir, user_config_dir

    # XDG directories for adgn
    USER_DATA_DIR = Path(user_data_dir("adgn", "agentydragon"))
    USER_CACHE_DIR = Path(user_cache_dir("adgn", "agentydragon"))
    USER_CONFIG_DIR = Path(user_config_dir("adgn", "agentydragon"))

    # Specific application paths
    MCP_BRIDGE_DB = USER_DATA_DIR / "mcp-bridge.db"
    RESPONSES_CACHE_DB = USER_CACHE_DIR / "responses.db"
    AUTH_TOKENS_FILE = USER_CONFIG_DIR / "auth-tokens.json"

    # Ensure directories exist on import
    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    USER_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    ```

    Then use throughout the codebase:
    ```python
    # src/adgn/agent/mcp_bridge/cli.py
    from adgn.paths import MCP_BRIDGE_DB

    DEFAULT_DB_PATH = MCP_BRIDGE_DB

    # Or directly:
    @click.option("--db", default=MCP_BRIDGE_DB, ...)
    ```

    **Benefits:**

    1. **Single source of truth**: All paths defined in one place
    2. **Consistency**: Guaranteed to use same app name/author everywhere
    3. **Easy to change**: Update base directory in one place
    4. **Discoverability**: Import paths module to see all data locations
    5. **Testable**: Can patch `adgn.paths` module for testing
    6. **Environment override**: Can add environment variable support once:
       ```python
       USER_DATA_DIR = Path(
           os.environ.get("ADGN_DATA_DIR") or
           user_data_dir("adgn", "agentydragon")
       )
       ```

    **Testing benefits:**

    With centralized paths, tests can override the base directory:
    ```python
    # In test setup:
    import adgn.paths
    adgn.paths.USER_DATA_DIR = tmp_path / "data"
    adgn.paths.MCP_BRIDGE_DB = adgn.paths.USER_DATA_DIR / "mcp-bridge.db"
    ```

    **XDG Base Directory Specification:**

    The correct pattern follows XDG standards:
    - `XDG_DATA_HOME` (~/.local/share) - user-specific data files
    - `XDG_CONFIG_HOME` (~/.config) - user-specific configuration
    - `XDG_CACHE_HOME` (~/.cache) - user-specific non-essential data

    Use `platformdirs` once, in the paths module, to get these correctly on all platforms.
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
