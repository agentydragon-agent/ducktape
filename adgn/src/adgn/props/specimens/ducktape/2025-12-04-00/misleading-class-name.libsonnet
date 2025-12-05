local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Class named ConnectionManager but extends BaseHandler and primarily handles agent events, not connections. The name obscures its role as an event handler, making the architecture harder to understand when skimming code.

    The class manages message delivery and event handling for the agent session, not connection lifecycle. A name like MessageDeliveryHandler or UiEventHandler would better reflect its actual purpose.
  |||,
  filesToRanges={'adgn/src/adgn/agent/server/runtime.py': [38]},
)
