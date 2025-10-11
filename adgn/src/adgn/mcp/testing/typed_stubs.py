from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Generic, TypeVar

from fastmcp.client import Client
from fastmcp.client.client import CallToolResult
from mcp import types as mcp_types
from pydantic import BaseModel, TypeAdapter

# We use the concrete FastMCP Client type for sessions in tests


T_Out = TypeVar("T_Out")


def _require_structured(resp: CallToolResult, *, tool_name: str) -> Any:
    """Return structuredContent or raise if not provided (success path only).

    Requires a FastMCP CallToolResult; enforces success and structuredContent presence.
    """
    if resp.is_error:
        raise AssertionError(
            f"{tool_name!r} returned error; use TypedClient.error(...) assertion path in tests"
        )
    sc = resp.structured_content
    if sc is None:
        raise RuntimeError(
            f"{tool_name!r} did not return structuredContent; tests require structured outputs"
        )
    return sc


async def call_tool_typed(
    session: Client,
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
    if not isinstance(resp, CallToolResult):
        raise TypeError(f"{name!r} must return a CallToolResult, got {type(resp).__name__}")
    raw = _require_structured(resp, tool_name=name)
    return TypeAdapter(out_type).validate_python(raw)


class ToolStub(Generic[T_Out]):
    """Awaitable callable bound to a (session, tool_name, out_type)."""

    def __init__(
        self,
        session: Client,
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
    # No output wrapping; servers should return structured content matching Output


def _extract_error_message(resp: Any) -> str:
    if isinstance(resp, CallToolResult):
        nontext: list[str] = []
        for b in resp.content or []:
            if isinstance(b, mcp_types.TextContent):
                txt = b.text
                if isinstance(txt, str) and txt:
                    return txt
            else:
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

    def __init__(self, session: Client, *, exclude_none: bool = True) -> None:
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
        session: Client,
        *,
        exclude_none: bool = True,
    ) -> "TypedClient":
        """Create a TypedClient introspecting FastMCP's tool registry.

        Requires a server created via FastMCP. Uses server._tool_manager.list_tools()
        and reads each tool.fn_metadata.arg_model/output_model.
        """
        # Access the internal tool manager and fetch local tools synchronously
        try:
            tm = server._tool_manager  # type: ignore[attr-defined]
        except AttributeError as exc:
            raise RuntimeError("Server does not expose _tool_manager") from exc
        # Prefer local tools; mounted tools aren't needed for typed tests here
        tools = list(getattr(tm, "_tools", {}).values())

        client = cls(session, exclude_none=exclude_none)
        for t in tools:
            try:
                fm = t.fn_metadata  # type: ignore[attr-defined]
            except AttributeError:
                fm = None
            try:
                fn = t.fn  # type: ignore[attr-defined]
            except AttributeError:
                fn = None
            hinted_input = getattr(fn, "_mcp_flat_input_model", None) if fn else None
            hinted_output = getattr(fn, "_mcp_flat_output_model", None) if fn else None

            if fm is None:
                # Fall back to flat-model hints only
                arg_model = hinted_input
                out_model = hinted_output
                if not (isinstance(arg_model, type) and issubclass(arg_model, BaseModel)):
                    continue
            else:
                arg_model = fm.arg_model  # type: ignore[attr-defined]
                out_model = fm.output_model  # type: ignore[attr-defined]
                if out_model is None or arg_model is None:
                    continue

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

            try:
                tool_key = t.key  # type: ignore[attr-defined]
            except AttributeError:
                tool_key = getattr(t, "name", None)
            if not isinstance(tool_key, str) or not tool_key:
                continue
            client._models[tool_key] = ToolModels(
                Input=input_type,
                Output=hinted_output or out_model or Any,
                _arg_model=arg_model,
                _wrapper_field=wrapper_field,
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
            # Call; FastMCP raises on tool error by default. Capture and return message.
            try:
                resp = await session.call_tool(name=name, arguments=args_dict)
            except Exception as exc:
                return str(exc)
            if not isinstance(resp, CallToolResult):
                raise TypeError(f"{name!r} must return a CallToolResult, got {type(resp).__name__}")
            if not resp.is_error:
                raise AssertionError("expected tool error")
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
            if not isinstance(resp, CallToolResult):
                raise TypeError(f"{name!r} must return a CallToolResult, got {type(resp).__name__}")
            raw = _require_structured(resp, tool_name=name)
            return adapter.validate_python(raw)

        return _call
