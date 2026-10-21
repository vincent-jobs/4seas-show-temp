import json
from datetime import datetime

import asyncpg


class Store:
    """Shared persistence contract for all collection sources."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def discover(
        self, source_id, name, kind, metric, unit, metadata=None, *, enabled=False
    ):
        await self.pool.execute(
            """
            INSERT INTO sources (id, name, kind, metric, unit, metadata, enabled)
            VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7)
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                last_seen = now(),
                metadata = EXCLUDED.metadata
            """,
            source_id, name, kind, metric, unit, json.dumps(metadata or {}), enabled,
        )

    async def enabled(self, kind):
        rows = await self.pool.fetch(
            "SELECT id FROM sources WHERE kind = $1 AND enabled", kind
        )
        return {row["id"] for row in rows}

    async def status(self, source_id, status, error=None, *, seen=False):
        await self.pool.execute(
            """UPDATE sources SET status = $2, error = $3,
                last_seen = CASE WHEN $4 THEN now() ELSE last_seen END WHERE id = $1""",
            source_id, status, error, seen,
        )

    async def write(
        self, source_id: str, value: float | None, recorded_at: datetime, metadata=None
    ):
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute("SELECT pg_advisory_xact_lock(746201)")
                # Lock against a simultaneous pause from the UI. A notification
                # already in flight must not be saved after collection is paused.
                source = await connection.fetchrow(
                    "SELECT enabled, kind FROM sources WHERE id = $1 FOR UPDATE", source_id
                )
                if not source or not source["enabled"]:
                    return
                if source["kind"] == "ble_heart_rate" and (
                    value is None or value <= 0 or (metadata or {}).get("reported_bpm") == 0
                    or (metadata or {}).get("contact") is False
                    or (metadata or {}).get("measurement_valid") is False
                ):
                    return
                # A queued sample arriving after End still belongs to its interval.
                # Heart samples belong only to the bound band. Room/bed samples
                # are stored once and linked to every overlapping experience.
                experiences = await connection.fetch(
                    """
                    SELECT id FROM experiences WHERE started_at <= $1
                    AND (ended_at IS NULL OR $1 < ended_at)
                    AND ($2 <> 'ble_heart_rate' OR heart_source_id = $3
                         OR (heart_source_id IS NULL AND client_id IS NULL))
                    ORDER BY started_at DESC, id
                    """, recorded_at, source["kind"], source_id,
                )
                sample_id = await connection.fetchval(
                    """
                    INSERT INTO samples (source_id, value, recorded_at, metadata, experience_id)
                    VALUES ($1, $2, $3, $4::jsonb, $5) RETURNING id
                    """,
                    source_id, value, recorded_at, json.dumps(metadata or {}, allow_nan=False),
                    experiences[0]["id"] if experiences else None,
                )
                if experiences:
                    await connection.executemany(
                        "INSERT INTO experience_samples (experience_id,sample_id) VALUES ($1,$2)",
                        [(row["id"], sample_id) for row in experiences],
                    )
                await connection.execute(
                    """
                    UPDATE sources SET sample_count = sample_count + 1,
                        last_sample_at = $2, last_seen = now(),
                        status = 'streaming', error = NULL
                    WHERE id = $1
                    """,
                    source_id, recorded_at,
                )

    async def heartbeat(self, error=None):
        await self.pool.execute(
            """
            INSERT INTO collector_status (id, heartbeat, error) VALUES (1, now(), $1)
            ON CONFLICT (id) DO UPDATE SET heartbeat = now(), error = EXCLUDED.error
            """,
            error,
        )
