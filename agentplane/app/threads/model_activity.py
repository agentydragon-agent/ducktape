"""Conservative event-derived proxy for when this Thread last used a model.

This is not an observed provider request or evidence of a cache hit. Tool results and
harness bookkeeping can arrive much later than the request that caused them.
"""

from agentplane.protocol import event_pb2

# gazelle:include_dep @pypi//protobuf


def is_model_activity(event: event_pb2.Event) -> bool:
    match event.WhichOneof("observation"):
        case "text_delta":
            return bool(event.text_delta.text)
        case "tool_arguments_delta":
            return bool(event.tool_arguments_delta.partial_json)
        case "tool_arguments":
            return bool(event.tool_arguments.arguments_json)
        case "item_started":
            return event.item_started.kind in (
                event_pb2.ITEM_KIND_ASSISTANT_TEXT,
                event_pb2.ITEM_KIND_REASONING,
                event_pb2.ITEM_KIND_TOOL_CALL,
            )
        case "item_completed":
            return event.item_completed.WhichOneof("outcome") == "text" and bool(event.item_completed.text)
        case _:
            return False
