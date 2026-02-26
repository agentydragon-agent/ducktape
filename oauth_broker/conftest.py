"""pytest-asyncio auto mode for oauth_broker tests."""


def pytest_configure(config):
    config.option.asyncio_mode = "auto"
