from __future__ import annotations

from pathlib import Path

import os

from jupyter_mcp_stdio_guard.sandboxer import Policy, EnvConfig, FSConfig, NetConfig, PlatformConfig, SeatbeltPlatform
from jupyter_mcp_stdio_guard.sandboxer import _compose_seatbelt  # type: ignore[attr-defined]


def _mk_policy(**kwargs) -> Policy:
    # Helper to quickly build a Policy with defaults overrideable via kwargs
    p = Policy()
    for k, v in kwargs.items():
        setattr(p, k, v)
    return p


def test_net_mode_none_denies_all_network():
    pol = _mk_policy(net=NetConfig(mode="none"))
    sb, defs = _compose_seatbelt(pol, trace_path=None)
    assert "(allow network-inbound" not in sb
    assert "(allow network-outbound" not in sb
    assert defs == {}


def test_net_mode_loopback_allows_only_local_in_and_out():
    pol = _mk_policy(net=NetConfig(mode="loopback"))
    sb, _ = _compose_seatbelt(pol, trace_path=None)
    # Allows only local inbound and outbound
    assert "(allow network-inbound (local ip))" in sb
    assert "(allow network-outbound (local ip))" in sb
    # No blanket network rules should appear
    assert "(allow network-inbound)" not in sb
    assert "(allow network-outbound)" not in sb


def test_net_mode_open_allows_in_and_out():
    pol = _mk_policy(net=NetConfig(mode="open"))
    sb, _ = _compose_seatbelt(pol, trace_path=None)
    assert "(allow network-inbound)" in sb
    assert "(allow network-outbound)" in sb


def test_trace_included_when_trace_path_or_platform_trace():
    # When trace_path is provided, it must be included
    pol = _mk_policy()
    sb, _ = _compose_seatbelt(pol, trace_path="/tmp/seatbelt.trace.log")
    assert "(trace \"/tmp/seatbelt.trace.log\")" in sb

    # When seatbelt.trace True, include (trace "<trace>") even if None provided (placeholder)
    pol2 = _mk_policy(platform=PlatformConfig(seatbelt=SeatbeltPlatform(trace=True)))
    sb2, _ = _compose_seatbelt(pol2, trace_path=None)
    assert "(trace \"" in sb2  # placeholder path rendered by composer


def test_fs_write_paths_expand_to_params_and_dirs(tmp_path):
    # Provide file and dir write_paths → composer should allow the parent dirs under WP_* params
    file_path = tmp_path / "sub" / "file.txt"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text("x")
    dir_path = tmp_path / "dir"
    dir_path.mkdir(parents=True, exist_ok=True)

    pol = _mk_policy(fs=FSConfig(write_paths=[str(file_path), str(dir_path)]))
    sb, defs = _compose_seatbelt(pol, trace_path=None)

    # Expect WP_0, WP_1 params mapping to absolute dirs
    assert any("(param \"WP_0\")" in line for line in sb.splitlines())
    assert any("(param \"WP_1\")" in line for line in sb.splitlines())
    assert defs["WP_0"].startswith(str(tmp_path)) and Path(defs["WP_0"]).is_absolute()
    assert defs["WP_1"].startswith(str(tmp_path)) and Path(defs["WP_1"]).is_absolute()


def test_fs_read_paths_expand_to_params_and_dirs(tmp_path):
    # Provide file and dir read_paths → composer should allow parent dirs under RP_* params
    f = tmp_path / "bin" / "python"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("#!python\n")
    d = tmp_path / "lib"
    d.mkdir(parents=True, exist_ok=True)

    pol = _mk_policy(fs=FSConfig(read_paths=[str(f), str(d)]))
    sb, defs = _compose_seatbelt(pol, trace_path=None)

    assert any("(param \"RP_0\")" in line for line in sb.splitlines())
    assert any("(param \"RP_1\")" in line for line in sb.splitlines())
    assert defs["RP_0"].startswith(str(tmp_path)) and Path(defs["RP_0"]).is_absolute()
    assert defs["RP_1"].startswith(str(tmp_path)) and Path(defs["RP_1"]).is_absolute()


def test_platform_extra_file_read_extra_is_respected(tmp_path):
    extra_dir = tmp_path / "fonts"
    extra_dir.mkdir(parents=True, exist_ok=True)
    pol = _mk_policy(
        platform=PlatformConfig(
            seatbelt=SeatbeltPlatform(extra_allow=SeatbeltPlatform().extra_allow.__class__(file_read_extra=[str(extra_dir)]))
        )
    )
    sb, _ = _compose_seatbelt(pol, trace_path=None)
    assert f"(allow file-read* (subpath \"{extra_dir}\") )" in sb
