import asyncio

from fastmcp.client import Client as McpClient
from fastmcp.client.messages import MessageHandler
from mcp import types as mcp_types
import pytest

from adgn.mcp.chat.server import (
    ChatAuthor,
    ChatStore,
    PostInput,
    ReadPendingInput,
    make_chat_server,
)
from adgn.mcp.testing.typed_stubs import TypedClient


@pytest.mark.asyncio
async def test_chat_flow_user_to_agent_then_agent_to_user() -> None:
    # Build shared store and two in-proc servers
    store = ChatStore()
    human = make_chat_server(name="chat.human", author=ChatAuthor.USER, store=store)
    assistant = make_chat_server(name="chat.assistant", author=ChatAuthor.ASSISTANT, store=store)
    store.register_servers(human=human, assistant=assistant)

    async with McpClient(human) as human_sess, McpClient(assistant) as assistant_sess:
        h = TypedClient.from_server(human, human_sess)
        a = TypedClient.from_server(assistant, assistant_sess)

        # Initially, assistant has nothing pending
        page0 = await a.read_pending_messages(ReadPendingInput(limit=100))
        assert page0.messages == []

        # Human posts two messages
        for txt in ("hello", "world"):
            p = await h.post(PostInput(mime="text/markdown", content=txt))
            assert p.id

        # Assistant reads pending (should get both user messages once)
        page = await a.read_pending_messages(ReadPendingInput(limit=100))
        assert [m.content for m in page.messages] == ["hello", "world"]
        assert all(m.author == ChatAuthor.USER for m in page.messages)

        # Second read should be empty (HWM advanced)
        page2 = await a.read_pending_messages(ReadPendingInput(limit=100))
        assert page2.messages == []

        # Assistant replies; human reads it pending
        reply = await a.post(PostInput(mime="text/markdown", content="roger"))
        assert reply.id
        hpage = await h.read_pending_messages(ReadPendingInput(limit=100))
        assert len(hpage.messages) == 1
        assert hpage.messages[0].content == "roger"
        assert hpage.messages[0].author == ChatAuthor.ASSISTANT


class _Capture(MessageHandler):
    def __init__(self) -> None:
        self.updated: list[str] = []

    async def on_resource_updated(self, message: mcp_types.ResourceUpdatedNotification) -> None:  # type: ignore[override]
        self.updated.append(str(message.params.uri))


@pytest.mark.asyncio
async def test_chat_head_notifications_other_participant() -> None:
    store = ChatStore()
    human = make_chat_server(name="chat.human", author=ChatAuthor.USER, store=store)
    assistant = make_chat_server(name="chat.assistant", author=ChatAuthor.ASSISTANT, store=store)
    store.register_servers(human=human, assistant=assistant)

    # Assistant notifications on human posts
    cap_assist = _Capture()
    async with (
        McpClient(assistant, message_handler=cap_assist) as assist_sess,
        McpClient(human) as human_sess,
    ):
        h = TypedClient.from_server(human, human_sess)
        await h.post(PostInput(mime="text/markdown", content="hello"))
        await asyncio.sleep(0.05)
        assert any(uri.endswith("chat://head") for uri in cap_assist.updated), cap_assist.updated

    # Human notifications on assistant posts
    cap_human = _Capture()
    async with (
        McpClient(human, message_handler=cap_human) as human_sess,
        McpClient(assistant) as assist_sess,
    ):
        a = TypedClient.from_server(assistant, assist_sess)
        await a.post(PostInput(mime="text/markdown", content="roger"))
        await asyncio.sleep(0.05)
        assert any(uri.endswith("chat://head") for uri in cap_human.updated), cap_human.updated


@pytest.mark.asyncio
async def test_chat_last_read_updates_with_read_pending() -> None:
    # Build servers and register cross-broadcasts
    store = ChatStore()
    human = make_chat_server(name="chat.human", author=ChatAuthor.USER, store=store)
    assistant = make_chat_server(name="chat.assistant", author=ChatAuthor.ASSISTANT, store=store)
    store.register_servers(human=human, assistant=assistant)

    # Attach a capture handler to the assistant server where read_pending is called
    cap_assist = _Capture()
    async with (
        McpClient(assistant, message_handler=cap_assist) as assistant_sess,
        McpClient(human) as human_sess,
    ):
        h = TypedClient.from_server(human, human_sess)
        a = TypedClient.from_server(assistant, assistant_sess)

        # Human posts one message; assistant HWM should advance on read and emit last-read update
        await h.post(PostInput(mime="text/markdown", content="one"))
        cap_assist.updated.clear()
        await a.read_pending_messages(ReadPendingInput(limit=100))
        await asyncio.sleep(0.05)
        assert any(uri.endswith("chat://last-read") for uri in cap_assist.updated), (
            cap_assist.updated
        )

        # Reading again without new messages should not advance HWM or emit another last-read update
        cap_assist.updated.clear()
        await a.read_pending_messages(ReadPendingInput(limit=100))
        await asyncio.sleep(0.05)
        assert not cap_assist.updated
