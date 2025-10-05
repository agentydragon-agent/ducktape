from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Generic, TypeVar

from mcp import types as mcp_types
from pydantic import BaseModel, TypeAdapter


# Minimal duck-typed MCP session interface we rely on in tests
class _SessionProto:  # pragma: no cover - typing aid only
    async def call_tool(self, *, name: str, arguments: dict[str, Any]) -> Any: ...


T_Out = TypeVar("T_Out")


def _require_structured(resp: Any, *, tool_name: str) -> Any:
    """Return structuredContent or raise if not provided (success path only)."""
    if not isinstance(resp, mcp_types.CallToolResult):
        raise TypeError(
            f"{tool_name!r} returned unexpected type: {type(resp).__name__}; expected CallToolResult"
        )
    if resp.isError:
        raise AssertionError(
            f"{tool_name!r} returned error; use TypedClient.error(...) assertion path in tests"
        )
    sc = resp.structuredContent
    if sc is None:
        raise RuntimeError(
            f"{tool_name!r} did not return structuredContent; tests require structured outputs"
        )
    return sc


async def call_tool_typed(
    session: _SessionProto,
    name: str,
    payload: BaseModel | dict[str, Any],
    out_type: type[T_Out],
    *,
    exclude_none: bool = True,
) -> T_Out:
    """Call an MCP tool with a Pydantic input and parse a Pydantic output.

    Requires structuredContent from the server; raises otherwise.
    """
    args = (
        payload.model_dump(exclude_none=exclude_none) if isinstance(payload, BaseModel) else payload
    )
    resp = await session.call_tool(name=name, arguments=args)
    raw = _require_structured(resp, tool_name=name)
    return TypeAdapter(out_type).validate_python(raw)


class ToolStub(Generic[T_Out]):
    """Awaitable callable bound to a (session, tool_name, out_type)."""

    def __init__(
        self,
        session: _SessionProto,
        name: str,
        out_type: type[T_Out],
        *,
        exclude_none: bool = True,
    ) -> None:
        self._session = session
        self._name = name
        self._out_type = out_type
        self._exclude_none = exclude_none

    async def __call__(self, payload: BaseModel | dict[str, Any]) -> T_Out:
        return await call_tool_typed(
            self._session,
            self._name,
            payload,
            self._out_type,
            exclude_none=self._exclude_none,
        )


@dataclass(frozen=True)
class ToolModels:
    # Public types tests should use
    Input: type[BaseModel] | None
    Output: type[Any]
    # Internal wiring details for FastMCP registry
    _arg_model: type[BaseModel] | None = None
    _wrapper_field: str | None = None
    wrap_output: bool = False


def _extract_error_message(resp: Any) -> str:
    if isinstance(resp, mcp_types.CallToolResult):
        nontext: list[str] = []
        for b in resp.content or []:
            if isinstance(b, mcp_types.TextContent):
                txt = b.text
                if isinstance(txt, str) and txt:
                    return txt
            nontext.append(type(b).__name__)
        if nontext:
            # Specific failure for unsupported non-text tool error content
            raise NotImplementedError(f"Unsupported tool error content types: {', '.join(nontext)}")
    return "tool error"


class TypedClient:
    """Factory for typed tool call stubs bound to a session.

    Usage:
      # Manual typing
      client = TypedClient(session)
      sandbox_exec = client.stub("sandbox_exec", SandboxExecResult)
      res = await sandbox_exec(ExecArgs(...))

      # In-proc typed client (introspects FastMCP server registry)
      client = TypedClient.from_server(server, session)
      ExecArgs = client.models["sandbox_exec"].Input
      res = await client.sandbox_exec(ExecArgs(...))
    """

    def __init__(self, session: _SessionProto, *, exclude_none: bool = True) -> None:
        self._session = session
        self._exclude_none = exclude_none
        self._models: dict[str, ToolModels] = {}

    def stub(self, name: str, out_type: type[T_Out]) -> ToolStub[T_Out]:
        return ToolStub(self._session, name, out_type, exclude_none=self._exclude_none)

    @property
    def models(self) -> dict[str, ToolModels]:
        return self._models

    @classmethod
    def from_server(
        cls,
        server: Any,
        session: _SessionProto,
        *,
        exclude_none: bool = True,
    ) -> "TypedClient":
        """Create a TypedClient introspecting FastMCP's tool registry.

        Requires a server created via FastMCP. Uses server._tool_manager.list_tools()
        and reads each tool.fn_metadata.arg_model/output_model.
        """
        # Access the internal tool manager and fetch tools
        tm = getattr(server, "_tool_manager", None)
        if tm is None or not hasattr(tm, "list_tools"):
            raise RuntimeError("Server does not expose _tool_manager with list_tools()")
        tools = tm.list_tools()

        client = cls(session, exclude_none=exclude_none)
        for t in tools:
            fm = getattr(t, "fn_metadata", None)
            if not fm:
                continue
            arg_model = getattr(fm, "arg_model", None)
            out_model = getattr(fm, "output_model", None)
            wrap = bool(getattr(fm, "wrap_output", False))
            if out_model is None or arg_model is None:
                continue

            # Prefer explicit hints from helper-decorated wrappers
            fn = getattr(t, "fn", None)
            hinted_input = getattr(fn, "_mcp_flat_input_model", None) if fn else None
            hinted_output = getattr(fn, "_mcp_flat_output_model", None) if fn else None

            input_type: type[BaseModel] | None = None
            wrapper_field = None

            if isinstance(hinted_input, type) and issubclass(hinted_input, BaseModel):
                input_type = hinted_input
            else:
                # Fallback: flatten single-parameter BaseModel: prefer the inner named model
                try:
                    fields = getattr(arg_model, "model_fields")
                    if isinstance(fields, dict) and len(fields) == 1:
                        wrapper_field = next(iter(fields.keys()))
                        field_info = fields[wrapper_field]
                        ann = getattr(field_info, "annotation", None)
                        if isinstance(ann, type) and issubclass(ann, BaseModel):
                            input_type = ann
                except (AttributeError, KeyError, TypeError):
                    # Fallback to arg_model when field metadata is unavailable
                    pass

            # Final fallback: use arg_model
            if input_type is None:
                input_type = arg_model

            client._models[t.name] = ToolModels(
                Input=input_type,
                Output=hinted_output or out_model,
                _arg_model=arg_model,
                _wrapper_field=wrapper_field,
                wrap_output=wrap,
            )
        return client

    def error(self, name: str) -> Callable[[BaseModel], Awaitable[str]]:
        models = self._models.get(name)
        if not models:
            raise AttributeError(name)
        exclude_none = self._exclude_none
        session = self._session

        async def _err(payload: BaseModel) -> str:
            if models.Input is None or not isinstance(payload, models.Input):
                raise TypeError(
                    f"{name} expects {(models.Input.__name__ if models.Input else 'None')}, got {type(payload).__name__}"
                )
            if models._wrapper_field and models._arg_model:
                args_dict = {models._wrapper_field: payload.model_dump(exclude_none=exclude_none)}
            else:
                args_dict = payload.model_dump(exclude_none=exclude_none)
            resp = await session.call_tool(name=name, arguments=args_dict)
            assert getattr(resp, "isError", False) is True, "expected tool error"
            return _extract_error_message(resp)

        return _err

    def __getattr__(self, name: str) -> Callable[[BaseModel], Awaitable[Any]]:
        # Provide convenient client.tool_name(ExecArgs(...)) form when we have models
        models = self._models.get(name)
        if not models:
            raise AttributeError(name)
        adapter = TypeAdapter(models.Output)
        exclude_none = self._exclude_none
        session = self._session

        async def _call(payload: BaseModel) -> Any:
            if models.Input is None or not isinstance(payload, models.Input):
                raise TypeError(
                    f"{name} expects {(models.Input.__name__ if models.Input else 'None')}, got {type(payload).__name__}"
                )
            # If FastMCP wrapped the single argument under a field (e.g., 'payload'), rebuild the arg_model
            if models._wrapper_field and models._arg_model:
                args_dict = {models._wrapper_field: payload.model_dump(exclude_none=exclude_none)}
            else:
                args_dict = payload.model_dump(exclude_none=exclude_none)
            resp = await session.call_tool(name=name, arguments=args_dict)
            raw = _require_structured(resp, tool_name=name)
            if models.wrap_output and isinstance(raw, dict) and "result" in raw:
                raw = raw["result"]
            return adapter.validate_python(raw)

        return _call
