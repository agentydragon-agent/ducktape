from pathlib import Path

import tomllib
from pydantic import BaseModel
from platformdirs import user_config_dir

CONFIG_DIR = Path(user_config_dir("aiquota"))
DEFAULT_CONFIG_PATH = CONFIG_DIR / "config.toml"


class ProviderSettings(BaseModel):
    enabled: bool = True
    api_key_path: str | None = None


class ConfigFile(BaseModel):
    providers: dict[str, ProviderSettings] = {}


def load(path: Path | None = None) -> ConfigFile:
    p = path or DEFAULT_CONFIG_PATH
    try:
        raw = p.read_text()
    except OSError:
        return ConfigFile()
    try:
        data = tomllib.loads(raw)
    except tomllib.TOMLDecodeError:
        return ConfigFile()
    return ConfigFile.model_validate(data)
