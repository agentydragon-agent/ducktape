local I = import '../../lib.libsonnet';


I.issueMulti(
  rationale= |||
    Creating typed server stubs requires verbose boilerplate (infrastructure.py:180-186):

    reader_client = Client(reader_server)
    await stack.enter_async_context(reader_client)
    policy_reader = PolicyReaderStub(TypedClient(reader_client))

    approver_client = Client(approver_server)
    await stack.enter_async_context(approver_client)
    policy_approver = PolicyApproverStub(TypedClient(approver_client))

    This 3-line pattern repeats for every stub. Should provide convenience method:

    policy_reader = await PolicyReaderStub.for_server(stack, reader_server)
    policy_approver = await PolicyApproverStub.for_server(stack, approver_server)

    Or even simpler with context manager protocol on stub class.

    The for_server method would encapsulate:
    1. Create Client from server
    2. Enter into async context stack
    3. Wrap in TypedClient
    4. Return stub instance

    Benefits:
    - DRY: pattern in one place
    - Less error-prone: can't forget context manager entry
    - Clearer intent: "create stub from server"
    - Reduces line count 3:1

    This suggests base class method or helper function in server stub framework.
  |||,

  occurrences=[
    {
      files: {
        'adgn/src/adgn/agent/runtime/infrastructure.py': [[180, 182]],
      },
      note: 'PolicyReaderStub creation boilerplate',
      expect_caught_from: [['adgn/src/adgn/agent/runtime/infrastructure.py']],
    },
    {
      files: {
        'adgn/src/adgn/agent/runtime/infrastructure.py': [[184, 186]],
      },
      note: 'PolicyApproverStub creation boilerplate',
      expect_caught_from: [['adgn/src/adgn/agent/runtime/infrastructure.py']],
    },
  ],
)
