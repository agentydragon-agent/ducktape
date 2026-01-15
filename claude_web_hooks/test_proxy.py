"""Tests for claude_web_hooks.proxy module."""

from __future__ import annotations

import base64
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import pytest

import claude_web_hooks.proxy as proxy_module
from claude_web_hooks.proxy import kill_existing, load_credentials, make_auth_header, parse_proxy_url, write_credentials


class TestParseProxyUrl:
    """Tests for parse_proxy_url()."""

    def test_simple_url(self) -> None:
        result = parse_proxy_url("http://proxy.example.com:8080")
        assert result.hostname == "proxy.example.com"
        assert result.port == 8080
        assert result.username is None
        assert result.password is None

    def test_url_with_credentials(self) -> None:
        result = parse_proxy_url("http://user:pass@proxy.example.com:8080")
        assert result.hostname == "proxy.example.com"
        assert result.port == 8080
        assert result.username == "user"
        assert result.password == "pass"

    def test_url_with_complex_password(self) -> None:
        # JWT tokens contain special chars
        result = parse_proxy_url("http://container:jwt_eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ0ZXN0In0.abc@proxy:15004")
        assert result.hostname == "proxy"
        assert result.port == 15004
        assert result.username == "container"
        assert result.password == "jwt_eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ0ZXN0In0.abc"

    def test_invalid_url_raises(self) -> None:
        with pytest.raises(ValueError, match="Could not parse host"):
            parse_proxy_url("not-a-url")


class TestMakeAuthHeader:
    """Tests for make_auth_header()."""

    def test_no_credentials(self) -> None:
        proxy = urlparse("http://proxy.example.com:8080")
        assert make_auth_header(proxy) == ""

    def test_with_credentials(self) -> None:
        proxy = urlparse("http://user:pass@proxy.example.com:8080")
        header = make_auth_header(proxy)
        assert header.startswith("Proxy-Authorization: Basic ")
        assert header.endswith("\r\n")
        # Verify encoding
        encoded = header.split(" ")[2].rstrip()
        decoded = base64.b64decode(encoded).decode()
        assert decoded == "user:pass"

    def test_username_only(self) -> None:
        proxy = urlparse("http://user@proxy.example.com:8080")
        header = make_auth_header(proxy)
        encoded = header.split(" ")[2].rstrip()
        decoded = base64.b64decode(encoded).decode()
        assert decoded == "user:"


class TestKillExisting:
    """Tests for kill_existing()."""

    def test_no_pidfile(self, tmp_path: Path) -> None:
        pid_file = tmp_path / "nonexistent.pid"
        assert kill_existing(pid_file) is False

    def test_stale_pidfile(self, tmp_path: Path) -> None:
        pid_file = tmp_path / "stale.pid"
        pid_file.write_text("99999999")  # Non-existent PID
        assert kill_existing(pid_file) is False
        assert not pid_file.exists()  # Should clean up stale pidfile

    def test_invalid_pidfile(self, tmp_path: Path) -> None:
        pid_file = tmp_path / "invalid.pid"
        pid_file.write_text("not-a-number")
        assert kill_existing(pid_file) is False
        assert not pid_file.exists()

    def test_kills_running_process(self, tmp_path: Path) -> None:
        # Start a sleep process
        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        pid_file = tmp_path / "running.pid"
        pid_file.write_text(str(proc.pid))

        assert kill_existing(pid_file) is True
        assert not pid_file.exists()

        # Wait for process to die (SIGKILL is async)
        proc.wait(timeout=5)


class TestLoadCredentials:
    """Tests for load_credentials()."""

    cache: proxy_module.CredentialCache

    def setup_method(self) -> None:
        # Create fresh cache for each test
        self.cache = proxy_module.CredentialCache()

    def test_loads_credentials_from_file(self, tmp_path: Path) -> None:
        write_credentials(tmp_path, "http://user:pass@proxy:8080")
        proxy, auth_header = load_credentials(tmp_path, self.cache)
        assert proxy.hostname == "proxy"
        assert proxy.port == 8080
        assert proxy.username == "user"
        assert "Basic" in auth_header

    def test_raises_when_file_missing(self, tmp_path: Path) -> None:
        with pytest.raises(RuntimeError, match="Credentials file not found"):
            load_credentials(tmp_path, self.cache)

    def test_raises_when_file_empty(self, tmp_path: Path) -> None:
        (tmp_path / "upstream_proxy").write_text("")
        with pytest.raises(RuntimeError, match="Credentials file is empty"):
            load_credentials(tmp_path, self.cache)

    def test_caches_until_file_changes(self, tmp_path: Path) -> None:
        write_credentials(tmp_path, "http://user:pass@proxy:8080")

        # First load
        proxy1, _ = load_credentials(tmp_path, self.cache)
        assert proxy1.hostname == "proxy"

        # Second load should return cached (even if we modify in memory)
        proxy2, _ = load_credentials(tmp_path, self.cache)
        assert proxy2 is proxy1  # Same object from cache

    def test_reloads_when_file_modified(self, tmp_path: Path) -> None:
        write_credentials(tmp_path, "http://old@proxy:8080")
        proxy1, _ = load_credentials(tmp_path, self.cache)
        assert proxy1.username == "old"

        # Wait a bit to ensure mtime changes
        time.sleep(0.1)

        # Write new credentials
        write_credentials(tmp_path, "http://new@proxy:8080")
        proxy2, _ = load_credentials(tmp_path, self.cache)
        assert proxy2.username == "new"
        assert proxy2 is not proxy1  # New object (cache invalidated)
