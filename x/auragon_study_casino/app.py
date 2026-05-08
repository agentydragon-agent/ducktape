"""Study Casino backend — Y.Doc-backed multi-device sync.

The wire surface is one HTTP endpoint, plus health and the static
frontend. Clients (the Yjs `Y.Doc` running in the React PWA) sync
their local doc against the server's canonical doc using two binary
blobs encoded as base64 in a JSON envelope:

    POST /sync
      body: { state_vector_b64: str, update_b64: str }

      `state_vector_b64`  — Y.encodeStateVector(localDoc), the client's
                            knowledge of which ops it already has.
      `update_b64`        — Y.encodeStateAsUpdate(localDoc, lastServerSV),
                            the ops the client wants the server to merge.
                            May be empty ("") for a pure pull.

      → 200 { update_b64: str, state_vector_b64: str }
            on success: server merged the client's update, applied
            validators, persisted, and is returning the binary update
            the client still needs to catch up to current canonical.

      → 409 { rejection: { rule: str, message: str } }
            on validation failure: canonical is unchanged, the client
            should undo its last local transaction (Y.UndoManager) and
            surface the rule + message in a SyncIcon toast.

User-facing state still lives in the Y.Doc. Economy-changing operations are
server-authoritative: action endpoints validate, log, mutate the canonical
Y.Doc, and return the Y update for the caller. Direct client syncs that would
change `balance` or `prize_log` are rejected with `rule="server_authority"`.

Multi-user: each authenticated user gets a separate SQLite database
(`casino-<username>.db`). When OIDC is not configured the app falls
back to a single "default" user, keeping existing tests working.
"""

import asyncio
import base64
import json
import logging
import re
import sys
import time
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Annotated

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pycrdt import Map
from pydantic import BaseModel, Field

from x.auragon_study_casino.actions import (
    ActionResponse,
    AddPastSessionRequest,
    BlackjackDealRequest,
    BlackjackHandRequest,
    ConvertRequest,
    DeleteSessionRequest,
    EditSessionRequest,
    ImportRequest,
    PrizeRedeemRequest,
    ResetRequest,
    RouletteSpinRequest,
    SessionCompleteRequest,
    SlotsSpinRequest,
)
from x.auragon_study_casino.auth import create_oidc_router, decode_session_token, make_current_user_dep
from x.auragon_study_casino.config import Settings
from x.auragon_study_casino.events import GameEventRead
from x.auragon_study_casino.games import (
    RNG_VERSION,
    SecretsRandom,
    dealer_play,
    draw_cards,
    hand_value,
    is_blackjack,
    make_shoe,
    public_blackjack_state,
    settle_blackjack,
    spin_roulette,
    spin_slots,
)
from x.auragon_study_casino.models import BlackjackHandRow
from x.auragon_study_casino.store import Accepted, ActionMutation, ActionRejectedError, DocStore, Rejected

logger = logging.getLogger(__name__)

# Only allow filesystem-safe characters in usernames to prevent path traversal.
_SAFE_USERNAME = re.compile(r"^[a-zA-Z0-9._@-]{1,64}$")

# Maximum base64 payload length accepted over WebSocket — matches HTTP /sync.
_WS_PAYLOAD_LIMIT = 4 * 1024 * 1024


class _WSManager:
    """Per-user WebSocket registry for server-push fan-out across tabs."""

    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = defaultdict(set)

    def add(self, username: str, ws: WebSocket) -> None:
        self._connections[username].add(ws)

    def remove(self, username: str, ws: WebSocket) -> None:
        self._connections[username].discard(ws)

    async def push(self, username: str, message: dict, exclude: WebSocket | None = None) -> None:
        """Fan out `message` to every connected client for `username` except `exclude`."""
        dead: list[WebSocket] = []
        for ws in list(self._connections.get(username, ())):
            if ws is exclude:
                continue
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._connections[username].discard(ws)


class SyncRequest(BaseModel):
    state_vector_b64: str = Field(min_length=0, max_length=4 * 1024 * 1024)
    update_b64: str = Field(min_length=0, max_length=4 * 1024 * 1024)


class SyncSuccess(BaseModel):
    update_b64: str
    state_vector_b64: str


class SyncRejection(BaseModel):
    rule: str
    message: str


class SyncRejectionEnvelope(BaseModel):
    rejection: SyncRejection


def _credits(casino) -> int:
    return int(casino.balance.get("credits", 0))


def _tokens(casino) -> int:
    return int(casino.balance.get("tokens", 0))


def _set_balance(casino, *, credits: int | None = None, tokens: int | None = None) -> None:
    if credits is not None:
        casino.balance["credits"] = int(credits)
    if tokens is not None:
        casino.balance["tokens"] = int(tokens)


def _require_credits(casino, amount: int) -> None:
    if amount <= 0:
        raise ActionRejectedError("invalid_wager", "wager must be positive")
    if _credits(casino) < amount:
        raise ActionRejectedError("insufficient_credits", f"need {amount} credits; have {_credits(casino)}")


def _session_minutes(session) -> int:
    return int(session.get("seconds", 0)) // 60


def _mutate_blackjack_step(casino, s, hand_id: str, move: str, rng: SecretsRandom) -> ActionMutation:
    row = s.get(BlackjackHandRow, hand_id)
    if row is None or row.status != "playing":
        raise ActionRejectedError("blackjack_hand", "active blackjack hand not found")
    shoe = json.loads(row.shoe_json)
    player = json.loads(row.player_json)
    dealer = json.loads(row.dealer_json)
    current_wager = int(row.current_wager_credits)
    settlement = None

    if move == "hit":
        drawn, shoe = draw_cards(shoe, 1)
        player = [*player, *drawn]
        if hand_value(player) > 21:
            settlement = settle_blackjack(player, dealer, current_wager)
        elif hand_value(player) == 21:
            dealer, shoe = dealer_play(dealer, shoe)
            settlement = settle_blackjack(player, dealer, current_wager)
    elif move == "stand":
        dealer, shoe = dealer_play(dealer, shoe)
        settlement = settle_blackjack(player, dealer, current_wager)
    elif move == "double":
        if len(player) != 2:
            raise ActionRejectedError("blackjack_double", "double is only available on the first two cards")
        _require_credits(casino, current_wager)
        _set_balance(casino, credits=_credits(casino) - current_wager)
        current_wager *= 2
        drawn, shoe = draw_cards(shoe, 1)
        player = [*player, *drawn]
        if hand_value(player) <= 21:
            dealer, shoe = dealer_play(dealer, shoe)
        settlement = settle_blackjack(player, dealer, current_wager)
    else:
        raise ActionRejectedError("blackjack_move", f"unsupported blackjack move {move!r}")

    status = "done" if settlement is not None else "playing"
    if settlement is not None and settlement.payout_tokens:
        _set_balance(casino, tokens=_tokens(casino) + settlement.payout_tokens)

    row.status = status
    row.updated_at_ms = int(time.time() * 1000)
    row.current_wager_credits = current_wager
    row.shoe_json = json.dumps(shoe, separators=(",", ":"))
    row.player_json = json.dumps(player, separators=(",", ":"))
    row.dealer_json = json.dumps(dealer, separators=(",", ":"))
    row.result_json = json.dumps(settlement.outcome, separators=(",", ":")) if settlement else None

    result = public_blackjack_state(
        hand_id=hand_id, status=status, player=player, dealer=dealer, current_wager=current_wager, settlement=settlement
    )
    game_event = None
    if settlement is not None:
        game_event = {
            "game": "blackjack",
            "wager_credits": current_wager,
            "payout_tokens": settlement.payout_tokens,
            "outcome": settlement.outcome
            | {"initial_wager": row.wager_credits, "doubled": current_wager > row.wager_credits},
        }
    return ActionMutation(
        result=result,
        details={"hand_id": hand_id, "move": move},
        game_event=game_event,
        rng_version=RNG_VERSION if move in {"hit", "double"} else None,
    )


def create_app(settings: Settings) -> FastAPI:
    data_dir = settings.data_dir
    frontend_dist = settings.frontend_dist_dir or (Path(__file__).parent / "frontend" / "dist")

    # Per-user DocStore registry. Keys are sanitised usernames; stores are
    # created lazily on first request for that user.
    stores: dict[str, DocStore] = {}

    def get_store(username: str) -> DocStore:
        if username not in stores:
            if not _SAFE_USERNAME.match(username):
                raise HTTPException(status_code=400, detail=f"invalid username: {username!r}")
            stores[username] = DocStore(data_dir / f"casino-{username}.db")
        return stores[username]

    oidc = settings.oidc_config()
    current_user_dep = make_current_user_dep(oidc.session_secret if oidc else None)
    ws_manager = _WSManager()

    app = FastAPI(title="Study Casino", docs_url=None, redoc_url=None)
    app.state.current_user_dep = current_user_dep

    if oidc:
        app.include_router(
            create_oidc_router(
                issuer=oidc.issuer,
                client_id=oidc.client_id,
                client_secret=oidc.client_secret,
                session_secret=oidc.session_secret,
                public_url=oidc.public_url,
            )
        )

    def decode_state_vector(raw: str) -> bytes | None:
        if not raw:
            return None
        try:
            return base64.b64decode(raw)
        except (ValueError, TypeError) as e:
            raise HTTPException(status_code=400, detail=f"invalid state_vector_b64: {e}") from e

    async def commit_action(
        *,
        username: str,
        body,
        action_type: str,
        mutator,
        snapshot_reason: str | None = None,
        snapshot_note: str | None = None,
    ) -> ActionResponse:
        store = get_store(username)
        try:
            result = await asyncio.to_thread(
                store.run_server_action,
                client_action_id=body.client_action_id,
                action_type=action_type,
                client_state_vector=decode_state_vector(body.state_vector_b64),
                mutator=mutator,
                snapshot_reason=snapshot_reason,
                snapshot_note=snapshot_note,
            )
        except ActionRejectedError as e:
            raise HTTPException(status_code=409, detail={"rule": e.rule, "message": e.message}) from e

        full_update = await asyncio.to_thread(store.get_update_for_client, None)
        await ws_manager.push(
            username, {"type": "server_push", "update_b64": base64.b64encode(full_update).decode("ascii")}
        )
        return ActionResponse(
            client_action_id=body.client_action_id,
            event=result.event,
            result=result.result,
            update_b64=base64.b64encode(result.server_update).decode("ascii"),
            state_vector_b64=base64.b64encode(result.server_state_vector).decode("ascii"),
            game_event=result.game_event,
        )

    @app.get("/healthz")
    def healthz() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/me")
    def me(username: Annotated[str, Depends(current_user_dep)]) -> dict[str, str]:
        return {"username": username}

    @app.get("/game-events")
    def list_game_events(
        username: Annotated[str, Depends(current_user_dep)], limit: Annotated[int, Query(ge=1, le=500)] = 100
    ) -> list[GameEventRead]:
        store = get_store(username)
        return store.list_game_events(limit=limit)

    @app.get("/ledger-events")
    def list_ledger_events(
        username: Annotated[str, Depends(current_user_dep)], limit: Annotated[int, Query(ge=1, le=500)] = 100
    ):
        store = get_store(username)
        return store.list_ledger_events(limit=limit)

    @app.post("/actions/session/complete")
    async def complete_session(
        body: SessionCompleteRequest, username: Annotated[str, Depends(current_user_dep)]
    ) -> ActionResponse:
        def mutate(casino, _session, now_ms: int) -> ActionMutation:
            session_id = body.session_id
            if session_id is None:
                active = [(sid, s) for sid, s in casino.sessions.items() if not s.get("ended_at_ms")]
                if len(active) != 1:
                    raise ActionRejectedError("active_session", "expected exactly one active session")
                session_id, session = active[0]
            else:
                session = casino.sessions.get(session_id)
            if session is None or session.get("ended_at_ms"):
                raise ActionRejectedError("active_session", "session is not active")
            ended_at = body.ended_at_ms or now_ms
            start = int(session.get("start_time_ms", ended_at))
            paused_duration = int(session.get("paused_duration_ms", 0))
            if session.get("paused") and session.get("pause_started_at_ms"):
                paused_duration += max(0, ended_at - int(session.get("pause_started_at_ms", ended_at)))
            seconds = max(0, int((ended_at - start - paused_duration) / 1000))
            if seconds <= 0:
                del casino.sessions[session_id]
                return ActionMutation(result={"session_id": session_id, "seconds": 0, "credits_earned": 0})
            minutes = seconds // 60
            session["seconds"] = seconds
            session["ended_at_ms"] = ended_at
            for key in ["start_time_ms", "paused", "paused_duration_ms", "pause_started_at_ms"]:
                if key in session:
                    del session[key]
            if minutes:
                _set_balance(casino, credits=_credits(casino) + minutes)
            return ActionMutation(
                result={"session_id": session_id, "seconds": seconds, "credits_earned": minutes},
                details={"subject": session.get("subject")},
            )

        return await commit_action(username=username, body=body, action_type="session.complete", mutator=mutate)

    @app.post("/actions/session/add-past")
    async def add_past_session(
        body: AddPastSessionRequest, username: Annotated[str, Depends(current_user_dep)]
    ) -> ActionResponse:
        def mutate(casino, _session, _now_ms: int) -> ActionMutation:
            session_id = body.session_id or f"manual-{uuid.uuid4()}"
            if casino.sessions.get(session_id) is not None:
                raise ActionRejectedError("session_id", "session id already exists")
            sm: Map = Map()
            casino.sessions[session_id] = sm
            sm["subject"] = body.subject
            sm["seconds"] = body.seconds
            sm["ended_at_ms"] = body.ended_at_ms
            credits_earned = body.seconds // 60
            _set_balance(casino, credits=_credits(casino) + credits_earned)
            return ActionMutation(
                result={"session_id": session_id, "credits_earned": credits_earned},
                details={"subject": body.subject, "seconds": body.seconds},
            )

        return await commit_action(username=username, body=body, action_type="session.add_past", mutator=mutate)

    @app.post("/actions/session/edit")
    async def edit_session(
        body: EditSessionRequest, username: Annotated[str, Depends(current_user_dep)]
    ) -> ActionResponse:
        def mutate(casino, _session, _now_ms: int) -> ActionMutation:
            session = casino.sessions.get(body.session_id)
            if session is None or not session.get("ended_at_ms"):
                raise ActionRejectedError("session", "completed session not found")
            old_minutes = _session_minutes(session)
            if body.subject is not None:
                session["subject"] = body.subject
            if body.seconds is not None:
                session["seconds"] = body.seconds
            delta = _session_minutes(session) - old_minutes
            if delta:
                _set_balance(casino, credits=max(0, _credits(casino) + delta))
            return ActionMutation(
                result={"session_id": body.session_id, "credits_delta": delta},
                details={"subject": session.get("subject"), "seconds": int(session.get("seconds", 0))},
            )

        return await commit_action(username=username, body=body, action_type="session.edit", mutator=mutate)

    @app.post("/actions/session/delete")
    async def delete_session(
        body: DeleteSessionRequest, username: Annotated[str, Depends(current_user_dep)]
    ) -> ActionResponse:
        def mutate(casino, _session, _now_ms: int) -> ActionMutation:
            session = casino.sessions.get(body.session_id)
            if session is None or not session.get("ended_at_ms"):
                raise ActionRejectedError("session", "completed session not found")
            credits_delta = -_session_minutes(session)
            del casino.sessions[body.session_id]
            _set_balance(casino, credits=max(0, _credits(casino) + credits_delta))
            return ActionMutation(result={"session_id": body.session_id, "credits_delta": credits_delta})

        return await commit_action(username=username, body=body, action_type="session.delete", mutator=mutate)

    @app.post("/actions/convert")
    async def convert(body: ConvertRequest, username: Annotated[str, Depends(current_user_dep)]) -> ActionResponse:
        def mutate(casino, _session, _now_ms: int) -> ActionMutation:
            _require_credits(casino, body.amount)
            _set_balance(casino, credits=_credits(casino) - body.amount, tokens=_tokens(casino) + body.amount)
            return ActionMutation(result={"amount": body.amount})

        return await commit_action(username=username, body=body, action_type="convert", mutator=mutate)

    @app.post("/actions/prize/redeem")
    async def redeem_prize(
        body: PrizeRedeemRequest, username: Annotated[str, Depends(current_user_dep)]
    ) -> ActionResponse:
        def mutate(casino, _session, now_ms: int) -> ActionMutation:
            prize = casino.prizes.get(body.prize_id)
            if prize is None:
                raise ActionRejectedError("prize", "prize not found")
            cost = int(prize.get("cost", 0))
            if cost <= 0:
                raise ActionRejectedError("prize", "prize cost must be positive")
            if _tokens(casino) < cost:
                raise ActionRejectedError("insufficient_tokens", f"need {cost} tokens; have {_tokens(casino)}")
            _set_balance(casino, tokens=_tokens(casino) - cost)

            entry: Map = Map()
            casino.prize_log.append(entry)
            redemption_id = f"r-{uuid.uuid4()}"
            entry["id"] = redemption_id
            entry["name"] = prize.get("name")
            entry["cost"] = cost
            entry["at_ms"] = now_ms
            return ActionMutation(
                result={"redemption_id": redemption_id, "prize_id": body.prize_id, "cost": cost},
                details={"name": prize.get("name")},
            )

        return await commit_action(username=username, body=body, action_type="prize.redeem", mutator=mutate)

    @app.post("/actions/import")
    async def import_data(body: ImportRequest, username: Annotated[str, Depends(current_user_dep)]) -> ActionResponse:
        store = get_store(username)

        def mutate(_casino, _session, _now_ms: int) -> ActionMutation:
            replacement = store.build_import_casino(body.data)
            return ActionMutation(result={"imported": True}, replacement=replacement)

        return await commit_action(
            username=username, body=body, action_type="data.import", mutator=mutate, snapshot_reason="before_import"
        )

    @app.post("/actions/reset")
    async def reset_data(body: ResetRequest, username: Annotated[str, Depends(current_user_dep)]) -> ActionResponse:
        store = get_store(username)

        def mutate(_casino, _session, _now_ms: int) -> ActionMutation:
            return ActionMutation(result={"reset": True}, replacement=store.build_reset_casino())

        return await commit_action(
            username=username, body=body, action_type="data.reset", mutator=mutate, snapshot_reason="before_reset"
        )

    @app.post("/casino/slots/spin")
    async def slots_spin(body: SlotsSpinRequest, username: Annotated[str, Depends(current_user_dep)]) -> ActionResponse:
        rng = SecretsRandom()

        def mutate(casino, _session, _now_ms: int) -> ActionMutation:
            _require_credits(casino, body.wager_credits)
            settlement = spin_slots(body.wager_credits, rng)
            _set_balance(
                casino, credits=_credits(casino) - body.wager_credits, tokens=_tokens(casino) + settlement.payout_tokens
            )
            result = settlement.outcome | {"payout_tokens": settlement.payout_tokens}
            return ActionMutation(
                result=result,
                details={"wager_credits": body.wager_credits},
                game_event={
                    "game": "slots",
                    "wager_credits": body.wager_credits,
                    "payout_tokens": settlement.payout_tokens,
                    "outcome": settlement.outcome,
                },
                rng_version=RNG_VERSION,
            )

        return await commit_action(username=username, body=body, action_type="casino.slots.spin", mutator=mutate)

    @app.post("/casino/roulette/spin")
    async def roulette_spin(
        body: RouletteSpinRequest, username: Annotated[str, Depends(current_user_dep)]
    ) -> ActionResponse:
        rng = SecretsRandom()

        def mutate(casino, _session, _now_ms: int) -> ActionMutation:
            _require_credits(casino, body.wager_credits)
            try:
                settlement = spin_roulette(body.wager_credits, body.bet_type, body.bet_number, rng)
            except ValueError as e:
                raise ActionRejectedError("roulette_bet", str(e)) from e
            _set_balance(
                casino, credits=_credits(casino) - body.wager_credits, tokens=_tokens(casino) + settlement.payout_tokens
            )
            result = settlement.outcome | {"payout_tokens": settlement.payout_tokens}
            return ActionMutation(
                result=result,
                details={"wager_credits": body.wager_credits, "bet_type": body.bet_type, "bet_number": body.bet_number},
                game_event={
                    "game": "roulette",
                    "wager_credits": body.wager_credits,
                    "payout_tokens": settlement.payout_tokens,
                    "outcome": settlement.outcome,
                },
                rng_version=RNG_VERSION,
            )

        return await commit_action(username=username, body=body, action_type="casino.roulette.spin", mutator=mutate)

    @app.post("/casino/blackjack/deal")
    async def blackjack_deal(
        body: BlackjackDealRequest, username: Annotated[str, Depends(current_user_dep)]
    ) -> ActionResponse:
        rng = SecretsRandom()

        def mutate(casino, s, now_ms: int) -> ActionMutation:
            _require_credits(casino, body.wager_credits)
            shoe = make_shoe(rng)
            p1, shoe = draw_cards(shoe, 1)
            d1, shoe = draw_cards(shoe, 1)
            p2, shoe = draw_cards(shoe, 1)
            d2, shoe = draw_cards(shoe, 1)
            player = [*p1, *p2]
            dealer = [*d1, *d2]
            _set_balance(casino, credits=_credits(casino) - body.wager_credits)
            hand_id = f"bj-{uuid.uuid4()}"
            status = "playing"
            settlement = None
            if is_blackjack(player) or is_blackjack(dealer):
                settlement = settle_blackjack(player, dealer, body.wager_credits)
                if settlement.payout_tokens:
                    _set_balance(casino, tokens=_tokens(casino) + settlement.payout_tokens)
                status = "done"
            row = BlackjackHandRow(
                id=hand_id,
                created_at_ms=now_ms,
                updated_at_ms=now_ms,
                status=status,
                wager_credits=body.wager_credits,
                current_wager_credits=body.wager_credits,
                credits_before=_credits(casino) + body.wager_credits,
                tokens_before=_tokens(casino) - (settlement.payout_tokens if settlement else 0),
                shoe_json=json.dumps(shoe, separators=(",", ":")),
                player_json=json.dumps(player, separators=(",", ":")),
                dealer_json=json.dumps(dealer, separators=(",", ":")),
                result_json=json.dumps(settlement.outcome, separators=(",", ":")) if settlement else None,
            )
            s.add(row)
            result = public_blackjack_state(
                hand_id=hand_id,
                status=status,
                player=player,
                dealer=dealer,
                current_wager=body.wager_credits,
                settlement=settlement,
            )
            game_event = (
                {
                    "game": "blackjack",
                    "wager_credits": body.wager_credits,
                    "payout_tokens": settlement.payout_tokens,
                    "outcome": settlement.outcome | {"initial_wager": body.wager_credits, "doubled": False},
                }
                if settlement
                else None
            )
            return ActionMutation(
                result=result,
                details={"hand_id": hand_id, "wager_credits": body.wager_credits},
                game_event=game_event,
                rng_version=RNG_VERSION,
            )

        return await commit_action(username=username, body=body, action_type="blackjack.deal", mutator=mutate)

    @app.post("/casino/blackjack/hit")
    async def blackjack_hit(
        body: BlackjackHandRequest, username: Annotated[str, Depends(current_user_dep)]
    ) -> ActionResponse:
        rng = SecretsRandom()

        def mutate(casino, s, _now_ms: int) -> ActionMutation:
            return _mutate_blackjack_step(casino, s, body.hand_id, "hit", rng)

        return await commit_action(username=username, body=body, action_type="blackjack.hit", mutator=mutate)

    @app.post("/casino/blackjack/stand")
    async def blackjack_stand(
        body: BlackjackHandRequest, username: Annotated[str, Depends(current_user_dep)]
    ) -> ActionResponse:
        rng = SecretsRandom()

        def mutate(casino, s, _now_ms: int) -> ActionMutation:
            return _mutate_blackjack_step(casino, s, body.hand_id, "stand", rng)

        return await commit_action(username=username, body=body, action_type="blackjack.stand", mutator=mutate)

    @app.post("/casino/blackjack/double")
    async def blackjack_double(
        body: BlackjackHandRequest, username: Annotated[str, Depends(current_user_dep)]
    ) -> ActionResponse:
        rng = SecretsRandom()

        def mutate(casino, s, _now_ms: int) -> ActionMutation:
            return _mutate_blackjack_step(casino, s, body.hand_id, "double", rng)

        return await commit_action(username=username, body=body, action_type="blackjack.double", mutator=mutate)

    @app.websocket("/ws")
    async def websocket_sync(ws: WebSocket) -> None:
        """WebSocket sync endpoint.

        Protocol (JSON, both directions):
          Client → server: {"type":"sync","state_vector_b64":"...","update_b64":"..."}
          Server → client: {"type":"accepted","update_b64":"...","state_vector_b64":"..."}
                         | {"type":"rejected","rule":"...","message":"..."}
                         | {"type":"server_push","update_b64":"..."}  (fan-out from another tab)
                         | {"type":"error","code":N,"message":"..."}
        """
        # Auth: read the HMAC-signed session cookie from the WS upgrade request.
        if oidc is not None:
            casino_session = ws.cookies.get("casino_session")
            if not casino_session:
                await ws.close(code=4001, reason="not authenticated")
                return
            username = decode_session_token(casino_session, oidc.session_secret)
            if username is None:
                await ws.close(code=4001, reason="session invalid or expired")
                return
        else:
            username = "default"

        await ws.accept()
        store = get_store(username)
        ws_manager.add(username, ws)
        logger.info("ws connected: user=%s", username)

        # Bootstrap the client with the full canonical state immediately.
        init_update, init_sv = await asyncio.to_thread(store.snapshot_for_client, None)
        await ws.send_json(
            {
                "type": "accepted",
                "update_b64": base64.b64encode(init_update).decode("ascii"),
                "state_vector_b64": base64.b64encode(init_sv).decode("ascii"),
            }
        )

        try:
            while True:
                try:
                    data = await ws.receive_json()
                except Exception:
                    break

                if data.get("type") != "sync":
                    continue

                sv_raw = data.get("state_vector_b64") or ""
                upd_raw = data.get("update_b64") or ""
                if len(sv_raw) > _WS_PAYLOAD_LIMIT or len(upd_raw) > _WS_PAYLOAD_LIMIT:
                    await ws.send_json({"type": "error", "code": 413, "message": "payload too large"})
                    continue

                try:
                    client_sv = base64.b64decode(sv_raw)
                    client_update = base64.b64decode(upd_raw)
                except (ValueError, TypeError) as e:
                    await ws.send_json({"type": "error", "code": 400, "message": f"invalid base64: {e}"})
                    continue

                if not client_update:
                    # Pure pull — no new data from client.
                    srv_update, srv_sv = await asyncio.to_thread(store.snapshot_for_client, client_sv)
                    await ws.send_json(
                        {
                            "type": "accepted",
                            "update_b64": base64.b64encode(srv_update).decode("ascii"),
                            "state_vector_b64": base64.b64encode(srv_sv).decode("ascii"),
                        }
                    )
                    continue

                result = await asyncio.to_thread(store.apply_client_update, client_update, client_sv)

                if isinstance(result, Rejected):
                    logger.info("ws sync rejected: user=%s rule=%s", username, result.rule)
                    await ws.send_json({"type": "rejected", "rule": result.rule, "message": result.message})
                    continue

                assert isinstance(result, Accepted)
                logger.info("ws sync accepted: user=%s", username)

                await ws.send_json(
                    {
                        "type": "accepted",
                        "update_b64": base64.b64encode(result.server_update).decode("ascii"),
                        "state_vector_b64": base64.b64encode(result.server_state_vector).decode("ascii"),
                    }
                )

                # Fan the full canonical state out to every other connected tab for this user.
                full_update = await asyncio.to_thread(store.get_update_for_client, None)
                await ws_manager.push(
                    username,
                    {"type": "server_push", "update_b64": base64.b64encode(full_update).decode("ascii")},
                    exclude=ws,
                )

        except WebSocketDisconnect:
            pass
        finally:
            ws_manager.remove(username, ws)
            logger.info("ws disconnected: user=%s", username)

    @app.post("/sync", response_model=SyncSuccess)
    def sync(body: SyncRequest, username: Annotated[str, Depends(current_user_dep)]) -> SyncSuccess | JSONResponse:
        store = get_store(username)

        try:
            client_sv = base64.b64decode(body.state_vector_b64)
            client_update = base64.b64decode(body.update_b64)
        except (ValueError, TypeError) as e:
            raise HTTPException(status_code=400, detail=f"invalid base64: {e}") from e

        if not client_update:
            server_update, server_sv = store.snapshot_for_client(client_sv)
            return SyncSuccess(
                update_b64=base64.b64encode(server_update).decode("ascii"),
                state_vector_b64=base64.b64encode(server_sv).decode("ascii"),
            )

        result = store.apply_client_update(client_update, client_sv)
        if isinstance(result, Rejected):
            logger.info("sync rejected: user=%s rule=%s", username, result.rule)
            envelope = SyncRejectionEnvelope(rejection=SyncRejection(rule=result.rule, message=result.message))
            return JSONResponse(status_code=409, content=envelope.model_dump())

        assert isinstance(result, Accepted)
        logger.info("sync accepted: user=%s", username)
        return SyncSuccess(
            update_b64=base64.b64encode(result.server_update).decode("ascii"),
            state_vector_b64=base64.b64encode(result.server_state_vector).decode("ascii"),
        )

    if frontend_dist.exists():
        app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")
    else:
        logger.warning("frontend dist dir %s not found — serving API only", frontend_dist)

    return app


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s", stream=sys.stderr)
    settings = Settings()
    logger.info("study casino listening on %s:%d, data_dir=%s", settings.host, settings.port, settings.data_dir)
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
