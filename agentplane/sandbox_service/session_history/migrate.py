"""Migrate the Sandbox Service's independent Session Event history database.

Run from the history migration image, never as an init container of the inventory
service: history database availability must not gate existing lifecycle RPCs.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict

from agentplane.sandbox_service.session_history.database_migrate import RUNNER


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AGENTPLANE_SANDBOX_SERVICE_HISTORY_")
    database_url: str


def main() -> None:
    RUNNER.apply(Settings().database_url)


if __name__ == "__main__":
    main()
