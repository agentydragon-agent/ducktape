from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from platformdirs import user_cache_dir

from aiquota.models import AllQuotas

CACHE_DIR = Path(user_cache_dir("aiquota"))
CACHE_PATH = CACHE_DIR / "quotas.json"
CACHE_TTL = timedelta(seconds=120)


def read(path: Path = CACHE_PATH) -> AllQuotas | None:
    try:
        return AllQuotas.model_validate_json(path.read_text())
    except (OSError, ValueError):
        return None


def write(quotas: AllQuotas, path: Path = CACHE_PATH) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(quotas.model_dump_json())
    except OSError:
        pass


def get_or_fetch(
    fetch_fn: Callable[[], AllQuotas],
    cache_path: Path = CACHE_PATH,
    ttl: timedelta = CACHE_TTL,
) -> AllQuotas:
    cached = read(cache_path)
    if cached is not None and datetime.now(UTC) - cached.fetched_at < ttl:
        return cached
    try:
        fresh = fetch_fn()
    except Exception:
        return cached if cached is not None else AllQuotas(providers=[], fetched_at=datetime.now(UTC))
    write(fresh, cache_path)
    return fresh
