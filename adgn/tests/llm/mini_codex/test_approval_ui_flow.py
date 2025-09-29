"""Test that approval prompts auto-appear in UI without refresh."""

import asyncio
from concurrent.futures import CancelledError

from fastapi.testclient import TestClient
import pytest

from adgn.llm.mini_codex.agent import MiniCodex
from adgn.llm.mini_codex.approvals import ApprovalPolicyEngine, ApprovalHub
from adgn.llm.mini_codex.mcp_manager import McpManager
from adgn.llm.mini_codex.ui import protocol
from adgn.llm.mini_codex.ui.server import create_app
from adgn.llm.mini_codex.ui.shared_bus import UiBus
from adgn.llm.mini_codex.ui.ui_handler import UiModeHandler
from adgn.llm.mcp.inproc_transport import make_inproc_slot_spec
from adgn.llm.mcp.ui.server import make_ui_mcp
from tests.llm.support.openai_mock import make_mock

Envelope = protocol.Envelope


class DummyClient:
    @property
    def responses(self):
        raise AssertionError("responses.create should not be called directly in this test")


@pytest.mark.timeout(10)
def test_approval_prompt_auto_appears(
    responses_factory,
    make_echo_spec,
) -> None:
    """Test that approval prompts appear immediately in UI without manual refresh."""

    state = {"step": 0}

    async def responses_create(_req):
        step = state["step"]
        state["step"] += 1
        if step == 0:
            # Agent tries to call echo tool - should trigger approval prompt
            return responses_factory.make_tool_call(
                "mcp__echo__echo", {"text": "hello"}, call_id="call_echo"
            )
        # After approval, agent should end turn
        return responses_factory.make_tool_call(
            "mcp__ui__end_turn", {}, call_id="call_ui_end"
        )

    client = make_mock(responses_create)
    bus = UiBus()

    # Set up approval system - this should cause echo tool to require approval
    approval_engine = ApprovalPolicyEngine()  # Uses default policy that asks for approval
    approval_hub = ApprovalHub()

    specs = make_echo_spec()
    specs["ui"] = make_inproc_slot_spec(make_ui_mcp("ui", bus))

    async def _run_test():
        async with McpManager(specs) as mcp_mgr:
            agent = await MiniCodex.create(
                model="test-model",
                mcp=mcp_mgr,
                system="You are a test agent.",
                client=client,
                handlers=[UiModeHandler(bus=bus, poll_notifications=mcp_mgr.poll_notifications)],
                parallel_tool_calls=False,
                # Enable approval system
                approval_engine=approval_engine,
                approval_hub=approval_hub,
            )
            return agent

    agent = asyncio.run(_run_test())

    app = create_app(require_static_assets=False)
    app.state.ui_bus = bus
    app.state.approval_engine = approval_engine
    app.state.approval_hub = approval_hub

    try:
        with TestClient(app) as client_ws:
            app.state.session.attach_agent(agent)

            with client_ws.websocket_connect("/ws") as ws:
                ws.send_json({"type": "send", "text": "use echo tool to say hello"})

                # Wait for accepted
                for _ in range(20):
                    env = Envelope.model_validate(ws.receive_json())
                    if env.payload.type == "accepted":
                        break
                else:
                    raise AssertionError("accepted not received")

                # Look for approval_pending event - this should appear immediately
                saw_approval_pending = False
                approval_call_id = None
                saw_finished = False

                for _ in range(50):  # Give more iterations for the approval flow
                    payload = Envelope.model_validate(ws.receive_json()).payload

                    if payload.type == "approval_pending":
                        saw_approval_pending = True
                        approval_call_id = payload.call_id
                        print(f"✅ Approval prompt appeared automatically! call_id={approval_call_id}")

                        # Approve the tool call
                        ws.send_json({"type": "approve", "call_id": approval_call_id})
                        continue

                    if payload.type == "approval_decision":
                        print(f"✅ Approval decision processed: {payload.decision}")
                        continue

                    if payload.type == "function_call_output":
                        print(f"✅ Tool executed: call_id={payload.call_id}")
                        continue

                    if (
                        payload.type == "run_status"
                        and payload.run_state.status == "finished"
                    ):
                        saw_finished = True
                        break

                # Verify the approval flow worked
                assert saw_approval_pending, "❌ Approval prompt did not appear automatically"
                assert approval_call_id is not None, "❌ No approval call_id received"
                assert saw_finished, "❌ Run did not finish successfully"

                print("🎉 Success: Approval prompts now auto-appear without refresh!")

    except CancelledError:
        pass


if __name__ == "__main__":
    # Allow running this test directly
    import sys
    sys.exit(pytest.main([__file__, "-v"]))