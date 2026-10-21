import json
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from collector.sources.airgradient import SERIAL, next_deadline, parse_snapshot, merge_display, restore_display


class AirGradientSnapshotTests(unittest.TestCase):
    def test_preserves_measurements_device_state_and_future_fields(self):
        payload = {
            "serialno": SERIAL, "rco2": 1405, "pm02": 3, "atmp": 22.84,
            "rhum": 30.3, "tvocIndex": 104.5, "noxIndex": 1,
            "wifi": -40, "firmware": "3.7.0", "model": "I-9PSL",
            "future": {"samples": [1, None], "available": True},
        }
        value, saved = parse_snapshot(json.dumps(payload).encode())
        self.assertEqual(value, 1405)
        self.assertEqual(saved, payload)

    def test_missing_or_invalid_co2_does_not_discard_other_sensors(self):
        for co2 in (None, "unavailable", True):
            with self.subTest(co2=co2):
                payload = {"serialno": SERIAL, "rco2": co2, "pm02": 3}
                value, saved = parse_snapshot(json.dumps(payload))
                self.assertIsNone(value)
                self.assertEqual(saved, payload)
        value, saved = parse_snapshot(json.dumps({"serialno": SERIAL, "rco2": 0}))
        self.assertEqual(value, 0)

    def test_wrong_device_cannot_be_recorded_after_ip_reuse(self):
        for payload in ([], {}, {"serialno": "another-device", "rco2": 700}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                parse_snapshot(json.dumps(payload))

    def test_invalid_json_numbers_are_rejected_before_postgres(self):
        for constant in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(constant=constant), self.assertRaises(ValueError):
                parse_snapshot(f'{{"serialno":"{SERIAL}","rco2":{constant}}}')

    def test_regular_polling_does_not_accumulate_request_duration(self):
        deadline = 0.0
        for _ in range(60):
            deadline = next_deadline(deadline, deadline + 0.2)
        self.assertEqual(deadline, 60.0)

    def test_slow_requests_skip_missed_slots_without_a_catchup_burst(self):
        self.assertEqual(next_deadline(10.0, 12.4), 13.4)


class AirDisplayTests(unittest.IsolatedAsyncioTestCase):
    async def test_partial_invalid_snapshots_and_restart_preserve_values_and_times(self):
        before = "2026-10-21T03:00:00+00:00"
        after = "2026-10-21T03:00:10+00:00"
        initial = merge_display({}, {"rco2": 650, "rhum": 45, "pm02": 8}, before)
        raw = {"rco2": None, "rhum": "unknown", "pm02": 0, "atmp": 23,
               "noxIndex": True, "tvocIndex": float("nan")}
        display = merge_display(initial, raw, after)
        self.assertEqual(display["measurements"], {"rco2":650,"rhum":45,"pm02":0,"atmp":23})
        self.assertEqual(display["updated_at"]["rco2"], before)
        self.assertEqual(display["updated_at"]["pm02"], after)
        self.assertIsNone(raw["rco2"])
        self.assertEqual(initial["measurements"]["pm02"], 8)
        pool = SimpleNamespace(fetch=AsyncMock(return_value=[
            {"display":json.dumps(display), "measurements":"{}", "recorded_at":datetime.now(timezone.utc)}
        ]))
        self.assertEqual(await restore_display(SimpleNamespace(pool=pool)), display)

    async def test_upgrade_restores_old_snapshots_without_a_display_cache(self):
        older = datetime(2026,10,21,3,0,tzinfo=timezone.utc)
        newer = datetime(2026,10,21,3,1,tzinfo=timezone.utc)
        pool = SimpleNamespace(fetch=AsyncMock(return_value=[
            {"display":None,"measurements":'{"atmp":24,"rhum":null}',"recorded_at":newer},
            {"display":None,"measurements":'{"atmp":23,"rhum":45}',"recorded_at":older},
        ]))
        display = await restore_display(SimpleNamespace(pool=pool))
        self.assertEqual(display["measurements"], {"atmp":24,"rhum":45})
        self.assertEqual(display["updated_at"]["rhum"], older.isoformat())


if __name__ == "__main__":
    unittest.main()
