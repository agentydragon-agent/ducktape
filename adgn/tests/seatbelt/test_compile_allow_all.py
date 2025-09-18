from adgn.seatbelt.compile import compile_sbpl
from adgn.seatbelt.model import (
    FileRule,
    MachLookupRule,
    NetworkRule,
    PathFilter,
    ProcessRule,
    SBPLPolicy,
    SystemRule,
    TraceConfig,
)


def test_compile_allow_all_effectively_no_sandbox():
    policy = SBPLPolicy(
        default_behavior="allow",
        process=ProcessRule(allow_process_star=True, allow_signal_self=True),
        files=[
            FileRule(op="file-read*", filters=[PathFilter(kind="subpath", value="/")]),
            FileRule(op="file-write*", filters=[PathFilter(kind="subpath", value="/")]),
            FileRule(op="file-map-executable", filters=[]),
        ],
        network=[
            NetworkRule(op="network-inbound", local_only=False),
            NetworkRule(op="network-outbound", local_only=False),
            NetworkRule(op="network-bind", local_only=False),
        ],
        mach=MachLookupRule(global_names=[]),
        system=SystemRule(system_socket=True, sysctl_read=True),
        trace=TraceConfig(enabled=False),
    )

    sb = compile_sbpl(policy)

    # Core header & defaults
    assert "(version 1)" in sb
    assert "(allow default)" in sb

    # Process primitives
    assert "(allow process*)" in sb
    assert "(allow signal (target self))" in sb

    # FS broad rules
    assert '(allow file-read* (subpath "/"))' in sb
    assert '(allow file-write* (subpath "/"))' in sb
    assert "(allow file-map-executable)" in sb

    # Network wide open
    assert "(allow network-inbound)" in sb
    assert "(allow network-outbound)" in sb
    assert "(allow network-bind)" in sb

    # System toggles
    assert "(allow system-socket)" in sb
    assert "(allow sysctl-read)" in sb

    # Sanity: should not contain any deny lines in this configuration
    assert "(deny" not in sb
