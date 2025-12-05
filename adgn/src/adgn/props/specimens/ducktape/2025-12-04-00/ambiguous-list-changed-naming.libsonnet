local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    The naming "list_changed" is ambiguous - it could refer to any list changing.
    These handlers specifically react to resource list changes on mounted servers (MCP resources/list_changed notifications).
    The semantic meaning is that the list of *resources* on a server changed, not some generic "list".
    All references should use explicit "resource_list_changed" naming to clarify this contract.
    This affects field names (_list_changed_listeners, _pending_list_changed), method names (add_list_changed_listener, _notify_list_changed, pop_recent_list_changed), and the comment at line 82.
  |||,
  filesToRanges={
    'adgn/src/adgn/mcp/compositor/server.py': [
      [82, 84],  // comment and field declaration
      109,  // add_list_changed_listener method
      116,  // _notify_list_changed method
      142,  // on_resource_list_changed handler
      143,  // _pending_list_changed.add call
      145,  // _notify_list_changed call
      [151, 154],  // pop_recent_list_changed method
    ],
  },
)
