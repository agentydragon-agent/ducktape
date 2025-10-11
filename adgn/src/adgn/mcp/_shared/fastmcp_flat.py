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

from fastmcp.server import FastMCP
from pydantic import BaseModel, ConfigDict, Field
from pydantic_core import PydanticUndefined

logger = logging.getLogger(__name__)

InputModelT = TypeVar("InputModelT", bound=BaseModel)
RegisterTool = Callable[[Callable[..., Any], dict[str, Any]], Callable[..., Any]]


def _make_flat_signature_from_model(
    model: type[BaseModel], *, return_type: Any
) -> inspect.Signature:
    params: list[inspect.Parameter] = []
    for name, fld in model.model_fields.items():
        ann = fld.annotation
        field_kwargs: dict[str, Any] = {"description": fld.description}
        if fld.alias:
            field_kwargs["alias"] = fld.alias
        if fld.default is not PydanticUndefined:
            field_kwargs["default"] = fld.default
        df = fld.default_factory
        if df is not None and df is not PydanticUndefined:
            field_kwargs["default_factory"] = df
        annotated_type: Any = Any if ann in (inspect._empty, None) else ann
        annotated = Annotated[annotated_type, Field(**field_kwargs)]
        if df is not None or fld.default is not PydanticUndefined:
            param_default = fld.default if fld.default is not PydanticUndefined else inspect._empty
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


def _flat_model_decorator(
    register_tool: RegisterTool,
    *,
    name: str | None = None,
    title: str | None = None,
    description: str | None = None,
    annotations: Any | None = None,
    structured_output: bool = True,
    output_model: type[BaseModel] | None = None,
):
    def outer(fn: Callable[[InputModelT], Any]) -> Callable[[InputModelT], Any]:
        sig = inspect.signature(fn)
        params = list(sig.parameters.values())
        if len(params) != 1:
            raise TypeError("@mcp_flat_model expects exactly one parameter (the Pydantic model)")
        param = params[0]

        if not inspect.isfunction(fn):
            raise TypeError("@mcp_flat_model requires a plain function (not a callable object)")
        globs = fn.__globals__
        try:
            hints = get_type_hints(fn, globalns=globs, localns=globs, include_extras=True)
        except (NameError, TypeError, AttributeError):
            # Fallback when annotations reference names not yet defined or unsupported constructs
            hints = {}

        def _resolve_model(name: str, annotation: Any) -> type[BaseModel]:
            cand = hints.get(name, annotation)
            if isinstance(cand, str):
                try:
                    cand = globs[cand]
                except Exception:
                    raise NotImplementedError(
                        "mcp_flat_model requires real types for input; string annotations not resolved. "
                        "Move models to module scope to allow resolution."
                    )
            if not (isinstance(cand, type) and issubclass(cand, BaseModel)):
                raise TypeError("Parameter must be a Pydantic BaseModel subclass")
            return cand

        model_in = _resolve_model(param.name, param.annotation)

        inferred_return = output_model or hints.get("return", sig.return_annotation)
        model_out = inferred_return
        if isinstance(model_out, str):
            globs = fn.__globals__
            try:
                model_out = globs[model_out]
            except Exception:
                raise NotImplementedError(
                    "mcp_flat_model requires real types for output; string annotations not resolved. "
                    "Move models to module scope or pass output_model=... explicitly."
                )
        if structured_output and model_out is inspect.Signature.empty:
            raise TypeError(
                "Return annotation is required when structured_output=True (or pass output_model=...)"
            )

        try:
            model_in.model_rebuild()
        except AttributeError as exc:
            raise TypeError(
                "Input model must be a Pydantic BaseModel with model_rebuild()"
            ) from exc
        except Exception as e:
            logger.debug("model_rebuild() on input failed: %s", e)

        rt = model_out
        if get_origin(rt) is Annotated:
            rt = get_args(rt)[0]
        if isinstance(rt, type) and issubclass(rt, BaseModel):
            try:
                rt.model_rebuild()
            except AttributeError as exc:
                raise TypeError(
                    "Output model must expose model_rebuild(); ensure it is a Pydantic model"
                ) from exc
            except Exception as e:
                logger.debug("model_rebuild() on output failed: %s", e)

        def _coerce_payload(kwargs: dict[str, Any]) -> InputModelT:
            return cast(InputModelT, model_in(**kwargs))

        is_async = inspect.iscoroutinefunction(fn)
        if is_async:
            typed_async: Callable[[InputModelT], Awaitable[Any]] = cast(
                Callable[[InputModelT], Awaitable[Any]], fn
            )

            @functools.wraps(fn)
            async def _flat_wrapper(**kwargs: Any) -> Any:
                payload = _coerce_payload(kwargs)
                return await typed_async(payload)
        else:
            typed_sync: Callable[[InputModelT], Any] = cast(Callable[[InputModelT], Any], fn)

            @functools.wraps(fn)
            def _flat_wrapper(**kwargs: Any) -> Any:
                payload = _coerce_payload(kwargs)
                return typed_sync(payload)

        setattr(_flat_wrapper, "_mcp_flat_input_model", model_in)
        if model_out is not inspect.Signature.empty:
            setattr(_flat_wrapper, "_mcp_flat_output_model", model_out)

        signature = _make_flat_signature_from_model(model_in, return_type=model_out)
        setattr(_flat_wrapper, "__signature__", signature)

        # Also provide parameter annotations to satisfy ParsedFunction.from_function
        def _build_param_annotations(model: type[BaseModel], *, return_type: Any) -> dict[str, Any]:
            out: dict[str, Any] = {}
            for pname, fld in model.model_fields.items():
                pann = fld.annotation
                field_kwargs: dict[str, Any] = {"description": fld.description}
                if fld.alias:
                    field_kwargs["alias"] = fld.alias
                annotated_type: Any = Any if pann in (inspect._empty, None) else pann
                out[pname] = Annotated[annotated_type, Field(**field_kwargs)]
            out["return"] = return_type
            return out

        _flat_wrapper.__annotations__ = _build_param_annotations(model_in, return_type=model_out)

        inferred_desc = description
        if inferred_desc is None:
            inferred_desc = inspect.getdoc(fn) or None

        # Only pass kwargs accepted by FastMCP.tool; structured_output is enforced here
        tool_kwargs = dict(
            name=(name or fn.__name__ or None),
            title=title,
            description=inferred_desc,
            annotations=annotations,
        )
        registered = register_tool(_flat_wrapper, tool_kwargs)
        return cast(Callable[[InputModelT], Any], registered)

    return outer


class FlatModelToolMixin:
    class _ToolOpts(BaseModel):
        name: str | None = None
        title: str | None = None
        description: str | None = None
        annotations: Any | None = None
        structured_output: bool = True
        model_config = ConfigDict(extra="ignore")

    def tool(self, *args: Any, **kwargs: Any):  # type: ignore[override]
        """Wrapper around FastMCP.tool with optional flat-model support.

        Uses a Pydantic model to validate/normalize known kwargs; unknown kwargs are
        ignored for flat-mode and passed through for non-flat mode.
        """
        flat: bool = bool(kwargs.pop("flat", False))
        flat_output_model = kwargs.pop("flat_output_model", None)
        wants_flat = flat or (flat_output_model is not None)
        if not wants_flat:
            base_tool = super().tool  # type: ignore[misc]
            return base_tool(*args, **kwargs)

        opts = self._ToolOpts.model_validate(kwargs or {})

        def _register(
            fn: Callable[..., Any], mcp_tool_kwargs: dict[str, Any]
        ) -> Callable[..., Any]:
            # Only pass kwargs accepted by FastMCP.tool overload (drop unsupported ones)
            base_tool = super(FlatModelToolMixin, self).tool  # type: ignore[misc]
            filtered = {k: v for k, v in mcp_tool_kwargs.items() if v is not None}
            decorator = base_tool(**filtered)
            decorator(fn)  # register
            return fn

        return cast(
            Callable[[Callable[..., Any]], Callable[..., Any]],
            _flat_model_decorator(
                _register,
                name=opts.name,
                title=opts.title,
                description=opts.description,
                annotations=opts.annotations,
                structured_output=opts.structured_output,
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
    output_model: type[BaseModel] | None = None,
):
    if isinstance(mcp, FlatModelToolMixin):
        mixin = cast(FlatModelToolMixin, mcp)
        return cast(
            Callable[[Callable[..., Any]], Callable[..., Any]],
            mixin.tool(
                name=name,
                title=title,
                description=description,
                annotations=annotations,
                structured_output=structured_output,
                flat=True,
                flat_output_model=output_model,
            ),
        )

    def _register(fn: Callable[..., Any], mcp_tool_kwargs: dict[str, Any]) -> Callable[..., Any]:
        decorator = cast(
            Callable[[Callable[..., Any]], Callable[..., Any]], mcp.tool(**mcp_tool_kwargs)
        )
        decorator(fn)  # register
        return fn

    return cast(
        Callable[[Callable[..., Any]], Callable[..., Any]],
        _flat_model_decorator(
            _register,
            name=name,
            title=title,
            description=description,
            annotations=annotations,
            structured_output=structured_output,
            output_model=output_model,
        ),
    )
