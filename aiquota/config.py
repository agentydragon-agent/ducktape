import tomllib
from pathlib import Path

from platformdirs import user_config_dir
from pydantic import BaseModel

CONFIG_DIR = Path(user_config_dir("aiquota"))
DEFAULT_CONFIG_PATH = CONFIG_DIR / "config.toml"


class ProviderSettings(BaseModel):
    enabled: bool = True
    api_key_path: str | None = None


class ConfigFile(BaseModel):
    providers: dict[str, ProviderSettings] = {}


def load(path: Path) -> ConfigFile:
    try:
        raw = path.read_text()
    except OSError:
        return ConfigFile()
    try:
        data = tomllib.loads(raw)
    except tomllib.TOMLDecodeError:
        return ConfigFile()
    return ConfigFile.model_validate(data)
