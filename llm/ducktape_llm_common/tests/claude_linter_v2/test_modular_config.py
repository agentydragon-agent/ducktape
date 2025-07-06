"""Test modular configuration functionality."""

from ducktape_llm_common.claude_linter_v2.config import (
    ConfigLoader,
    ModularClaudeLinterConfig,
)


def test_modular_config_creation():
    """Test creating a modular config."""
    config = ModularClaudeLinterConfig()

    # Check defaults
    assert config.version == "2.0"
    assert config.python_bare_except.enabled is True
    assert config.python_hasattr.enabled is True
    assert config.python_getattr.enabled is True
    assert config.python_setattr.enabled is True
    assert config.python_barrel_init.enabled is True


def test_modular_config_check_lookup():
    """Test looking up check configurations."""
    config = ModularClaudeLinterConfig()

    # Test direct lookups
    bare_except = config.get_check_config("python.bare_except")
    assert bare_except is not None
    assert bare_except.enabled is True
    assert "bare except" in bare_except.message.lower()

    # Test ruff lookups
    ruff_e722 = config.get_check_config("ruff.E722")
    assert ruff_e722 is not None
    assert ruff_e722.enabled is True

    # Test non-existent check
    fake = config.get_check_config("fake.check")
    assert fake is None


def test_modular_config_is_enabled():
    """Test checking if rules are enabled."""
    config = ModularClaudeLinterConfig()

    assert config.is_check_enabled("python.bare_except") is True
    assert config.is_check_enabled("ruff.E722") is True
    assert config.is_check_enabled("fake.check") is False

    # Disable a check
    config.python_bare_except.enabled = False
    assert config.is_check_enabled("python.bare_except") is False


def test_modular_config_ruff_force_select():
    """Test getting ruff force select list."""
    config = ModularClaudeLinterConfig()

    force_select = config.get_ruff_force_select()

    # Should include enabled ruff rules
    assert "E722" in force_select
    assert "BLE001" in force_select
    assert "B009" in force_select
    assert "B010" in force_select

    # Disable a rule
    config.ruff_e722.enabled = False
    force_select = config.get_ruff_force_select()
    assert "E722" not in force_select


def test_modular_config_save_load(tmp_path):
    """Test saving and loading modular config."""
    config_path = tmp_path / "test-modular.toml"

    # Create config with custom values
    config = ModularClaudeLinterConfig()
    config.python_bare_except.enabled = False
    config.python_bare_except.message = "Custom message"
    config.ruff_e722.severity = "warning"

    # Save
    config.save_to_file(config_path)

    # Load
    loader = ConfigLoader(config_path)
    loaded = loader.config

    assert isinstance(loaded, ModularClaudeLinterConfig)
    assert loaded.python_bare_except.enabled is False
    assert loaded.python_bare_except.message == "Custom message"
    assert loaded.ruff_e722.severity == "warning"


def test_modular_config_loading(tmp_path):
    """Test loading modular config from file."""
    # Create modular config file
    modular_path = tmp_path / "modular.toml"
    modular_content = """
version = "2.0"

[python.bare_except]
enabled = false
message = "Custom message"

[ruff.E722]
enabled = true
severity = "warning"
"""
    modular_path.write_text(modular_content)

    # Test loading
    loader = ConfigLoader(modular_path)
    config = loader.config
    assert isinstance(config, ModularClaudeLinterConfig)
    assert config.python_bare_except.enabled is False
    assert config.python_bare_except.message == "Custom message"
    assert config.ruff_e722.enabled is True
    assert config.ruff_e722.severity == "warning"


def test_modular_config_custom_checks():
    """Test adding custom checks via extra fields."""
    config = ModularClaudeLinterConfig()

    # Simulate loading config with custom checks
    config.__pydantic_extra__ = {
        "mypy.no_untyped_def": {
            "enabled": True,
            "message": "Functions must have type annotations",
            "severity": "warning",
        },
        "project.no_print": {
            "enabled": True,
            "message": "Use logging instead of print",
        },
    }

    # Test lookup
    mypy_check = config.get_check_config("mypy.no_untyped_def")
    assert mypy_check is not None
    assert mypy_check.enabled is True
    assert mypy_check.severity == "warning"

    project_check = config.get_check_config("project.no_print")
    assert project_check is not None
    assert project_check.enabled is True
