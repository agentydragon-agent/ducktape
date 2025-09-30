from __future__ import annotations

import functools
import inspect
import logging
from typing import (
    Annotated,
    Any,
    Awaitable,
    Callable,
    TypeVar,
    cast,
    get_args,
    get_origin,
    get_type_hints,
)

from pydantic import BaseModel, Field
from pydantic_core import PydanticUndefined
import anyio
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from contextlib import AbstractAsyncContextManager, AsyncExitStack
from mcp.server.fastmcp import FastMCP
from mcp.server.lowlevel.server import InitializationOptions, Server
from mcp.server.session import ServerSession
from mcp.shared.message import SessionMessage

logger = logging.getLogger("adgn.mcp")

# Intentionally no __all__; internal helpers are available for local imports.


def _make_flat_signature_from_model(
    model: type[BaseModel],
    *,
    return_type: Any,
) -> inspect.Signature:
    """Create a flat, keyword-only function signature from a Pydantic model.

    Each model field becomes one keyword-only parameter annotated as
    Annotated[T, Field(...)] so FastMCP can emit a rich JSON Schema directly
    from the wrapper function signature.
    """
    params: list[inspect.Parameter] = []
    for name, fld in model.model_fields.items():
        ann = fld.annotation
        # Preserve description/default/alias/default_factory so it shows up in tool schema.
        field_kwargs: dict[str, Any] = {
            "description": fld.description,
        }
        alias = fld.alias
        if alias:
            field_kwargs["alias"] = alias
        # Only set default if truly provided; do NOT insert None
        if fld.default is not PydanticUndefined:
            field_kwargs["default"] = fld.default
        # Propagate default_factory when present
        df = fld.default_factory
        if df is not None and df is not PydanticUndefined:
            field_kwargs["default_factory"] = df
        annotated_type: Any
        if ann in (inspect._empty, None):
            annotated_type = Any
        else:
            annotated_type = ann
        annotated = Annotated[
            annotated_type,
            Field(**field_kwargs),
        ]
        # Parameter default mirrors model: required if no default/default_factory
        if df is not None or fld.default is not PydanticUndefined:
            param_default = (
                fld.default if fld.default is not PydanticUndefined else inspect._empty
            )
            # Note: default_factory cannot be expressed as a Python default; leave empty
        else:
            param_default = inspect._empty
        params.append(
            inspect.Parameter(
                name=name,
                kind=inspect.Parameter.KEYWORD_ONLY,
                default=param_default,
                annotation=annotated,
            )
        )

    return inspect.Signature(parameters=params, return_annotation=return_type)


InputModelT = TypeVar("InputModelT", bound=BaseModel)

RegisterTool = Callable[[Callable[..., Any], dict[str, Any]], Callable[..., Any]]


def _flat_model_decorator(
    register_tool: RegisterTool,
    *,
    name: str | None = None,
    title: str | None = None,
    description: str | None = None,
    annotations: Any | None = None,
    structured_output: bool = True,
    input_model: type[BaseModel] | None = None,
    output_model: type[BaseModel] | None = None,
):
    def outer(
        fn: Callable[[InputModelT], Any],
    ) -> Callable[[InputModelT], Any]:
        sig = inspect.signature(fn)
        params = list(sig.parameters.values())
        if len(params) != 1:
            raise TypeError(
                "@mcp_flat_model expects exactly one parameter (the Pydantic model)"
            )
        param = params[0]

        # Resolve type hints with the function's globals for forward refs — but only if needed
        if input_model is None or output_model is None:
            hints = get_type_hints(
                fn, globalns=getattr(fn, "__globals__", {}), include_extras=True
            )
        else:
            hints = {}

        inferred_input = input_model or hints.get(param.name, param.annotation)
        model_in = inferred_input
        if isinstance(model_in, str):
            raise NotImplementedError(
                "mcp_flat_model requires real types for input; string annotations are not supported. "
                "Move models to module scope or pass input_model=... explicitly."
            )
        if not (isinstance(model_in, type) and issubclass(model_in, BaseModel)):
            raise TypeError(
                "Parameter must be a Pydantic BaseModel subclass (or pass input_model=...)"
            )

        inferred_return = output_model or hints.get("return", sig.return_annotation)
        model_out = inferred_return
        if isinstance(model_out, str):
            raise NotImplementedError(
                "mcp_flat_model requires real types for output; string annotations are not supported. "
                "Move models to module scope or pass output_model=... explicitly."
            )
        if structured_output and model_out is inspect.Signature.empty:
            raise TypeError(
                "Return annotation is required when structured_output=True (or pass output_model=...)"
            )

        # Resolve forward refs in input/output models before schema/signature building
        try:
            model_in.model_rebuild()
        except AttributeError as exc:
            raise TypeError(
                "Input model must be a Pydantic BaseModel with model_rebuild()"
            ) from exc
        except Exception:
            pass
        # If model_out is Annotated[Model, Field(...)] or similar, extract the model for rebuild
        rt = model_out
        if get_origin(rt) is Annotated:
            # Annotated[T, ...] → take T
            rt = get_args(rt)[0]
        if isinstance(rt, type) and issubclass(rt, BaseModel):
            try:
                rt.model_rebuild()
            except AttributeError as exc:
                raise TypeError(
                    "Output model must expose model_rebuild(); ensure it is a Pydantic model"
                ) from exc
            except Exception:
                pass

        # Preserve async/sync nature to keep FastMCP is_async detection correct
        def _coerce_payload(kwargs: dict[str, Any]) -> InputModelT:
            # Flat-only: require flat keyword args matching the Input model
            # (legacy nested {"payload": {...}} is not accepted)
            return cast(InputModelT, model_in(**kwargs))

        is_async = inspect.iscoroutinefunction(fn)
        if is_async:

            @functools.wraps(fn)
            async def _flat_wrapper(**kwargs: Any) -> Any:
                payload = _coerce_payload(kwargs)
                return await cast(Callable[[InputModelT], Awaitable[Any]], fn)(
                    cast(InputModelT, payload)
                )
        else:

            @functools.wraps(fn)
            def _flat_wrapper(**kwargs: Any) -> Any:
                payload = _coerce_payload(kwargs)
                return cast(Callable[[InputModelT], Any], fn)(
                    cast(InputModelT, payload)
                )

        # Advertise original input/output models for typed clients
        setattr(_flat_wrapper, "_mcp_flat_input_model", model_in)
        if model_out is not inspect.Signature.empty:
            setattr(_flat_wrapper, "_mcp_flat_output_model", model_out)

        # Synthesize a flat signature so FastMCP emits a flat input schema
        signature = _make_flat_signature_from_model(
            model_in,
            return_type=model_out,
        )
        setattr(_flat_wrapper, "__signature__", signature)
        # Also set return annotation so FastMCP picks up structured output schema
        try:
            anns = dict(getattr(_flat_wrapper, "__annotations__", {}) or {})
            anns["return"] = model_out
            _flat_wrapper.__annotations__ = anns
        except Exception:
            pass

        # Register wrapper as a tool; FastMCP will introspect the flat signature
        tool_kwargs = dict(
            name=name,
            title=title,
            description=description,
            annotations=annotations,
            structured_output=structured_output,
        )
        registered = register_tool(_flat_wrapper, tool_kwargs)
        return cast(Callable[[InputModelT], Any], registered)

    return outer


class FlatModelToolMixin:
    """Mixin that lets ``@mcp.tool`` flatten Pydantic models with new keywords.

    This mixin expects to be mixed with FastMCP or a class that has a tool method.
    """

    def tool(
        self,
        name: str | None = None,
        title: str | None = None,
        description: str | None = None,
        annotations: Any | None = None,
        structured_output: bool | None = None,
        *,
        flat: bool = False,
        flat_input_model: type[BaseModel] | None = None,
        flat_output_model: type[BaseModel] | None = None,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Extend FastMCP.tool with ``flat_*`` keywords for Pydantic helpers."""

        wants_flat = (
            flat or flat_input_model is not None or flat_output_model is not None
        )
        if not wants_flat:
            base_tool = super().tool  # type: ignore[misc]
            return cast(
                Callable[[Callable[..., Any]], Callable[..., Any]],
                base_tool(
                    name=name,
                    title=title,
                    description=description,
                    annotations=annotations,
                    structured_output=structured_output,
                ),
            )

        effective_structured_output = (
            structured_output if structured_output is not None else True
        )

        def _register(
            fn: Callable[..., Any], mcp_tool_kwargs: dict[str, Any]
        ) -> Callable[..., Any]:
            # Nested helper runs outside method descriptor context; pass explicit
            # class + instance so ``super`` resolves correctly during runtime.
            base_tool = super(FlatModelToolMixin, self).tool  # type: ignore[misc]
            decorator = cast(
                Callable[[Callable[..., Any]], Callable[..., Any]],
                base_tool(**mcp_tool_kwargs),
            )
            return decorator(fn)

        return cast(
            Callable[[Callable[..., Any]], Callable[..., Any]],
            _flat_model_decorator(
                _register,
                name=name,
                title=title,
                description=description,
                annotations=annotations,
                structured_output=effective_structured_output,
                input_model=flat_input_model,
                output_model=flat_output_model,
            ),
        )


class FlatModelFastMCP(FlatModelToolMixin, FastMCP):
    """FastMCP subclass with the flat-model convenience decorator built-in."""


def mcp_flat_model(
    mcp: FastMCP,
    *,
    name: str | None = None,
    title: str | None = None,
    description: str | None = None,
    annotations: Any | None = None,
    structured_output: bool = True,
    input_model: type[BaseModel] | None = None,
    output_model: type[BaseModel] | None = None,
):
    """Backward-compatible convenience wrapper for FastMCP instances.

    When the provided MCP instance implements ``flat_model`` (e.g. via
    FlatModelToolMixin) that method is used directly; otherwise we fall back to
    the original helper behaviour.
    """

    if isinstance(mcp, FlatModelToolMixin):
        return cast(
            Callable[[Callable[..., Any]], Callable[..., Any]],
            mcp.tool(
                name=name,
                title=title,
                description=description,
                annotations=annotations,
                structured_output=structured_output,
                flat=True,
                flat_input_model=input_model,
                flat_output_model=output_model,
            ),
        )

    def _register(
        fn: Callable[..., Any], mcp_tool_kwargs: dict[str, Any]
    ) -> Callable[..., Any]:
        decorator = cast(
            Callable[[Callable[..., Any]], Callable[..., Any]],
            mcp.tool(**mcp_tool_kwargs),
        )
        return decorator(fn)

    return cast(
        Callable[[Callable[..., Any]], Callable[..., Any]],
        _flat_model_decorator(
            _register,
            name=name,
            title=title,
            description=description,
            annotations=annotations,
            structured_output=structured_output,
            input_model=input_model,
            output_model=output_model,
        ),
    )


class SafeDispatchServer(Server):
    """Low-level Server that dispatches each request in a child task.

    Ensures a request responder's enter/exit occur within the same task, avoiding
    cancel-scope mismatches during shutdown. Keeps full parallelism via a
    TaskGroup.
    """

    async def run(
        self,
        read_stream: MemoryObjectReceiveStream[SessionMessage | Exception],
        write_stream: MemoryObjectSendStream[SessionMessage],
        initialization_options: InitializationOptions,
        raise_exceptions: bool = False,
        stateless: bool = False,
    ):
        async with AsyncExitStack() as stack:
            lifespan_context = await stack.enter_async_context(self.lifespan(self))
            session = await stack.enter_async_context(
                ServerSession(
                    read_stream,
                    write_stream,
                    initialization_options,
                    stateless=stateless,
                )
            )
            async with anyio.create_task_group() as tg:
                async for message in session.incoming_messages:

                    async def _serve(msg):
                        try:
                            await self._handle_message(
                                msg,
                                session,
                                lifespan_context,
                                raise_exceptions,
                            )
                        except BaseException as exc:  # do not cancel siblings
                            logger.exception("Server responder error: %s", exc)

                    tg.start_soon(_serve, message)


class SafeFastMCP(FlatModelToolMixin, FastMCP):
    """FastMCP that uses SafeDispatchServer for low-level dispatch.

    We replace the underlying low-level server immediately after base init and
    re-install handlers so all registered tools are bound to the safe server.
    """

    def __init__(
        self,
        name: str,
        *,
        instructions: str | None = None,
        lifespan: Callable[[FastMCP], AbstractAsyncContextManager[Any]] | None = None,
    ) -> None:
        super().__init__(name=name, instructions=instructions, lifespan=lifespan)
        cur = cast(Server, self._mcp_server)
        if not isinstance(cur, SafeDispatchServer):
            name0 = cur.name
            instr0 = cur.instructions
            prev_lifespan = getattr(cur, "lifespan", None)
            new_server = SafeDispatchServer(name=name0, instructions=instr0)
            # Preserve lifespan behavior from the previous low-level server
            if prev_lifespan is not None:
                try:
                    setattr(new_server, "lifespan", prev_lifespan)
                except Exception:
                    pass
            setattr(self, "_mcp_server", new_server)
            self._setup_handlers()
