"""pytest-asyncio auto mode for airlock.oauth tests."""


def pytest_configure(config):
    config.option.asyncio_mode = "auto"
