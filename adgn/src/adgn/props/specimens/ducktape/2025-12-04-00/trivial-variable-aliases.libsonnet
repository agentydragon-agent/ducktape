local I = import '../../lib.libsonnet';

I.issueMulti(
  rationale= |||
    Three event handler methods in `UiEventHandler` create trivial single-use variables that should be inlined directly into the function call:

    **Lines 85-86** (`on_user_text_event`): Variable `ut` is assigned `UiUserText(text=evt.text)` and immediately passed to `self._spawn(self._send_and_reduce(ut))`. Inline to: `self._spawn(self._send_and_reduce(UiUserText(text=evt.text)))`.

    **Lines 92-93** (`on_tool_call_event`): Variable `tc` is assigned `UiToolCall(name=evt.name, args_json=evt.args_json, call_id=evt.call_id)` and immediately passed to `self._spawn(self._send_and_reduce(tc))`. Inline to: `self._spawn(self._send_and_reduce(UiToolCall(name=evt.name, args_json=evt.args_json, call_id=evt.call_id)))`.

    **Lines 100-101** (`on_tool_result_event`): Variable `fco` is assigned `FunctionCallOutput(call_id=evt.call_id, result=evt.result)` and immediately passed to `self._spawn(self._send_and_reduce(fco))`. Inline to: `self._spawn(self._send_and_reduce(FunctionCallOutput(call_id=evt.call_id, result=evt.result)))`.

    These single-use aliases add no clarity - the constructor calls are self-documenting. Inlining removes unnecessary intermediate variables without sacrificing readability.
  |||,
  occurrences=[
    {
      files: {'adgn/src/adgn/agent/server/runtime.py': [[85, 86]]},
      note: 'on_user_text_event: ut variable should be inlined',
      expect_caught_from: [['adgn/src/adgn/agent/server/runtime.py']],
    },
    {
      files: {'adgn/src/adgn/agent/server/runtime.py': [[92, 93]]},
      note: 'on_tool_call_event: tc variable should be inlined',
      expect_caught_from: [['adgn/src/adgn/agent/server/runtime.py']],
    },
    {
      files: {'adgn/src/adgn/agent/server/runtime.py': [[100, 101]]},
      note: 'on_tool_result_event: fco variable should be inlined',
      expect_caught_from: [['adgn/src/adgn/agent/server/runtime.py']],
    },
  ],
)
