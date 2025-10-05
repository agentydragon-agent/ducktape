from __future__ import annotations

from pathlib import Path
from typing import Any

from platformdirs import user_config_dir
from pydantic import BaseModel, Field
import yaml

from adgn.agent.runtime.spec_utils import rehydrate_mcp_specs
from adgn.agent.runtime.specs import McpServerSpec


def _xdg_presets_dir() -> Path:
    """Return the default XDG-compliant presets directory.

    Uses platformdirs to resolve the user configuration directory for app "adgn",
    then appends the "presets" subfolder.
    """
    cfg_root = Path(user_config_dir("adgn"))
    return cfg_root / "presets"


class AgentPreset(BaseModel):
    name: str
    description: str | None = None
    system: str | None = None
    specs: dict[str, Any] = Field(default_factory=dict)
    approval_policy: str | None = None

    def typed_specs(self) -> dict[str, McpServerSpec]:
        return rehydrate_mcp_specs(self.specs)


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"preset must be a mapping: {path}")
    return data


def load_presets_from_dir(root: Path) -> dict[str, AgentPreset]:
    out: dict[str, AgentPreset] = {}
    if not root.exists() or not root.is_dir():
        return out
    for p in sorted(root.glob("*.y*ml")):
        data = _load_yaml(p)
        name = str(data.get("name") or p.stem)
        preset = AgentPreset(
            name=name,
            description=data.get("description"),
            system=data.get("system"),
            specs=data.get("specs") or {},
            approval_policy=data.get("approval_policy") or data.get("policy") or None,
        )
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
        out["default"] = AgentPreset(
            name="default", description="Default UI agent", system=None, specs={}
        )
    return out
