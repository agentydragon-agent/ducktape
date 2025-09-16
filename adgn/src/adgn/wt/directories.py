from pathlib import Path

from platformdirs import user_data_dir, user_log_dir


class Directories:
    def __init__(self, app_name: str = "adgn-worktree"):
        self.app_name = app_name
        self._log_dir = Path(user_log_dir(app_name))
        self._data_dir = Path(user_data_dir(app_name))

    def init_dirs(self) -> None:
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._data_dir.mkdir(parents=True, exist_ok=True)

    @property
    def log_dir(self) -> Path:
        return self._log_dir

    @property
    def data_dir(self) -> Path:
        return self._data_dir

    @property
    def pr_cache_file(self) -> Path:
        return self._data_dir / "pr_cache.json"

    @property
    def operations_log_file(self) -> Path:
        return self._log_dir / "operations.jsonl"


# Global instance
directories = Directories()
