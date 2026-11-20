"""sales-claw pause patch — pause/resume a meeting bot's RECORDING while it stays in the room.

Added on top of the meeting-api from vexaai/vexa-lite:v0.12.28 (Apache-2.0), modelled on
``stop_router.py`` (whose auth, platform guard and row lookup it reuses):

  * ``POST /bots/{platform}/{native_meeting_id}/pause`` body ``{"at_ms": <epoch ms int>}`` → 202.
    Publishes ``{"action":"pause","at":at_ms,"meeting_id":id}`` on the bot's command channel (the one
    DELETE's ``leave`` uses), then deletes every segment of the meeting that touches the click from
    the live hash, ``transcriptions`` and the live feed, and tells live consumers (``retract``).
    ``at_ms`` is the CLICK time, which is why it must be an integer epoch-ms: the bot clamps anything
    else to "now" (later than the click), so it is rejected here with 422 instead.
  * ``POST /bots/{platform}/{native_meeting_id}/resume`` → 202. Publishes
    ``{"action":"resume","meeting_id":id}``.
  * ``store_pause_confirmation`` — the bot's confirmation (lifecycle.v1 event field
    ``aufnahme_pause: {pausiert, seit_ms}``) into ``meeting.data["aufnahme_pause"]``. Called by the
    lifecycle callback BEFORE the FSM step, because the bot confirms under its CURRENT status: a
    repeated status is an FSM no-op and a late lobby confirmation is a rejected edge — neither may
    lose it.

Every bot of the room gets the act (a sibling bot would otherwise keep transcribing). Logs carry
ids and counts only — no room names, no text.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException, Request

from .stop import leave_command_channel
from .stop_router import (
    _PLANNED_STATUSES,
    _SUPPORTED_PLATFORMS,
    CommandPublisher,
    _active_rows,
    _resolve_user_id,
)

# A plausible click in epoch MILLISECONDS: at/after 2001-09-09 and before 2286. Anything below is a
# seconds-scale value (or garbage) the bot would silently clamp.
MIN_AT_MS = 1_000_000_000_000
MAX_AT_MS = 10_000_000_000_000


def pause_command_payload(meeting_id: Any, at_ms: int) -> dict:
    return {"action": "pause", "at": at_ms, "meeting_id": meeting_id}


def resume_command_payload(meeting_id: Any) -> dict:
    return {"action": "resume", "meeting_id": meeting_id}


def _at_ms(body: Any) -> int:
    value = body.get("at_ms") if isinstance(body, dict) else None
    # `type(...) is int` on purpose: bool is an int subclass, and a float is not a click time.
    if type(value) is not int or not (MIN_AT_MS <= value < MAX_AT_MS):
        raise HTTPException(
            status_code=422,
            detail="body must be {\"at_ms\": <integer epoch milliseconds of the click>}",
        )
    return value


async def _live_rows(repo, user_id: int, platform: str, native_meeting_id: str) -> list:
    """Every row of the caller's room that HAS a bot (planned rows have none), newest first."""
    rows = await _active_rows(repo, user_id, platform, native_meeting_id)
    live = [row for row in rows if row.get("status") not in _PLANNED_STATUSES]
    if not live:
        raise HTTPException(status_code=404, detail="No active meeting for this bot")
    return live


def _check_platform(platform: str) -> None:
    if platform not in _SUPPORTED_PLATFORMS:
        raise HTTPException(
            status_code=422,
            detail=f"unsupported platform '{platform}' — must be one of: "
                   f"{', '.join(sorted(_SUPPORTED_PLATFORMS))}",
        )


def _log(event: str, *, level: str = "info", **fields) -> None:
    try:
        from ..obs import log_event

        log_event(event, audience="operator", level=level, span="bots.pause", fields=fields)
    except Exception:  # noqa: BLE001 — logging never fails a pause
        pass


async def _announce_retract(redis, meeting_id: int, segment_ids: list) -> None:
    """Tell live consumers to drop what was deleted — the same marker + frame the collector emits for
    a bot ``transcript_retract`` (``collector/ingest.py``). Best-effort: the data is already gone."""
    if redis is None or not segment_ids:
        return
    from ..collector.ingest import _mutable_channel, _transcript_stream

    try:
        await redis.xadd(_transcript_stream(meeting_id), {"type": "retract", "segment_ids": segment_ids})
        await redis.publish(_mutable_channel(meeting_id), json.dumps({
            "type": "transcript_retract", "meeting": {"id": meeting_id}, "segment_ids": segment_ids,
        }))
    except Exception as e:  # noqa: BLE001
        _log("pause_retract_announce_failed", level="warning", meeting_id=meeting_id,
             error_type=type(e).__name__)


def build_pause_router(repo, publisher: CommandPublisher, store, redis=None) -> APIRouter:
    """The pause/resume routes over the injected ``MeetingRepo``, ``CommandPublisher``, the
    ``TranscriptStore`` (``delete_segments_from``) and the optional collector ``RedisBus``."""
    router = APIRouter()

    @router.post("/bots/{platform}/{native_meeting_id}/pause", status_code=202)
    async def pause_bot(
        platform: str,
        native_meeting_id: str,
        request: Request,
        x_user_id: Optional[str] = Header(default=None),
    ):
        user_id = _resolve_user_id(x_user_id)
        _check_platform(platform)
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001 — not JSON
            body = None
        at_ms = _at_ms(body)
        rows = await _live_rows(repo, user_id, platform, native_meeting_id)

        # The act first — every second counts for the bot's gate. A bus fault does not skip the
        # deletion below: what is already stored must go either way.
        bus_error: Optional[Exception] = None
        try:
            for row in rows:
                await publisher.publish(
                    leave_command_channel(row["id"]),
                    json.dumps(pause_command_payload(row["id"], at_ms)),
                )
        except Exception as e:  # noqa: BLE001 — answered with 503 below
            bus_error = e

        deleted = 0
        try:
            for row in rows:
                ids = await store.delete_segments_from(row["id"], at_ms)
                deleted += len(ids)
                await _announce_retract(redis, row["id"], ids)
        except Exception as e:  # noqa: BLE001 — the caller must retry (idempotent)
            _log("pause_segment_delete_failed", level="error",
                 meeting_ids=[row["id"] for row in rows], error_type=type(e).__name__)
            raise HTTPException(
                status_code=503,
                detail="transcript store unavailable; segments from the pause may remain — retry",
            ) from e
        if bus_error is not None:
            _log("pause_publish_failed", level="error",
                 meeting_ids=[row["id"] for row in rows], error_type=type(bus_error).__name__)
            raise HTTPException(
                status_code=503,
                detail="command bus (redis) unavailable; the pause did not reach the bot — retry",
            ) from bus_error

        _log("pause_requested", meeting_ids=[row["id"] for row in rows], segments_deleted=deleted)
        return {
            "status": "pause_requested",
            "meeting_id": rows[0]["id"],
            "also_paused": [row["id"] for row in rows[1:]],
            "segments_deleted": deleted,
        }

    @router.post("/bots/{platform}/{native_meeting_id}/resume", status_code=202)
    async def resume_bot(
        platform: str,
        native_meeting_id: str,
        x_user_id: Optional[str] = Header(default=None),
    ):
        user_id = _resolve_user_id(x_user_id)
        _check_platform(platform)
        rows = await _live_rows(repo, user_id, platform, native_meeting_id)
        try:
            for row in rows:
                await publisher.publish(
                    leave_command_channel(row["id"]),
                    json.dumps(resume_command_payload(row["id"])),
                )
        except Exception as e:  # noqa: BLE001 — Redis unreachable → narrow, retryable failure
            _log("resume_publish_failed", level="error",
                 meeting_ids=[row["id"] for row in rows], error_type=type(e).__name__)
            raise HTTPException(
                status_code=503,
                detail="command bus (redis) unavailable; the resume did not reach the bot — retry",
            ) from e
        _log("resume_requested", meeting_ids=[row["id"] for row in rows])
        return {
            "status": "resume_requested",
            "meeting_id": rows[0]["id"],
            "also_resumed": [row["id"] for row in rows[1:]],
        }

    return router


def _valid_confirmation(value: Any) -> Optional[dict]:
    """``{"pausiert": bool, "seit_ms": number|null}`` (the bot's contract), extras dropped; else None."""
    if not isinstance(value, dict) or type(value.get("pausiert")) is not bool:
        return None
    seit = value.get("seit_ms")
    if seit is not None and (type(seit) not in (int, float) or seit != seit):
        return None
    return {"pausiert": value["pausiert"], "seit_ms": seit}


async def store_pause_confirmation(repo, session_uid: Any, value: Any) -> None:
    """Persist the bot's pause confirmation into ``meeting.data["aufnahme_pause"]`` by session uid,
    independent of the FSM step. Best-effort like the rest of the lifecycle callback: a malformed
    value or a store fault is logged and dropped — the sales-claw watchdog re-sends an unconfirmed
    act, and the bot confirms again."""
    confirmation = _valid_confirmation(value)
    if confirmation is None or not session_uid:
        _log("pause_confirmation_rejected", level="warning", reason="malformed")
        return
    merge = getattr(repo, "merge_meeting_data_by_session", None)
    if merge is None:
        _log("pause_confirmation_rejected", level="warning", reason="repo_without_merge")
        return
    try:
        meeting_id = await merge(session_uid=str(session_uid), patch={"aufnahme_pause": confirmation})
    except Exception as e:  # noqa: BLE001
        _log("pause_confirmation_persist_failed", level="warning", error_type=type(e).__name__)
        return
    _log("pause_confirmed", meeting_id=meeting_id, pausiert=confirmation["pausiert"])
