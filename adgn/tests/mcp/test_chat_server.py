import asyncio
from typing import Any

from fastmcp.client import Client
from hamcrest import anything, assert_that, contains, empty, has_properties
from hamcrest.core.matcher import Matcher
import pytest

from adgn.mcp.chat.server import (
    ChatAuthor,
    ChatMessage,
    ChatStore,
    PostInput,
    PostResult,
    ReadPendingInput,
    make_chat_server,
)
from adgn.mcp.stubs.typed_stubs import TypedClient
from adgn.mcp.testing.chat_stubs import ChatServerStub
from tests.mcp.conftest import ResourceUpdatedCapture


@pytest.fixture
def chat_servers() -> tuple[ChatStore, Any, Any]:
    """Create and wire up chat servers with shared store."""
    store = ChatStore()
    human = make_chat_server(name="chat.human", author=ChatAuthor.USER, store=store)
    assistant = make_chat_server(name="chat.assistant", author=ChatAuthor.ASSISTANT, store=store)
    store.register_servers(human=human, assistant=assistant)
    return store, human, assistant


def user_markdown_message(content: str, *, id: Matcher[str] | None = None) -> Matcher[ChatMessage]:
    """Matcher for user markdown messages."""
    if id is None:
        id = anything()
    matcher: Matcher[ChatMessage] = has_properties(author=ChatAuthor.USER, mime="text/markdown", content=content, id=id)
    return matcher


def assistant_markdown_message(content: str, *, id: Matcher[str] | None = None) -> Matcher[ChatMessage]:
    """Matcher for assistant markdown messages."""
    if id is None:
        id = anything()
    matcher: Matcher[ChatMessage] = has_properties(
        author=ChatAuthor.ASSISTANT, mime="text/markdown", content=content, id=id
    )
    return matcher


async def test_chat_flow_user_to_agent_then_agent_to_user(chat_servers) -> None:
    _store, human, assistant = chat_servers

    async with Client(human) as human_sess, Client(assistant) as assistant_sess:
        h = ChatServerStub.from_server(human, human_sess)
        a = ChatServerStub.from_server(assistant, assistant_sess)

        # Initially, assistant has nothing pending
        page0 = await a.read_pending_messages(ReadPendingInput(limit=100))
        assert_that(page0.messages, empty())

        # Human posts two messages
        for txt in ("hello", "world"):
            p = await h.post(PostInput(mime="text/markdown", content=txt))
            assert p.id

        # Assistant reads pending (should get both user messages once)
        page = await a.read_pending_messages(ReadPendingInput(limit=100))
        messages = page.messages
        assert len(messages) == 2
        assert messages[0].author == ChatAuthor.USER
        assert messages[0].mime == "text/markdown"
        assert messages[0].content == "hello"
        assert messages[1].author == ChatAuthor.USER
        assert messages[1].mime == "text/markdown"
        assert messages[1].content == "world"

        # Second read should be empty (HWM advanced)
        page2 = await a.read_pending_messages(ReadPendingInput(limit=100))
        assert_that(page2.messages, empty())

        # Assistant replies; human reads it pending
        reply = await a.post(PostInput(mime="text/markdown", content="roger"))
        assert reply.id is not None
        hpage = await h.read_pending_messages(ReadPendingInput(limit=100))
        assert_that(hpage.messages, contains(assistant_markdown_message("roger")))


async def test_chat_head_notifications_other_participant(chat_servers) -> None:
    _store, human, assistant = chat_servers

    # Assistant notifications on human posts
    cap_assist = ResourceUpdatedCapture()
    async with Client(assistant, message_handler=cap_assist) as assist_sess, Client(human) as human_sess:
        h_post = TypedClient.from_server(human, human_sess).stub("post", PostResult)
        await h_post(PostInput(mime="text/markdown", content="hello"))
        await asyncio.sleep(0.05)
        assert any(uri.endswith("chat://head") for uri in cap_assist.updated), cap_assist.updated

    # Human notifications on assistant posts
    cap_human = ResourceUpdatedCapture()
    async with Client(human, message_handler=cap_human) as human_sess, Client(assistant) as assist_sess:
        a_post = TypedClient.from_server(assistant, assist_sess).stub("post", PostResult)
        await a_post(PostInput(mime="text/markdown", content="roger"))
        await asyncio.sleep(0.05)
        assert any(uri.endswith("chat://head") for uri in cap_human.updated), cap_human.updated


async def test_chat_last_read_updates_with_read_pending(chat_servers) -> None:
    _store, human, assistant = chat_servers

    # Attach a capture handler to the assistant server where read_pending is called
    cap_assist = ResourceUpdatedCapture()
    async with Client(assistant, message_handler=cap_assist) as assistant_sess, Client(human) as human_sess:
        h = ChatServerStub.from_server(human, human_sess)
        a = ChatServerStub.from_server(assistant, assistant_sess)

        # Human posts one message; assistant HWM should advance on read and emit last-read update
        await h.post(PostInput(mime="text/markdown", content="one"))
        cap_assist.updated.clear()
        await a.read_pending_messages(ReadPendingInput(limit=100))
        await asyncio.sleep(0.05)
        assert any(uri.endswith("chat://last-read") for uri in cap_assist.updated), cap_assist.updated

        # Reading again without new messages should not advance HWM or emit another last-read update
        cap_assist.updated.clear()
        await a.read_pending_messages(ReadPendingInput(limit=100))
        await asyncio.sleep(0.05)
        assert not cap_assist.updated
