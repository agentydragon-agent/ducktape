"""Per-session state and lifecycle for the hook daemon."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from devinfra.claude.auth_proxy.proxy import AuthForwardingProxy, UdsRemoteProxy, UpstreamCreds
from devinfra.claude.auth_proxy.vars import get_upstream_proxy_url
from devinfra.claude.hook_config import HookConfig
from devinfra.claude.hook_daemon.session_start import precommit
from devinfra.claude.session_paths import SessionPaths
from devinfra.claude.settings import HookSettings, ProxyMode

logger = logging.getLogger(__name__)


# TODO: persist mailbox to disk so messages survive daemon restarts.


@dataclass
class Session:
    """Per-session state: identity, paths, proxy handles, and background tasks."""

    session_id: str
    paths: SessionPaths
    proxy: AuthForwardingProxy | None = None
    uds_remote: UdsRemoteProxy | None = None  # Bazel --remote_proxy
    uds_bes: UdsRemoteProxy | None = None  # Bazel --bes_proxy
    _upstream_creds: UpstreamCreds = field(default_factory=UpstreamCreds)
    _background: set[asyncio.Task[object]] = field(default_factory=set)
    _mailbox: list[str] = field(default_factory=list)

    def track(self, task: asyncio.Task[object]) -> None:
        """Hold a strong reference to task; release it when done."""
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    def post_message(self, message: str) -> None:
        """Post a notification message to the mailbox."""
        self._mailbox.append(message)

    def drain_messages(self) -> list[str]:
        """Return and clear all pending mailbox messages."""
        messages = list(self._mailbox)
        self._mailbox.clear()
        return messages

    def register_precommit_install(self, task: asyncio.Task[precommit.PrecommitHooksResult]) -> None:
        """Register install-hooks task: track it and post status on completion."""

        def _on_done(t: asyncio.Task[precommit.PrecommitHooksResult]) -> None:
            if t.cancelled():
                return
            match t.result():
                case precommit.PrecommitHooksInstalled():
                    self.post_message("pre-commit install-hooks completed successfully. Hook environments are ready.")
                case precommit.PrecommitHooksFailed(error=e):
                    self.post_message(
                        f"pre-commit install-hooks failed: {e}. Run `pre-commit install-hooks` manually to retry."
                    )

        task.add_done_callback(_on_done)
        self.track(task)

    def register_bazel_warmup(self, task: asyncio.Task[None]) -> None:
        """Register bazel warmup task: track it and post status on completion."""

        def _on_done(t: asyncio.Task[None]) -> None:
            if t.cancelled():
                return
            exc = t.exception()
            if exc is not None:
                self.post_message(f"Bazel server warmup failed: {exc}")
            else:
                self.post_message("Bazel server is warm.")

        task.add_done_callback(_on_done)
        self.track(task)

    def register_background_bazel_command(self, task: asyncio.Task[None], pid: int, command: str) -> None:
        """Register a background bazel command: post PID for cancellation, track completion."""
        self.post_message(f"Background `bazel {command}` started (PID {pid}). To cancel, run: `kill {pid}`")

        def _on_done(t: asyncio.Task[None]) -> None:
            if t.cancelled():
                return
            exc = t.exception()
            if exc is not None:
                self.post_message(f"Background `bazel {command}` failed: {exc}")
            else:
                self.post_message(f"Background `bazel {command}` completed.")

        task.add_done_callback(_on_done)
        self.track(task)

    async def start_proxy(self, web_mode: bool, hook_config: HookConfig, settings: HookSettings) -> None:
        """Start proxy infrastructure for this session."""
        profile = hook_config.profile(web_mode)
        upstream_url = get_upstream_proxy_url()

        self._upstream_creds.set(upstream_url)

        # CLEANUP(2026-03-26): Remove TCP proxy once UDS mode is confirmed stable.
        if settings.proxy_mode == ProxyMode.TCP:
            self.proxy = AuthForwardingProxy(listen_port=0, creds=self._upstream_creds)
            self.proxy.start()
            logger.info("Auth proxy started in-process on port %d (tcp mode)", self.proxy.listen_port)

        if profile.bazel_remote_proxy is not None:
            self.uds_remote = UdsRemoteProxy(
                sock_path=self.paths.bazel_remote_proxy_sock,
                remote_target=profile.bazel_remote_proxy.target,
                creds=self._upstream_creds,
            )
            self.uds_remote.start()

        if profile.bazel_bes_proxy is not None:
            self.uds_bes = UdsRemoteProxy(
                sock_path=self.paths.bazel_bes_proxy_sock,
                remote_target=profile.bazel_bes_proxy.target,
                creds=self._upstream_creds,
            )
            self.uds_bes.start()

    def stop(self) -> None:
        """Stop all proxy infrastructure for this session."""
        for proxy in [self.proxy, self.uds_remote, self.uds_bes]:
            if proxy is not None:
                proxy.stop()

    def set_proxy_creds(self, https_proxy: str) -> None:
        self._upstream_creds.set(https_proxy)
