"""Reply audio against Postgres: stored for 24 h, capped at 2 MB, gone with its user (s06 §4.8,
data-model `media_blobs`)."""

import os
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.errors import MediaTooLarge
from app.domain.models.base import UserHash
from app.domain.models.message import AudioClip
from app.store.db import create_engine, create_session_factory
from app.store.repositories.media_blob_repository import MediaBlobRepository
from app.store.tables import MEDIA_BLOB_MAX_BYTES
from tests.support.app_factory import make_settings

pytestmark = pytest.mark.integration

PARENT = UserHash("c" * 64)
NOTE = AudioClip(data=b"OggS voice reply", mime_type="audio/ogg; codecs=opus", duration_ms=4000)


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.fail("DATABASE_URL must point at the docker-compose.test.yml database")
    engine = create_engine(make_settings(database_url=url))
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE users, inbox_messages RESTART IDENTITY CASCADE"))
        await connection.execute(
            text("INSERT INTO users (user_hash, channel, state) VALUES (:h, 'whatsapp', 'active')"),
            {"h": PARENT},
        )
    yield engine
    await engine.dispose()


@pytest.fixture
def media(engine: AsyncEngine) -> MediaBlobRepository:
    return MediaBlobRepository(create_session_factory(engine))


async def run_sql(engine: AsyncEngine, sql: str, **values: object) -> list[tuple[object, ...]]:
    async with engine.begin() as connection:
        result = await connection.execute(text(sql), values)
        return [tuple(row) for row in result.all()] if result.returns_rows else []


async def test_saved_audio_loads_back_for_the_sender(media: MediaBlobRepository) -> None:
    blob_id = await media.save(PARENT, NOTE)
    assert await media.load_audio(blob_id) == AudioClip(
        data=NOTE.data, mime_type=NOTE.mime_type, duration_ms=None
    )


async def test_an_unknown_id_loads_nothing(media: MediaBlobRepository) -> None:
    assert await media.load_audio(uuid4()) is None


async def test_expired_audio_isnt_loaded_and_is_deleted_by_maintenance(
    engine: AsyncEngine, media: MediaBlobRepository
) -> None:
    expired = await media.save(PARENT, NOTE)
    fresh = await media.save(PARENT, NOTE)
    await run_sql(
        engine,
        "UPDATE media_blobs SET expires_at = now() - interval '1 second' WHERE id = :id",
        id=expired,
    )
    assert await media.load_audio(expired) is None
    assert await media.delete_expired() == 1
    assert await run_sql(engine, "SELECT id FROM media_blobs") == [(fresh,)]


async def test_exactly_2_mb_is_stored_and_one_byte_more_is_refused(
    engine: AsyncEngine, media: MediaBlobRepository
) -> None:
    at_cap = AudioClip(data=b"x" * MEDIA_BLOB_MAX_BYTES, mime_type="audio/ogg", duration_ms=None)
    await media.save(PARENT, at_cap)
    over = AudioClip(
        data=b"x" * (MEDIA_BLOB_MAX_BYTES + 1), mime_type="audio/ogg", duration_ms=None
    )
    with pytest.raises(MediaTooLarge, match=f"reply audio is {MEDIA_BLOB_MAX_BYTES + 1} bytes"):
        await media.save(PARENT, over)
    assert await run_sql(engine, "SELECT count(*) FROM media_blobs") == [(1,)]


async def test_the_database_refuses_a_size_that_doesnt_match_the_bytes(engine: AsyncEngine) -> None:
    with pytest.raises(IntegrityError, match="ck_media_blobs_size_matches"):
        await run_sql(
            engine,
            "INSERT INTO media_blobs (id, user_hash, purpose, mime_type, data, size_bytes, "
            "expires_at) VALUES (gen_random_uuid(), :h, 'reply_audio', 'audio/ogg', 'abc', 1, "
            "now())",
            h=PARENT,
        )


async def test_an_unknown_purpose_is_refused(engine: AsyncEngine) -> None:
    with pytest.raises(IntegrityError, match="ck_media_blobs_purpose_valid"):
        await run_sql(
            engine,
            "INSERT INTO media_blobs (id, user_hash, purpose, mime_type, data, size_bytes, "
            "expires_at) VALUES (gen_random_uuid(), :h, 'user_photo', 'image/jpeg', 'abc', 3, "
            "now())",
            h=PARENT,
        )


async def test_deleting_the_user_deletes_their_audio(
    engine: AsyncEngine, media: MediaBlobRepository
) -> None:
    await media.save(PARENT, NOTE)
    await run_sql(engine, "DELETE FROM users WHERE user_hash = :h", h=PARENT)
    assert await run_sql(engine, "SELECT count(*) FROM media_blobs") == [(0,)]


async def test_an_outbox_part_loses_its_link_when_the_audio_is_deleted(
    engine: AsyncEngine, media: MediaBlobRepository
) -> None:
    blob_id = await media.save(PARENT, NOTE)
    turn_id = uuid4()
    await run_sql(
        engine,
        "INSERT INTO turns (id, user_hash, status, worker_id) "
        "VALUES (:t, :h, 'completed', 'test-worker')",
        t=turn_id,
        h=PARENT,
    )
    await run_sql(
        engine,
        "INSERT INTO outbox_messages (turn_id, part_no, user_hash, channel, kind, audio_blob_id) "
        "VALUES (:t, 0, :h, 'whatsapp', 'audio', :b)",
        t=turn_id,
        h=PARENT,
        b=blob_id,
    )
    await run_sql(engine, "DELETE FROM media_blobs WHERE id = :b", b=blob_id)
    assert await run_sql(engine, "SELECT audio_blob_id FROM outbox_messages") == [(None,)]
