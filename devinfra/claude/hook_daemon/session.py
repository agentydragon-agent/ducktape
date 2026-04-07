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
    _precommit_hooks_task: asyncio.Task[precommit.PrecommitHooksResult] | None = None

    def track(self, task: asyncio.Task[object]) -> None:
        """Hold a strong reference to task; release it when done."""
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    def register_precommit_install(self, task: asyncio.Task[precommit.PrecommitHooksResult]) -> None:
        """Register install-hooks task and keep it alive."""
        self._precommit_hooks_task = task
        self.track(task)

    def take_precommit_status(self) -> str | None:
        """Non-blocking: return and clear status message if task is done, else None."""
        task = self._precommit_hooks_task
        if task is None or not task.done():
            return None
        self._precommit_hooks_task = None
        if task.cancelled():
            return None
        match task.result():
            case precommit.PrecommitHooksInstalled():
                return "pre-commit install-hooks completed successfully. Hook environments are ready."
            case precommit.PrecommitHooksFailed(error=e):
                return f"pre-commit install-hooks failed: {e}. Run `pre-commit install-hooks` manually to retry."

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
