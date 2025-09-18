"""
SBPL (macOS Seatbelt) typed policy models.

Layering contract:
- Pure data only. No implicit defaults beyond field defaults.
- No platform probing, path injection, or mutation helpers here.
- Compiler/validator/runner live in sibling modules.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PathFilter(BaseModel):
    """
    Path filter for file operations.

    kind:
      - "literal": (literal "/abs/path")
      - "subpath": (subpath "/abs/dir")
    value: absolute path string; caller is responsible for correctness.
    """

    kind: Literal["literal", "subpath"]
    value: str

    model_config = ConfigDict(extra="forbid")


class FileRule(BaseModel):
    """
    File operation rule. Each filter produces a separate SBPL clause.

    Example SBPL render for allow+file-read*+subpath("/usr/lib"):
      (allow file-read* (subpath "/usr/lib"))
    """

    action: Literal["allow", "deny"] = "allow"
    op: Literal[
        "file-read*",
        "file-write*",
        "file-read-metadata",
        "file-map-executable",
    ]
    filters: list[PathFilter] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class MachLookupRule(BaseModel):
    """
    Mach lookup permissions by global service names.

    action applies to all names in the list.
    """

    action: Literal["allow", "deny"] = "allow"
    global_names: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class NetworkRule(BaseModel):
    """
    Network permission rule.

    local_only=True renders the (local ip) predicate.
    """

    action: Literal["allow", "deny"] = "allow"
    op: Literal["network-inbound", "network-outbound", "network-bind"]
    local_only: bool = False

    model_config = ConfigDict(extra="forbid")


class SystemRule(BaseModel):
    """
    System-level toggles. True => emit an allow clause in compiler.
    """

    system_socket: bool = False
    sysctl_read: bool = False

    model_config = ConfigDict(extra="forbid")


class ProcessRule(BaseModel):
    """
    Process/signal primitives.
    """

    allow_process_star: bool = True
    allow_signal_self: bool = True

    model_config = ConfigDict(extra="forbid")


class TraceConfig(BaseModel):
    """
    Seatbelt trace configuration.

    If enabled and path is provided, compiler will emit (trace "<path>").
    """

    enabled: bool = False
    path: str | None = None

    model_config = ConfigDict(extra="forbid")


class SBPLPolicy(BaseModel):
    """
    Top-level SBPL policy model (useful subset).

    default_behavior controls the header (allow/deny default).
    Lists preserve caller-provided order.
    """

    version: int = 1
    default_behavior: Literal["deny", "allow"] = "deny"

    process: ProcessRule = Field(default_factory=ProcessRule)
    files: list[FileRule] = Field(default_factory=list)
    network: list[NetworkRule] = Field(default_factory=list)
    mach: MachLookupRule = Field(default_factory=MachLookupRule)
    system: SystemRule = Field(default_factory=SystemRule)
    trace: TraceConfig = Field(default_factory=TraceConfig)

    model_config = ConfigDict(extra="forbid")
