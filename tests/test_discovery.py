import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from collector.sources import heart_rate


class DiscoveryIsolationTests(unittest.IsolatedAsyncioTestCase):
    async def test_scan_failure_keeps_existing_streams_and_new_bands_join_independently(self):
        real_sleep = asyncio.sleep
        active, started, cancelled = set(), [], []
        devices = {key: SimpleNamespace(address=key, name=key) for key in ("a", "b")}
        advert = SimpleNamespace(service_uuids=[heart_rate.SERVICE], local_name=None, rssi=-50)
        scans = 0

        async def collect(_store, source_id, _device):
            active.add(source_id); started.append(source_id)
            try:
                await asyncio.Future()
            finally:
                active.remove(source_id); cancelled.append(source_id)

        async def scan(**kwargs):
            nonlocal scans
            scans += 1
            if scans == 1:
                return {"a": (devices["a"], advert)}
            if scans == 2:
                self.assertEqual(active, {"ble:a"})
                raise RuntimeError("temporary scan failure")
            if scans == 3:
                self.assertEqual(active, {"ble:a"})
                self.assertEqual(cancelled, [])
                return {"b": (devices["b"], advert)}
            if scans == 4:
                self.assertEqual(active, {"ble:a", "ble:b"})
                return {}
            self.assertEqual(active, {"ble:b"})
            self.assertEqual(cancelled, ["ble:a"])
            raise asyncio.CancelledError

        async def enabled(_kind):
            return {"ble:a", "ble:b"} if scans < 4 else {"ble:b"}

        async def pause(_seconds):
            await real_sleep(0)

        store = SimpleNamespace(discover=AsyncMock(), enabled=AsyncMock(side_effect=enabled))
        with patch.object(heart_rate.BleakScanner, "discover", side_effect=scan), patch.object(
            heart_rate, "collect", side_effect=collect
        ), patch.object(heart_rate.asyncio, "sleep", side_effect=pause):
            with self.assertRaises(asyncio.CancelledError):
                await heart_rate.run(store)
        self.assertEqual(sorted(started), ["ble:a", "ble:b"])
        self.assertEqual(sorted(cancelled), ["ble:a", "ble:b"])
        self.assertFalse(active)
