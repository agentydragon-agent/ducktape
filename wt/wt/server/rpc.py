from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Generic, Protocol, TypeVar, cast
import inspect
import logging

from pydantic import BaseModel, ValidationError

from ..shared.protocol import ErrorCodes, ErrorResponse, Request, Response, create_error_response

ParamsT = TypeVar("ParamsT", bound=BaseModel)
ResultT = TypeVar("ResultT")
EventT = TypeVar("EventT", bound=BaseModel)


@dataclass
class Context:
    daemon: "WtDaemon"
    start_time: float


class Emitter(Protocol[EventT]):
    def emit(self, event: EventT) -> None: ...


class Stream(Generic[EventT]):
    def __init__(self, writer):
        self._writer = writer
        self._error_logged = False

    def emit(self, event: EventT) -> None:
        if not self._writer:
            return
        try:
            self._writer.write((event.model_dump_json() + "\n").encode())
        except Exception:
            if not self._error_logged:
                logging.getLogger(__name__).debug("stream emit failed", exc_info=True)
                self._error_logged = True
            self._writer = None


class RpcError(Exception):
    def __init__(self, code: int, message: str, data: Any | None = None):
        super().__init__(message)
        self.code = code
        self.data = data


Handler = Callable[[Context, Any], Awaitable[Any]]


class RpcRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, Callable[[Request, "WtDaemon", Any, float], Awaitable[Response | ErrorResponse]]] = {}
        self._stream_methods: set[str] = set()

    def _wrap_method(self, method: str, params_model: type[ParamsT] | None, handler: Handler) -> None:
        async def _wrapped(req: Request, daemon: "WtDaemon", writer, start_time: float) -> Response | ErrorResponse:
            try:
                params = (
                    params_model.model_validate(req.params) if params_model is not None else None
                )
            except ValidationError as e:
                return create_error_response(ErrorCodes.INVALID_PARAMS, str(e), req.id)

            ctx = Context(daemon=daemon, start_time=start_time)
            try:
                if params is None:
                    result = await cast(Callable[[Context], Awaitable[Any]], handler)(ctx)  # type: ignore[misc]
                else:
                    result = await cast(Callable[[Context, Any], Awaitable[Any]], handler)(ctx, params)  # type: ignore[misc]
                return Response(result=result, id=req.id)
            except RpcError as e:
                return create_error_response(e.code, str(e), req.id, e.data)
            except Exception as e:
                logging.getLogger(__name__).exception("Unhandled error in method %s", method)
                return create_error_response(ErrorCodes.INTERNAL_ERROR, f"Internal error: {e}", req.id)

        self._handlers[method] = _wrapped

    def _wrap_stream(self, method: str, params_model: type[ParamsT], handler: Handler) -> None:
        async def _wrapped(req: Request, daemon: "WtDaemon", writer, start_time: float) -> Response | ErrorResponse:
            try:
                params = params_model.model_validate(req.params)
            except ValidationError as e:
                return create_error_response(ErrorCodes.INVALID_PARAMS, str(e), req.id)
            ctx = Context(daemon=daemon, start_time=start_time)
            try:
                stream = Stream(writer)
                result = await cast(Callable[[Context, Any, Stream[Any]], Awaitable[Any]], handler)(ctx, params, stream)  # type: ignore[misc]
                return Response(result=result, id=req.id)
            except RpcError as e:
                return create_error_response(e.code, str(e), req.id, e.data)
            except Exception as e:
                logging.getLogger(__name__).exception("Unhandled error in stream method %s", method)
                return create_error_response(ErrorCodes.INTERNAL_ERROR, f"Internal error: {e}", req.id)

        self._handlers[method] = _wrapped
        self._stream_methods.add(method)

    def method(self, name: str, *, params: type[ParamsT] | None = None):
        def deco(fn: Callable[..., Awaitable[Any]]):
            sig = inspect.signature(fn)
            if params is None:
                if len(sig.parameters) != 1:
                    raise TypeError(f"Method '{name}' must accept (ctx)")
                self._wrap_method(name, None, fn)
            else:
                if len(sig.parameters) != 2:
                    raise TypeError(f"Method '{name}' must accept (ctx, params)")
                self._wrap_method(name, params, fn)
            return fn
        return deco

    def stream(self, name: str, *, params: type[ParamsT]):
        def deco(fn: Callable[..., Awaitable[Any]]):
            sig = inspect.signature(fn)
            if len(sig.parameters) != 3:
                raise TypeError(f"Stream method '{name}' must accept (ctx, params, stream)")
            self._wrap_stream(name, params, fn)
            return fn
        return deco

    def list_methods(self) -> list[str]:
        return list(self._handlers.keys())

    async def dispatch(self, req: Request, daemon: "WtDaemon", writer, start_time: float) -> Response | ErrorResponse:
        wrapped = self._handlers.get(req.method)
        if not wrapped:
            return create_error_response(
                ErrorCodes.METHOD_NOT_FOUND, f"Method '{req.method}' not found", req.id, req.id
            )
        return await wrapped(req, daemon, writer, start_time)


rpc = RpcRegistry()
