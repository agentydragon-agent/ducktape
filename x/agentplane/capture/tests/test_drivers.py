from x.agentplane.capture.providers.claude import driver as claude
from x.agentplane.capture.providers.codex import driver as codex
from x.agentplane.capture.scenarios import PROVIDERS, SCENARIOS


def test_matrix_has_both_providers_for_each_required_scenario() -> None:
    assert set(PROVIDERS) == {"claude", "codex"}
    assert {
        "launch_handshake",
        "normal_submit_while_active",
        "dequeue_pending_input",
        "kill_active_reconcile_resume",
    } <= set(SCENARIOS)


def test_claude_native_frames_remain_explicit() -> None:
    assert claude.initialize()["request"]["subtype"] == "initialize"
    assert claude.user_frame("hello", message_uuid="u-1")["uuid"] == "u-1"
    assert claude.interrupt(cancel_queued=True)["request"]["cancel_queued"] is True


def test_codex_native_frames_remain_explicit() -> None:
    started = codex.thread_start("1", cwd="/workspace", model="cheap", effort="low")
    assert started["method"] == "thread/start"
    assert started["params"]["ephemeral"] is False
    assert codex.turn_start("2", thread_id="t", text="hello")["method"] == "turn/start"
    assert codex.steer("3", thread_id="t", turn_id="r", text="stop")["method"] == "turn/steer"


if __name__ == "__main__":
    import pytest_bazel

    pytest_bazel.main()
