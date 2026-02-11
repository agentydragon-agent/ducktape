from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import cast

from platformdirs import user_config_dir
from pydantic import BaseModel, Field, JsonValue
import yaml


def _xdg_presets_dir() -> Path:
    """Return the default XDG-compliant presets directory.

    Uses platformdirs to resolve the user configuration directory for app "adgn",
    then appends the "presets" subfolder.
    """
    cfg_root = Path(user_config_dir("adgn"))
    return cfg_root / "presets"


class AgentPreset(BaseModel):
    name: str = Field(description="Preset name identifier")
    description: str | None = Field(None, description="Human-readable description of the preset")
    system: str | None = Field(None, description="System message for the agent")
    specs: dict[str, JsonValue] = Field(default_factory=dict, description="Agent specifications (arbitrary JSON)")
    approval_policy: str | None = Field(None, description="Approval policy Python source code")
    # Source metadata (filled by loader; used by UI)
    file_path: str | None = Field(None, description="Source file path for this preset")
    modified_at: str | None = Field(None, description="Last modification time (ISO-8601 string)")


def _load_yaml(path: Path) -> dict[str, JsonValue]:
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"preset must be a mapping: {path}")
    return cast(dict[str, JsonValue], data)


def load_presets_from_dir(root: Path) -> dict[str, AgentPreset]:
    out: dict[str, AgentPreset] = {}
    if not root.exists() or not root.is_dir():
        return out
    for p in sorted(root.glob("*.y*ml")):
        data = _load_yaml(p)
        # Default name from filename when missing in YAML
        if "name" not in data or not data.get("name"):
            data = dict(data)
            data["name"] = p.stem
        preset = AgentPreset.model_validate(data)
        stat = p.stat()  # Fail fast on OS errors
        preset.file_path = str(p)
        preset.modified_at = datetime.fromtimestamp(stat.st_mtime).isoformat()
        out[preset.name] = preset
    return out


def discover_presets(env_dir: str | None = None) -> dict[str, AgentPreset]:
    """Search for preset files in configured and default directories.

    Precedence: env_dir (if set) first, then DEFAULT_PRESETS_DIRS.
    Later directories do not override earlier names.
    """
    out: dict[str, AgentPreset] = {}
    roots: list[Path] = []
    if env_dir:
        roots.append(Path(env_dir))
    # Resolve only via platformdirs: user_config_dir('adgn') / 'presets'
    roots.append(_xdg_presets_dir())
    for r in roots:
        for name, preset in load_presets_from_dir(r).items():
            if name not in out:
                out[name] = preset
    # Always include a built-in default if none present
    if "default" not in out:
        out["default"] = AgentPreset(name="default", description="Default UI agent", system=None, specs={})
    return out
