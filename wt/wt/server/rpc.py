from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Generic, Protocol, TypeVar, cast

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

    def emit(self, event: EventT) -> None:
        if not self._writer:
            return
        try:
            self._writer.write((event.model_dump_json() + "\n").encode())
        except Exception:
            pass


class RpcError(Exception):
    def __init__(self, code: int, message: str, data: Any | None = None):
        super().__init__(message)
        self.code = code
        self.data = data


Handler = Callable[[Context, Any], Awaitable[Any]]


class RpcRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, Callable[[Request, "WtDaemon", Any, float], Awaitable[Response | ErrorResponse]]] = {}

    def _wrap(self, method: str, params_model: type[ParamsT] | None, handler: Handler) -> None:
        async def _wrapped(req: Request, daemon: "WtDaemon", writer, start_time: float) -> Response | ErrorResponse:
            try:
                params = (
                    params_model.model_validate(req.params) if params_model is not None else None
                )
            except ValidationError as e:
                return create_error_response(ErrorCodes.INVALID_PARAMS, str(e), req.id)

            ctx = Context(
                daemon=daemon,
                start_time=start_time,
            )
            try:
                if params is None:
                    result = await cast(Callable[[Context], Awaitable[Any]], handler)(ctx)  # type: ignore[misc]
                else:
                    try:
                        stream = Stream(writer)
                        result = await cast(Callable[[Context, Any, Stream[Any]], Awaitable[Any]], handler)(ctx, params, stream)  # type: ignore[misc]
                    except TypeError:
                        result = await cast(Callable[[Context, Any], Awaitable[Any]], handler)(ctx, params)  # type: ignore[misc]
                return Response(result=result, id=req.id)
            except RpcError as e:
                return create_error_response(e.code, str(e), req.id, e.data)
            except Exception as e:
                import logging
                logging.getLogger(__name__).exception("Unhandled error in method %s", method)
                return create_error_response(ErrorCodes.INTERNAL_ERROR, f"Internal error: {e}", req.id)

        self._handlers[method] = _wrapped

    def method(self, name: str, *, params: type[ParamsT] | None = None):
        def deco(fn: Callable[..., Awaitable[Any]]):
            self._wrap(name, params, fn)
            return fn
        return deco

    # Alias: stream just records with same wrapper; handler can accept Stream third arg
    def stream(self, name: str, *, params: type[ParamsT]):
        return self.method(name, params=params)

    async def dispatch(self, req: Request, daemon: "WtDaemon", writer, start_time: float) -> Response | ErrorResponse:
        wrapped = self._handlers.get(req.method)
        if not wrapped:
            return create_error_response(
                ErrorCodes.METHOD_NOT_FOUND, f"Method '{req.method}' not found", req.id, req.id
            )
        return await wrapped(req, daemon, writer, start_time)


rpc = RpcRegistry()
