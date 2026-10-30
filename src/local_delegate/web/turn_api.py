"""`/api/turn/*`: the daemon's turn endpoint for operations of another machine (PC+Mac, lot 3).

Three `POST` routes (REQ-010) over `turn_leases`. The handlers are **sync** (`def`): FastAPI runs
them in Starlette's threadpool, never on the event loop that serves `/mcp`, so a long wait of up
to `heartbeat_s` blocks one worker thread and nothing else.

Authentication (REQ-016), in `_require_turn_client`, because `PortToken` lets these three exact
routes through (`auth.TURN_ROUTES`):

- `Authorization: Bearer` only: no Basic and no session cookie (a browser must not use them);
- the secret is the port token (`LOCAL_DELEGATE_WEB_TOKEN`) **or** the backend's key
  (`LOCAL_DELEGATE_API_KEY`, the one the remote client already sends to `:9292`): whoever has the
  latter can already take the GPU directly, so the turn gives nothing new. Compared in constant
  time; never logged and never returned;
- with neither configured, `403 {"error": "turn_needs_secret"}`: `tailscale serve` connects from
  127.0.0.1, so loopback authenticates nothing;
- no `Origin` header and `Content-Type: application/json`, like `_require_hook_client`;
- body of 4 KB at most, strict models (`extra="forbid"`), names cleaned like
  `config.clean_machine_name` and refused when empty (REQ-017).

`LOCAL_DELEGATE_TURN_SERVER=off` answers 404, as an old daemon.
"""

from __future__ import annotations

import hmac
import json
from http import HTTPStatus
from typing import Annotated, Literal, TypeVar

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    ValidationError,
)

from .. import config, token_source, turn_leases
from .auth import TURN_ACQUIRE_PATH, TURN_HEARTBEAT_PATH, TURN_RELEASE_PATH

#: Largest body accepted (REQ-017).
MAX_BODY_BYTES = 4096
#: Most models in a `chain` and in a `waiting_backend` detail.
_MAX_ITEMS = 16


class TurnError(Exception):
    """An answer with an error code and nothing else: no trace, no echo of the request."""

    def __init__(self, status: int, code: str) -> None:
        super().__init__(code)
        self.status = status
        self.code = code


def _error_body(error: TurnError) -> dict[str, str]:
    if error.status == 404:
        # The same body as a daemon without this endpoint (FastAPI's own 404).
        return {"detail": HTTPStatus.NOT_FOUND.phrase}
    return {"error": error.code}


async def _turn_error(_request: Request, error: Exception) -> JSONResponse:
    assert isinstance(error, TurnError)
    return JSONResponse(_error_body(error), status_code=error.status)


def _bearer(request: Request) -> str | None:
    scheme, _, rest = (request.headers.get("authorization") or "").partition(" ")
    rest = rest.strip()
    if scheme.lower() != "bearer" or not rest:
        return None
    return rest


def _matches(presented: str, secrets_: list[str]) -> bool:
    given = presented.encode("utf-8")
    found = False
    for secret in secrets_:
        # Every secret is compared, not only until the first match: same time either way.
        found |= hmac.compare_digest(given, secret.encode("utf-8"))
    return found


async def _require_turn_client(request: Request) -> None:
    if not config.TURN_SERVER:
        raise TurnError(404, "not_found")
    if request.headers.get("origin") is not None:
        raise TurnError(403, "origin_not_allowed")
    secrets_ = [s for s in (token_source.daemon_token(), token_source.api_key()) if s]
    if not secrets_:
        raise TurnError(403, "turn_needs_secret")
    presented = _bearer(request)
    if presented is None or not _matches(presented, secrets_):
        raise TurnError(401, "unauthorized")
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type != "application/json":
        raise TurnError(415, "unsupported_media_type")


async def _json_body(request: Request) -> dict:
    """The body as a JSON object, read with the 4 KB cap (also without `Content-Length`)."""
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            if int(declared) > MAX_BODY_BYTES:
                raise TurnError(413, "body_too_large")
        except ValueError:
            raise TurnError(400, "bad_request") from None
    data = bytearray()
    async for chunk in request.stream():
        data += chunk
        if len(data) > MAX_BODY_BYTES:
            raise TurnError(413, "body_too_large")
    try:
        body = json.loads(bytes(data))
    except (ValueError, UnicodeDecodeError):
        raise TurnError(400, "bad_request") from None
    if not isinstance(body, dict):
        raise TurnError(400, "bad_request")
    return body


_Text = Annotated[StrictStr, Field(max_length=256)]
_Count = Annotated[StrictInt, Field(ge=0, le=10**12)]


_M = TypeVar("_M", bound=BaseModel)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AcquireBody(_Strict):
    op: _Text
    host: _Text
    tool: _Text
    model: _Text
    role: _Text = ""
    chain: list[_Text] = Field(default_factory=list, max_length=_MAX_ITEMS)
    chars_in: _Count = 0
    chunks: _Count | None = None


class HeartbeatBody(_Strict):
    lease: Annotated[StrictStr, Field(max_length=128)]
    in_backend: StrictBool = False
    waiting_backend: (
        StrictBool | Annotated[dict[_Text, _Text], Field(max_length=_MAX_ITEMS)] | None
    ) = None
    chunk: _Count | None = None
    phase: Literal["map", "reduce", "retry"] | None = None


class ReleaseBody(_Strict):
    lease: Annotated[StrictStr, Field(max_length=128)]


def _parse(model: type[_M], body: dict) -> _M:
    try:
        return model.model_validate(body)
    except ValidationError:
        raise TurnError(400, "bad_request") from None


def _name(raw: str) -> str:
    """A name cleaned like `config.clean_machine_name`; empty is a 400 (REQ-017)."""
    clean = config.clean_machine_name(raw)
    if not clean:
        raise TurnError(400, "bad_request")
    return clean


def _optional_names(raw: list[str] | dict[str, str]) -> list[str]:
    return [c for c in (config.clean_machine_name(x) for x in raw) if c]


router = APIRouter(dependencies=[Depends(_require_turn_client)])


@router.post(TURN_ACQUIRE_PATH)
def acquire(body: Annotated[dict, Depends(_json_body)]) -> JSONResponse:
    data = _parse(AcquireBody, body)
    request = turn_leases.AcquireRequest(
        op=_name(data.op),
        host=_name(data.host),
        tool=_name(data.tool),
        model=_name(data.model),
        role=config.clean_machine_name(data.role),
        chain=tuple(_optional_names(data.chain)),
        chars_in=data.chars_in,
        chunks=data.chunks,
    )
    try:
        answer = turn_leases.table().acquire(request)
    except turn_leases.TooManyLeases:
        raise TurnError(429, "too_many_leases") from None
    return JSONResponse(answer)


@router.post(TURN_HEARTBEAT_PATH)
def heartbeat(body: Annotated[dict, Depends(_json_body)]) -> JSONResponse:
    data = _parse(HeartbeatBody, body)
    waiting: dict[str, str] | bool | None = data.waiting_backend
    if isinstance(waiting, dict):
        waiting = {
            config.clean_machine_name(k): config.clean_machine_name(v)[:16]
            for k, v in waiting.items()
            if config.clean_machine_name(k)
        }
    beat = turn_leases.Beat(
        in_backend=data.in_backend, waiting_backend=waiting, chunk=data.chunk, phase=data.phase
    )
    return JSONResponse(turn_leases.table().heartbeat(data.lease, beat))


@router.post(TURN_RELEASE_PATH)
def release(body: Annotated[dict, Depends(_json_body)]) -> JSONResponse:
    data = _parse(ReleaseBody, body)
    return JSONResponse(turn_leases.table().release(data.lease))


def install(app: FastAPI) -> None:
    """Mount the three routes and their error answers on the dashboard's app."""
    app.include_router(router)
    app.add_exception_handler(TurnError, _turn_error)
