local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Pinned server tracking uses a separate set _pinned_servers instead of storing the flag in _MountState.
    This splits mount state across two data structures, making it harder to reason about mount lifecycle.
    The pinned flag should be a boolean field in _MountState (e.g., pinned: bool = False).
    This centralizes all mount state in one place and eliminates the need to keep _pinned_servers synchronized.
  |||,
  filesToRanges={
    'adgn/src/adgn/mcp/compositor/server.py': [
      89,  // _pinned_servers field declaration
      [306, 307],  // pinned check in mount_inproc
      314,  // pinned check in unmount_server
    ],
  },
)
