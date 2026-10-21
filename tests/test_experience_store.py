"""Opt-in integration tests against an isolated, disposable PostgreSQL database.
Run: TEST_PG_HOST=<compose db IP> .venv/bin/python -m unittest discover -s tests -p test_experience_store.py
The real postgres database and its samples are never modified.
"""
import asyncio
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import uuid
import unittest

import asyncpg
from collector.store import Store

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.environ.get("TEST_PG_HOST"), "set TEST_PG_HOST for isolated PostgreSQL integration")
class ExperienceStoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.database = "fourseas_test_" + uuid.uuid4().hex
        self.options = dict(host=os.environ["TEST_PG_HOST"], user="postgres", password="docker")
        self.admin = await asyncpg.connect(database="postgres", **self.options)
        await self.admin.execute(f'CREATE DATABASE "{self.database}"')
        self.pool = await asyncpg.create_pool(database=self.database, min_size=1, max_size=4, **self.options)
        for path in ("db/init.sql", "db/004_experiences.sql", "db/005_parallel_experiences.sql"):
            await self.pool.execute((ROOT / path).read_text())
        self.store = Store(self.pool)

    async def asyncTearDown(self):
        await self.pool.close()
        await self.admin.execute(f'DROP DATABASE "{self.database}"')
        await self.admin.close()

    async def test_time_boundaries_delayed_notifications_and_zero_filter(self):
        await self.store.discover("test:heart", "Heart", "ble_heart_rate", "heart_rate", "bpm", enabled=True)
        await self.store.discover("test:air", "Air", "airgradient", "co2", "ppm", enabled=True)
        start = datetime.now(timezone.utc) - timedelta(minutes=2)
        end = start + timedelta(seconds=30)
        first = await self.pool.fetchval(
            "INSERT INTO experiences (name,started_at,ended_at) VALUES ('体验者 1',$1,$2) RETURNING id", start, end)
        second = await self.pool.fetchval(
            "INSERT INTO experiences (name,started_at,ended_at) VALUES ('体验者 2',$1,$2) RETURNING id",
            end, end + timedelta(seconds=30))
        for offset, bpm in ((-1, 71), (0, 72), (29, 73), (30, 74), (59, 75), (60, 76)):
            await self.store.write("test:heart", bpm, start + timedelta(seconds=offset), {"contact": True})
        rows = await self.pool.fetch("SELECT value,experience_id FROM samples ORDER BY id")
        self.assertEqual([r["experience_id"] for r in rows], [None, first, first, second, second, None])
        # Both sessions have already ended when these queued packets reach storage.
        await self.store.write("test:heart", 0, start, {"reported_bpm": 0, "contact": True})
        await self.store.write("test:heart", None, start, {"reported_bpm": 0})
        await self.store.write("test:heart", 72, start, {"contact": False})
        await self.store.write("test:heart", 72, start, {"measurement_valid": False})
        self.assertEqual(await self.pool.fetchval("SELECT count(*) FROM samples"), 6)
        # Zero is a valid environmental reading; the rule is specific to heart rate.
        await self.store.write("test:air", 0, start, {"measurements": {"pm02": 0}})
        self.assertEqual(await self.pool.fetchval("SELECT experience_id FROM samples WHERE source_id='test:air'"), first)
        self.assertEqual(await self.pool.fetchval("SELECT sample_count FROM sources WHERE id='test:heart'"), 6)
        await self.pool.execute("UPDATE sources SET enabled=false WHERE id='test:heart'")
        await self.store.write("test:heart", 80, start)
        self.assertEqual(await self.pool.fetchval("SELECT count(*) FROM samples"), 7)

    async def test_parallel_bands_shared_room_and_independent_end(self):
        for source, kind in (("band:a", "ble_heart_rate"), ("band:b", "ble_heart_rate"), ("room", "airgradient")):
            await self.store.discover(source, source, kind, "value", "", enabled=True)
        start = datetime.now(timezone.utc) - timedelta(seconds=60)
        a = await self.pool.fetchval("INSERT INTO experiences(name,heart_source_id,client_id,started_at,ended_at) VALUES ('A','band:a',$1,$2,$3) RETURNING id",
                                    uuid.uuid4(), start, start + timedelta(seconds=20))
        b = await self.pool.fetchval("INSERT INTO experiences(name,heart_source_id,client_id,started_at) VALUES ('B','band:b',$1,$2) RETURNING id",
                                    uuid.uuid4(), start)
        await self.store.write("band:a", 75, start + timedelta(seconds=10))
        await self.store.write("band:b", 95, start + timedelta(seconds=10))
        await self.store.write("room", 800, start + timedelta(seconds=10))
        await self.store.write("band:a", 76, start + timedelta(seconds=20))
        await self.store.write("band:b", 96, start + timedelta(seconds=20))
        await self.store.write("room", 810, start + timedelta(seconds=20))
        await self.store.write("band:b", 0, start + timedelta(seconds=25))
        async def values(experience):
            return await self.pool.fetch("SELECT p.source_id,p.value FROM experience_samples x JOIN samples p ON p.id=x.sample_id WHERE x.experience_id=$1 ORDER BY p.id", experience)
        self.assertEqual([(r["source_id"], r["value"]) for r in await values(a)], [("band:a",75),("room",800)])
        self.assertEqual([(r["source_id"], r["value"]) for r in await values(b)], [("band:b",95),("room",800),("band:b",96),("room",810)])
        self.assertEqual(await self.pool.fetchval("SELECT count(*) FROM samples WHERE source_id='room'"), 2)
        self.assertEqual(await self.pool.fetchval("SELECT count(*) FROM samples WHERE value=0"), 0)

    async def test_zero_notification_updates_presence_without_a_sample(self):
        await self.store.discover("band:zero", "Band", "ble_heart_rate", "heart_rate", "bpm", enabled=True)
        await self.pool.execute("UPDATE sources SET last_seen=now()-interval '2 minutes' WHERE id='band:zero'")
        old_seen = await self.pool.fetchval("SELECT last_seen FROM sources WHERE id='band:zero'")
        await self.store.status("band:zero", "error", "scan problem")
        self.assertEqual(await self.pool.fetchval("SELECT last_seen FROM sources WHERE id='band:zero'"), old_seen)
        await self.store.status("band:zero", "waiting", seen=True)
        self.assertGreater(await self.pool.fetchval("SELECT last_seen FROM sources WHERE id='band:zero'"), old_seen)
        self.assertEqual(await self.pool.fetchval("SELECT count(*) FROM samples"), 0)

    async def test_http_handlers_against_real_database(self):
        env = {**os.environ, "TEST_DATABASE_URL":
               f'postgresql://postgres:docker@{self.options["host"]}:5432/{self.database}'}
        process = await asyncio.create_subprocess_exec("node", str(ROOT / "tests/test-experience-api.mjs"),
                                                      env=env, cwd=ROOT)
        self.assertEqual(await process.wait(), 0)
