"""Tests for configuration management."""

import tempfile
from pathlib import Path

import yaml
from claude_optimizer.config.settings import OptimizerConfig


def test_config_from_file():
    """Test loading config from YAML file."""
    config_data = {
        "rollouts": {"max_parallel": 4, "max_turns": 50, "bash_timeout_ms": 30000},
        "exclude_patterns": ["*.log", "*.tmp"],
    }
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        yaml.dump(config_data, f)
        config_path = Path(f.name)
    
    try:
        config = OptimizerConfig.from_file(config_path)
        assert config.rollouts.max_parallel == 4
        assert "*.log" in config.exclude_patterns
    finally:
        config_path.unlink()