"""sales-claw pause patch — POST /bots/{platform}/{native}/pause|resume + the bot's pause confirmation.

Added on top of the meeting-api from vexaai/vexa-lite:v0.12.28 (Apache-2.0); style of
``test_stop_route.py``. Drives the SAME shipped ``create_app`` with the in-memory fakes in their
production topology (fakeredis behind the live segment hash and the ``tc:meeting:{id}`` feed, the
production ``ingest`` and db-writer flush) and asserts:

  * the routes publish EXACTLY ``{"action":"pause","at":at_ms,"meeting_id":id}`` /
    ``{"action":"resume","meeting_id":id}`` on the bot's command channel (the same channel the
    DELETE leave uses) — ``at`` an integer epoch-ms, anything else is a 422;
  * auth exactly like DELETE /bots: identity header, own meeting only, 404 for a foreign/unknown one;
  * the safety deletion (ruling R4): every segment of THIS meeting that starts at/after the click or
    ends after it is gone from the durable rows, the live hash and the live feed; a segment ending at
    or before the click stays; another meeting is untouched;
  * the bot's ``aufnahme_pause`` confirmation lands in ``meeting.data`` even on a REPEATED status and
    even when the status edge itself is rejected (409 stays 409).

The Postgres legs of the SQL adapters run only when ``VEXA_PAUSE_TEST_PG_DSN`` points at a throwaway
database (the package suite has no Postgres; see the end of this file).
"""
from __future__ import annotations

import json
import os

import fakeredis.aioredis
import httpx
import pytest

from meeting_api import create_app
from meeting_api.bot_spawn.fakes import InMemoryMeetingRepo
from meeting_api.collector.db_writer import flush_meeting_segments, segments_hash_key
from meeting_api.collector.fakes import FakeRedisBus, InMemoryTranscriptStore
from meeting_api.collector.ingest import ingest
from meeting_api.lifecycle.stop_router import InMemoryCommandPublisher

USER = 7
NATIVE = "pausen-raum"
AT_MS = 1_784_000_000_000          # the click — epoch milliseconds (2026-07-14)
AT_S = AT_MS / 1000                # the same instant in the live pipeline's epoch SECONDS
LIFECYCLE = "/bots/internal/callback/lifecycle"


# ── harness ──────────────────────────────────────────────────────────────────────────────────────


class _Harness:
    def __init__(self):
        self.redis = fakeredis.aioredis.FakeRedis()
        self.bus = FakeRedisBus(self.redis)
        self.store = InMemoryTranscriptStore(redis_client=self.redis)
        self.repo = InMemoryMeetingRepo()
        self.pub = InMemoryCommandPublisher()
        self.app = create_app(
            meeting_repo=self.repo, command_publisher=self.pub,
            transcript_store=self.store, redis=self.bus,
        )

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://t")

    async def seed(self, *, user_id=USER, platform="jitsi", native=NATIVE, status="active"):
        """A meeting row (repo) + its transcript row (store) under ONE id, with a session."""
        m = await self.repo.create_meeting(
            user_id=user_id, platform=platform, native_meeting_id=native, data={}
        )
        sid = f"sess-{m['id']}"
        await self.repo.create_session(meeting_id=m["id"], session_uid=sid)
        if status != "requested":
            await self.repo.update_meeting_status(session_uid=sid, status=status)
        self.store.seed_meeting(
            user_id=user_id, platform=platform, native_meeting_id=native, meeting_id=m["id"]
        )
        return m

    async def ingest(self, meeting_id: int, segments: list[dict]) -> None:
        """Through the PRODUCTION ingest: live hash + tc:meeting feed + :mutable publish."""
        await ingest(self.store, self.bus, {"payload": json.dumps({
            "type": "transcription", "meeting_id": str(meeting_id), "uid": "sess",
            "platform": "jitsi", "segments": segments,
        })})

    async def flush(self, meeting_id: int) -> None:
        """The production db-writer flush (threshold 0) — hash → durable rows."""
        await flush_meeting_segments(self.redis, self.store, meeting_id, immutability_threshold=0)

    async def hash_ids(self, meeting_id: int) -> set[str]:
        raw = await self.redis.hgetall(segments_hash_key(meeting_id))
        return {k.decode() if isinstance(k, bytes) else k for k in raw}

    def durable_ids(self, meeting_id: int) -> set[str]:
        return set(self.store._meetings[meeting_id]["segments"])

    async def feed_segment_ids(self, meeting_id: int) -> set[str]:
        out: set[str] = set()
        for _eid, fields in await self.redis.xrange(f"tc:meeting:{meeting_id}"):
            payload = json.loads(fields[b"payload"])
            for seg in payload.get("segments") or []:
                out.add(seg["segment_id"])
        return out

    async def feed_retracts(self, meeting_id: int) -> list[list[str]]:
        out = []
        for _eid, fields in await self.redis.xrange(f"tc:meeting:{meeting_id}"):
            payload = json.loads(fields[b"payload"])
            if payload.get("type") == "retract":
                out.append(payload["segment_ids"])
        return out


def _seg(sid: str, start: float, end: float) -> dict:
    return {"segment_id": sid, "start": start, "end": end, "text": f"text {sid}",
            "language": "de", "speaker": "S", "completed": True}


H = {"x-user-id": str(USER)}


# ── the acts: exact payloads on the bot's command channel ────────────────────────────────────────


async def test_pause_publishes_the_exact_act_with_integer_epoch_ms():
    h = _Harness()
    m = await h.seed()
    async with h.client() as c:
        r = await c.post(f"/bots/jitsi/{NATIVE}/pause", json={"at_ms": AT_MS}, headers=H)
    assert r.status_code == 202, r.text
    assert r.json()["meeting_id"] == m["id"]
    assert len(h.pub.published) == 1
    chan, msg = h.pub.published[0]
    assert chan == f"bot_commands:meeting:{m['id']}", "must be the channel DELETE's leave uses"
    act = json.loads(msg)
    assert act == {"action": "pause", "at": AT_MS, "meeting_id": m["id"]}
    assert type(act["at"]) is int, "the bot clamps a non-integer/seconds `at` — it must be epoch ms"


async def test_resume_publishes_the_exact_act():
    h = _Harness()
    m = await h.seed()
    async with h.client() as c:
        r = await c.post(f"/bots/jitsi/{NATIVE}/resume", headers=H)
    assert r.status_code == 202, r.text
    assert h.pub.published == [
        (f"bot_commands:meeting:{m['id']}", json.dumps({"action": "resume", "meeting_id": m["id"]}))
    ]


@pytest.mark.parametrize("body", [
    {"at_ms": 1_784_000_000},             # SECONDS, not milliseconds — the bot would clamp it
    {"at_ms": 1_784_000_000_000.5},       # float
    {"at_ms": 1_784_000_000_000.0},       # float even when integral
    {"at_ms": "1784000000000"},           # string
    {"at_ms": True},                      # bool is an int subclass in Python — still not a time
    {"at_ms": None},
    {"at_ms": -1},
    {"at_ms": 10 ** 16},                  # far beyond any plausible epoch-ms
    {},
    [AT_MS],
])
async def test_pause_rejects_anything_but_plausible_integer_epoch_ms(body):
    h = _Harness()
    m = await h.seed()
    await h.ingest(m["id"], [_seg("late", AT_S + 5, AT_S + 6)])
    async with h.client() as c:
        r = await c.post(f"/bots/jitsi/{NATIVE}/pause", json=body, headers=H)
    assert r.status_code == 422, r.text
    assert h.pub.published == []
    assert await h.hash_ids(m["id"]) == {"late"}, "a rejected request must not delete anything"


async def test_pause_rejects_a_non_json_body():
    h = _Harness()
    await h.seed()
    async with h.client() as c:
        r = await c.post(f"/bots/jitsi/{NATIVE}/pause", content=b"at_ms=1", headers=H)
    assert r.status_code == 422
    assert h.pub.published == []


# ── auth exactly like DELETE /bots ───────────────────────────────────────────────────────────────


async def test_pause_and_resume_404_for_a_foreign_or_unknown_meeting():
    h = _Harness()
    m = await h.seed(user_id=USER)
    await h.ingest(m["id"], [_seg("late", AT_S + 5, AT_S + 6)])
    async with h.client() as c:
        foreign = await c.post(f"/bots/jitsi/{NATIVE}/pause", json={"at_ms": AT_MS},
                               headers={"x-user-id": "8"})
        unknown = await c.post("/bots/jitsi/nope/pause", json={"at_ms": AT_MS}, headers=H)
        foreign_resume = await c.post(f"/bots/jitsi/{NATIVE}/resume", headers={"x-user-id": "8"})
    assert (foreign.status_code, unknown.status_code, foreign_resume.status_code) == (404, 404, 404)
    assert h.pub.published == []
    assert await h.hash_ids(m["id"]) == {"late"}, "another user's request must not delete anything"


async def test_pause_401_without_identity_and_422_for_an_unsupported_platform():
    h = _Harness()
    await h.seed()
    async with h.client() as c:
        anon = await c.post(f"/bots/jitsi/{NATIVE}/pause", json={"at_ms": AT_MS})
        bad = await c.post(f"/bots/skype/{NATIVE}/pause", json={"at_ms": AT_MS}, headers=H)
        anon_resume = await c.post(f"/bots/jitsi/{NATIVE}/resume")
    assert (anon.status_code, bad.status_code, anon_resume.status_code) == (401, 422, 401)
    assert h.pub.published == []


async def test_a_planned_meeting_has_no_bot_to_pause():
    h = _Harness()
    await h.seed(status="scheduled")
    async with h.client() as c:
        r = await c.post(f"/bots/jitsi/{NATIVE}/pause", json={"at_ms": AT_MS}, headers=H)
    assert r.status_code == 404
    assert h.pub.published == []


async def test_pause_reaches_every_live_bot_of_the_room():
    """A sibling bot (one live, one still in the lobby) would keep transcribing — the pause, like the
    stop, means the ROOM, so each bot gets the act on its OWN channel."""
    h = _Harness()
    live = await h.seed(status="active")
    lobby = await h.seed(status="awaiting_admission")
    async with h.client() as c:
        r = await c.post(f"/bots/jitsi/{NATIVE}/pause", json={"at_ms": AT_MS}, headers=H)
    assert r.status_code == 202, r.text
    acts = {chan: json.loads(msg) for chan, msg in h.pub.published}
    assert acts == {
        f"bot_commands:meeting:{live['id']}": {"action": "pause", "at": AT_MS, "meeting_id": live["id"]},
        f"bot_commands:meeting:{lobby['id']}": {"action": "pause", "at": AT_MS, "meeting_id": lobby["id"]},
    }


async def test_pause_is_503_when_the_command_bus_is_down_but_still_deletes():
    class _DeadBus:
        async def publish(self, channel, message):
            raise ConnectionError("redis down")

    h = _Harness()
    h.app = create_app(meeting_repo=h.repo, command_publisher=_DeadBus(),
                       transcript_store=h.store, redis=h.bus)
    m = await h.seed()
    await h.ingest(m["id"], [_seg("late", AT_S + 5, AT_S + 6)])
    async with h.client() as c:
        r = await c.post(f"/bots/jitsi/{NATIVE}/pause", json={"at_ms": AT_MS}, headers=H)
    assert r.status_code == 503
    # The deletion is a safety net, not conditional on the bus: it still ran.
    assert await h.hash_ids(m["id"]) == set()


# ── the safety deletion (ruling R4) ──────────────────────────────────────────────────────────────


async def test_pause_deletes_every_segment_touching_the_click_everywhere():
    h = _Harness()
    m = await h.seed()
    other = await h.seed(native="anderer-raum")
    # Durable (already flushed to the transcriptions stand-in) …
    await h.ingest(m["id"], [
        _seg("d-before", AT_S - 10, AT_S - 5),        # entirely before → stays
        _seg("d-ends-at", AT_S - 5, AT_S),            # ends exactly at the click → stays
        _seg("d-straddle", AT_S - 2, AT_S + 2),       # straddles the click → gone (R4)
    ])
    await h.flush(m["id"])
    # … and still live in the hash.
    await h.ingest(m["id"], [
        _seg("l-before", AT_S - 4, AT_S - 3),          # stays
        _seg("l-starts-at", AT_S, AT_S + 1),            # starts exactly at the click → gone
        _seg("l-after", AT_S + 10, AT_S + 12),          # after → gone
    ])
    # Another meeting of the same user, same times — untouched.
    await h.ingest(other["id"], [_seg("o-after", AT_S + 10, AT_S + 12)])
    await h.flush(other["id"])
    await h.ingest(other["id"], [_seg("o-live", AT_S + 1, AT_S + 2)])
    assert h.durable_ids(m["id"]) == {"d-before", "d-ends-at", "d-straddle"}

    async with h.client() as c:
        r = await c.post(f"/bots/jitsi/{NATIVE}/pause", json={"at_ms": AT_MS}, headers=H)
    assert r.status_code == 202, r.text
    assert r.json()["segments_deleted"] == 3

    assert h.durable_ids(m["id"]) == {"d-before", "d-ends-at"}
    assert await h.hash_ids(m["id"]) == {"l-before"}
    transcript = await h.store.get_transcript(USER, "jitsi", NATIVE)
    assert {s["segment_id"] for s in transcript["segments"]} == {"d-before", "d-ends-at", "l-before"}
    # The live feed no longer carries their text, and consumers that already read it are told.
    assert await h.feed_segment_ids(m["id"]) == {"d-before", "d-ends-at", "l-before"}
    assert [sorted(ids) for ids in await h.feed_retracts(m["id"])] == [
        ["d-straddle", "l-after", "l-starts-at"]
    ]
    retract_frames = [json.loads(p) for ch, p in h.bus.published if ch == f"tc:meeting:{m['id']}:mutable"]
    assert {"type": "transcript_retract", "meeting": {"id": m["id"]},
            "segment_ids": sorted(["d-straddle", "l-after", "l-starts-at"])} in [
        {**f, "segment_ids": sorted(f.get("segment_ids") or [])} for f in retract_frames
    ]
    # The other meeting is untouched in every store.
    assert h.durable_ids(other["id"]) == {"o-after"}
    assert await h.hash_ids(other["id"]) == {"o-live"}
    assert await h.feed_segment_ids(other["id"]) == {"o-after", "o-live"}
    assert await h.feed_retracts(other["id"]) == []


async def test_a_second_pause_is_idempotent():
    h = _Harness()
    m = await h.seed()
    await h.ingest(m["id"], [_seg("keep", AT_S - 3, AT_S - 1), _seg("gone", AT_S + 1, AT_S + 2)])
    async with h.client() as c:
        first = await c.post(f"/bots/jitsi/{NATIVE}/pause", json={"at_ms": AT_MS}, headers=H)
        second = await c.post(f"/bots/jitsi/{NATIVE}/pause", json={"at_ms": AT_MS}, headers=H)
    assert (first.status_code, second.status_code) == (202, 202)
    assert (first.json()["segments_deleted"], second.json()["segments_deleted"]) == (1, 0)
    assert await h.hash_ids(m["id"]) == {"keep"}
    assert len(await h.feed_retracts(m["id"])) == 1, "nothing deleted → no empty retract marker"


def test_segment_touches_pause_units_and_edges():
    from meeting_api.collector.adapters import segment_touches_pause

    # Live pipeline: absolute epoch SECONDS (~1.78e9) — compared with the click directly.
    assert not segment_touches_pause(AT_S - 10, AT_S - 5, AT_S)
    assert not segment_touches_pause(AT_S - 5, AT_S, AT_S)           # ends exactly at → stays
    assert segment_touches_pause(AT_S - 2, AT_S + 2, AT_S)           # straddles → gone
    assert segment_touches_pause(AT_S, AT_S + 1, AT_S)               # starts at → gone
    assert segment_touches_pause(AT_S + 5, AT_S + 6, AT_S)
    assert segment_touches_pause(AT_S + 2, AT_S - 2, AT_S)           # inverted → normalised, gone
    # Relative offsets (seconds since the meeting's start, the transcript.v1 wording) are placed on
    # the clock via the meeting's base time.
    base = AT_S - 100
    assert not segment_touches_pause(80.0, 99.0, AT_S, base_epoch_s=base)
    assert not segment_touches_pause(95.0, 100.0, AT_S, base_epoch_s=base)
    assert segment_touches_pause(99.0, 101.0, AT_S, base_epoch_s=base)
    assert segment_touches_pause(120.0, 121.0, AT_S, base_epoch_s=base)
    # A relative segment with no base cannot be placed → removed ("im Zweifel lieber weg").
    assert segment_touches_pause(1.0, 2.0, AT_S, base_epoch_s=None)
    # Unreadable times cannot be placed either.
    assert segment_touches_pause(None, 2.0, AT_S)
    assert segment_touches_pause("x", 2.0, AT_S)


async def test_relative_segments_are_placed_via_the_meeting_start():
    h = _Harness()
    m = await h.seed()
    # The fake's seeded meeting start is 2026-06-20T09:00:00Z; the click 100 s later.
    start_s = 1781946000.0
    at_ms = int((start_s + 100) * 1000)
    await h.ingest(m["id"], [_seg("rel-before", 10.0, 99.0), _seg("rel-after", 100.5, 102.0)])
    async with h.client() as c:
        r = await c.post(f"/bots/jitsi/{NATIVE}/pause", json={"at_ms": at_ms}, headers=H)
    assert r.status_code == 202, r.text
    assert await h.hash_ids(m["id"]) == {"rel-before"}


# ── the bot's confirmation → meeting.data["aufnahme_pause"] ──────────────────────────────────────


async def _post_lifecycle(h: _Harness, event: dict) -> httpx.Response:
    async with h.client() as c:
        return await c.post(LIFECYCLE, json=event)


async def test_confirmation_on_a_repeated_status_is_stored():
    """The bot confirms under its CURRENT status — active→active is an FSM no-op, yet the
    confirmation must land (it is the only place the pause state is ever reported)."""
    h = _Harness()
    m = await h.seed(status="active")
    sid = f"sess-{m['id']}"
    paused = {"pausiert": True, "seit_ms": AT_MS}
    r = await _post_lifecycle(h, {"connection_id": sid, "status": "active", "aufnahme_pause": paused})
    assert r.status_code == 200, r.text
    row = await h.repo.get_meeting(m["id"])
    assert row["data"]["aufnahme_pause"] == paused
    assert row["status"] == "active"

    resumed = {"pausiert": False, "seit_ms": None}
    r = await _post_lifecycle(h, {"connection_id": sid, "status": "active", "aufnahme_pause": resumed})
    assert r.status_code == 200, r.text
    assert (await h.repo.get_meeting(m["id"]))["data"]["aufnahme_pause"] == resumed


async def test_a_late_lobby_confirmation_is_stored_although_its_status_edge_is_rejected():
    """Paused in the lobby, confirmed with status awaiting_admission — but the POST lands after the
    bot already reported `active`. The edge active→awaiting_admission stays a 409 exactly as before;
    the pause confirmation it carries must not be lost with it."""
    h = _Harness()
    m = await h.seed(status="active")
    sid = f"sess-{m['id']}"
    assert (await _post_lifecycle(h, {"connection_id": sid, "status": "active"})).status_code == 200
    paused = {"pausiert": True, "seit_ms": AT_MS}
    r = await _post_lifecycle(
        h, {"connection_id": sid, "status": "awaiting_admission", "aufnahme_pause": paused}
    )
    assert r.status_code == 409, r.text
    assert r.json()["from"] == "active" and r.json()["to"] == "awaiting_admission"
    row = await h.repo.get_meeting(m["id"])
    assert row["status"] == "active", "the rejected edge must not move the meeting"
    assert row["data"]["aufnahme_pause"] == paused


async def test_the_confirmation_survives_the_next_real_advance():
    h = _Harness()
    m = await h.seed(status="active")
    sid = f"sess-{m['id']}"
    paused = {"pausiert": True, "seit_ms": AT_MS}
    await _post_lifecycle(h, {"connection_id": sid, "status": "active", "aufnahme_pause": paused})
    r = await _post_lifecycle(h, {"connection_id": sid, "status": "completed",
                                  "completion_reason": "stopped"})
    assert r.status_code == 200, r.text
    row = await h.repo.get_meeting(m["id"])
    assert row["status"] == "completed"
    assert row["data"]["aufnahme_pause"] == paused


@pytest.mark.parametrize("bad", [
    {"pausiert": "ja", "seit_ms": None},
    {"pausiert": True, "seit_ms": "1784000000000"},
    {"pausiert": True, "seit_ms": True},
    {"seit_ms": AT_MS},
    "pausiert",
])
async def test_a_malformed_confirmation_is_ignored_without_failing_the_callback(bad):
    h = _Harness()
    m = await h.seed(status="active")
    r = await _post_lifecycle(h, {"connection_id": f"sess-{m['id']}", "status": "active",
                                  "aufnahme_pause": bad})
    assert r.status_code == 200, r.text
    assert "aufnahme_pause" not in (await h.repo.get_meeting(m["id"]))["data"]


async def test_only_the_two_contract_fields_are_stored_and_absence_writes_nothing():
    h = _Harness()
    m = await h.seed(status="active")
    sid = f"sess-{m['id']}"
    await _post_lifecycle(h, {"connection_id": sid, "status": "active"})
    assert "aufnahme_pause" not in (await h.repo.get_meeting(m["id"]))["data"]
    await _post_lifecycle(h, {"connection_id": sid, "status": "active",
                              "aufnahme_pause": {"pausiert": True, "seit_ms": AT_MS, "x": 1}})
    assert (await h.repo.get_meeting(m["id"]))["data"]["aufnahme_pause"] == {
        "pausiert": True, "seit_ms": AT_MS
    }


async def test_get_meeting_returns_the_confirmation_to_its_owner():
    h = _Harness()
    m = await h.seed()
    h.store._meetings[m["id"]]["data"]["aufnahme_pause"] = {"pausiert": True, "seit_ms": AT_MS}
    async with h.client() as c:
        r = await c.get(f"/meetings/{m['id']}", headers=H)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["aufnahme_pause"] == {"pausiert": True, "seit_ms": AT_MS}


# ── Postgres legs of the SQL adapters (throwaway DB only) ────────────────────────────────────────

PG_DSN = os.environ.get("VEXA_PAUSE_TEST_PG_DSN")
pg = pytest.mark.skipif(not PG_DSN, reason="VEXA_PAUSE_TEST_PG_DSN not set (throwaway Postgres only)")

_DDL = [
    "DROP TABLE IF EXISTS transcriptions, meeting_sessions, meetings",
    """CREATE TABLE meetings (
        id serial PRIMARY KEY, user_id int NOT NULL, platform varchar(100) NOT NULL,
        platform_specific_id varchar(255), status varchar(50) NOT NULL DEFAULT 'requested',
        bot_container_id varchar(255), start_time timestamp, end_time timestamp,
        data jsonb NOT NULL DEFAULT '{}'::jsonb, created_at timestamp DEFAULT now(),
        updated_at timestamp DEFAULT now())""",
    """CREATE TABLE meeting_sessions (
        id serial PRIMARY KEY, meeting_id int NOT NULL REFERENCES meetings(id),
        session_uid varchar NOT NULL, session_start_time timestamptz NOT NULL DEFAULT now())""",
    """CREATE TABLE transcriptions (
        id serial PRIMARY KEY, meeting_id int NOT NULL REFERENCES meetings(id),
        start_time double precision NOT NULL, end_time double precision NOT NULL, text text NOT NULL,
        speaker varchar(255), language varchar(10), created_at timestamp DEFAULT now(),
        session_uid varchar, segment_id varchar)""",
]


async def _pg():
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(PG_DSN)
    async with engine.begin() as conn:
        for stmt in _DDL:
            await conn.execute(text(stmt))
    return engine, async_sessionmaker(engine, expire_on_commit=False)


@pg
async def test_sql_store_deletes_touching_rows_hash_and_feed():
    from sqlalchemy import text

    from meeting_api.collector.adapters import SqlAlchemyTranscriptStore

    engine, sf = await _pg()
    redis = fakeredis.aioredis.FakeRedis()
    try:
        async with sf() as db:
            mid = (await db.execute(text(
                "INSERT INTO meetings (user_id, platform, platform_specific_id, status, start_time) "
                "VALUES (7, 'jitsi', 'r', 'active', to_timestamp(:base) AT TIME ZONE 'UTC') RETURNING id"
            ), {"base": AT_S - 100})).scalar()
            other = (await db.execute(text(
                "INSERT INTO meetings (user_id, platform, platform_specific_id, status) "
                "VALUES (7, 'jitsi', 'o', 'active') RETURNING id"
            ))).scalar()
            rows = [
                (mid, "before", AT_S - 10, AT_S - 5), (mid, "ends-at", AT_S - 5, AT_S),
                (mid, "straddle", AT_S - 2, AT_S + 2), (mid, "after", AT_S + 10, AT_S + 12),
                (mid, "rel-before", 10.0, 99.0), (mid, "rel-after", 100.5, 101.0),
                (other, "o-after", AT_S + 10, AT_S + 12),
            ]
            for m_id, sid, s, e in rows:
                await db.execute(text(
                    "INSERT INTO transcriptions (meeting_id, start_time, end_time, text, segment_id) "
                    "VALUES (:m, :s, :e, 'x', :sid)"), {"m": m_id, "s": s, "e": e, "sid": sid})
            await db.commit()
        store = SqlAlchemyTranscriptStore(sf, redis_client=redis)
        bus = FakeRedisBus(redis)
        await ingest(store, bus, {"payload": json.dumps({
            "type": "transcription", "meeting_id": str(mid), "uid": "s", "platform": "jitsi",
            "segments": [_seg("h-before", AT_S - 4, AT_S - 3), _seg("h-after", AT_S + 1, AT_S + 2)],
        })})

        deleted = await store.delete_segments_from(mid, AT_MS)

        assert sorted(deleted) == ["after", "h-after", "rel-after", "straddle"]
        async with sf() as db:
            left = (await db.execute(text(
                "SELECT meeting_id, segment_id FROM transcriptions ORDER BY segment_id"))).all()
        assert sorted(left) == sorted([(mid, "before"), (mid, "ends-at"), (mid, "rel-before"),
                                       (other, "o-after")])
        raw = await redis.hgetall(segments_hash_key(mid))
        assert {k.decode() for k in raw} == {"h-before"}
        feed = {json.loads(f[b"payload"])["segments"][0]["segment_id"]
                for _e, f in await redis.xrange(f"tc:meeting:{mid}")}
        assert feed == {"h-before"}
    finally:
        await redis.aclose()
        await engine.dispose()


@pg
async def test_sql_repo_merges_by_session_without_touching_status():
    from sqlalchemy import text

    from meeting_api.bot_spawn.adapters import SqlAlchemyMeetingRepo

    engine, sf = await _pg()
    try:
        async with sf() as db:
            mid = (await db.execute(text(
                "INSERT INTO meetings (user_id, platform, platform_specific_id, status, data) "
                "VALUES (7, 'jitsi', 'r', 'active', '{\"keep\": 1}'::jsonb) RETURNING id"))).scalar()
            await db.execute(text(
                "INSERT INTO meeting_sessions (meeting_id, session_uid) VALUES (:m, 'sess-x')"),
                {"m": mid})
            await db.commit()
        repo = SqlAlchemyMeetingRepo(sf)
        got = await repo.merge_meeting_data_by_session(
            session_uid="sess-x", patch={"aufnahme_pause": {"pausiert": True, "seit_ms": AT_MS}})
        assert got == mid
        assert await repo.merge_meeting_data_by_session(session_uid="nope", patch={"a": 1}) is None
        row = await repo.get_meeting(mid)
        assert row["status"] == "active"
        assert row["data"] == {"keep": 1, "aufnahme_pause": {"pausiert": True, "seit_ms": AT_MS}}
    finally:
        await engine.dispose()
