import asyncio
import json
import time
import unittest
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, patch

import httpx

from collector.eight_api import APIError, APP, AUTH, CLIENT, EightAPI, bed_temperature, concurrent_reads, measurements, snapshot
from collector.sources.eight_sleep import backfill_one, merge_display, next_poll_at, restore_display


class EightAPITest(unittest.IsolatedAsyncioTestCase):
    async def test_reauthenticate_once_and_keep_credentials_off_get_requests(self):
        calls = []
        auths = 0

        def handler(request):
            nonlocal auths
            calls.append(request)
            if str(request.url) == AUTH:
                auths += 1
                return httpx.Response(200, json={"access_token": f"secret-{auths}", "expires_in": 3600})
            if auths == 1:
                return httpx.Response(401, json={"message": "expired"})
            self.assertEqual(request.headers["authorization"], "Bearer secret-2")
            self.assertEqual(request.content, b"")
            return httpx.Response(200, json={"user": {"score": 80, "access_token": "must-not-save"}})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            data = await EightAPI("private@example.test", "private-password", http).get(CLIENT + "/users/me")
        self.assertEqual(auths, 2)
        self.assertEqual(data, {"user": {"score": 80}})
        self.assertEqual([r.method for r in calls], ["POST", "GET", "POST", "GET"])

    async def test_concurrent_expired_requests_share_one_token_refresh(self):
        auths = 0
        async def handler(request):
            nonlocal auths
            await asyncio.sleep(0.005)
            if str(request.url) == AUTH:
                auths += 1
                return httpx.Response(200, json={"access_token": "new", "expires_in": 3600})
            if request.headers["authorization"] == "Bearer old":
                return httpx.Response(401)
            return httpx.Response(200, json={"ok": True})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            api = EightAPI("", "", http)
            api.token, api.expires = "old", time.monotonic() + 3600
            results = await asyncio.gather(*(api.get(CLIENT + "/users/me") for _ in range(6)))
        self.assertEqual(auths, 1)
        self.assertTrue(all(result["ok"] for result in results))

    async def test_snapshot_parallelism_is_bounded_and_all_reads_finish(self):
        active = peak = 0
        async def get(url, params=None):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            try:
                await asyncio.sleep(0.005)
                if url == CLIENT + "/users/me":
                    return {"user": {"userId": "main", "devices": ["pod"]}}
                if url == CLIENT + "/devices/pod":
                    return {"result": {"online": True}}
                return {}
            finally:
                active -= 1
        api = AsyncMock()
        api.get.side_effect = get
        api.trends.return_value = {"days": []}
        result, _ = await snapshot(api)
        self.assertGreater(peak, 1)
        self.assertLessEqual(peak, 8)
        self.assertEqual(active, 0)
        self.assertIn("user/main/base", result["responses"])
        self.assertIn("user/main/temperature_all", result["responses"])

    async def test_fatal_read_cancels_siblings_before_next_poll(self):
        finished = asyncio.Event()
        async def blocked():
            try:
                await asyncio.Event().wait()
            finally:
                finished.set()
        async def limited():
            await asyncio.sleep(0)
            raise APIError(429, retry_after=60)
        with self.assertRaises(APIError):
            await concurrent_reads(blocked(), limited())
        self.assertTrue(finished.is_set())

    def test_last_valid_values_survive_missing_data_and_keep_original_times(self):
        old = merge_display({}, {"leftBedTempC": 21, "rightBedTempC": 22, "leftTorsoAngle": 15, "heartRate": 63}, "old")
        new = merge_display(old, {
            "leftBedTempC": 23, "rightBedTempC": None, "leftTorsoAngle": 0,
            "heartRate": 0, "hrv": float("nan"), "respiratoryRate": True,
        }, "new")
        self.assertEqual(new["measurements"], {"leftBedTempC": 23, "rightBedTempC": 22, "leftTorsoAngle": 0, "heartRate": 63})
        self.assertEqual(new["updated_at"]["rightBedTempC"], "old")
        self.assertEqual(new["updated_at"]["leftTorsoAngle"], "new")
        self.assertEqual(old["measurements"]["leftTorsoAngle"], 15)
        self.assertEqual(merge_display(new, {}, "later"), new)

    async def test_restored_display_survives_restart_and_legacy_snapshots(self):
        store = AsyncMock()
        stamp = datetime(2026, 10, 21, tzinfo=timezone.utc)
        expected = merge_display({}, {"leftBedTempC": 21}, stamp.isoformat())
        store.pool.fetch.return_value = [{
            "recorded_at": stamp, "display": json.dumps(expected), "measurements": "{}",
        }]
        self.assertEqual(await restore_display(store, "bed"), expected)
        store.pool.fetch.return_value = [
            {"recorded_at": stamp, "display": None, "measurements": '{"leftBedTempC": null}'},
            {"recorded_at": stamp, "display": None, "measurements": '{"leftBedTempC": 21}'},
        ]
        self.assertEqual(await restore_display(store, "bed"), expected)

    def test_poll_deadlines_do_not_add_request_duration_or_catch_up(self):
        self.assertEqual(next_poll_at(100, 103), 110)
        self.assertEqual(next_poll_at(100, 111), 120)
        self.assertEqual(next_poll_at(100, 135), 140)

    async def test_offline_code_preserved_without_error_body(self):
        def handler(request):
            return httpx.Response(404, json={
                "errorType": "PodOffline", "message": "private@example.test private-password",
            })
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            api = EightAPI("", "", http)
            with self.assertRaises(APIError) as caught:
                await api._request("GET", APP + "/v1/users/example/base")
        self.assertEqual(str(caught.exception), "HTTP 404 · PodOffline")

    async def test_rate_limit_keeps_retry_after_and_does_not_loop(self):
        calls = 0
        def handler(request):
            nonlocal calls
            calls += 1
            return httpx.Response(429, headers={"Retry-After": "900"})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            with self.assertRaises(APIError) as caught:
                await EightAPI("", "", http)._request("GET", CLIENT + "/users/me")
        self.assertEqual(caught.exception.retry_after, 900)
        self.assertEqual(calls, 1)

    async def test_snapshot_keeps_all_devices_users_and_partial_results(self):
        requested = []
        async def get(url, params=None):
            requested.append(url)
            if url == CLIENT + "/users/me":
                return {"user": {"userId": "main", "devices": ["pod"], "currentDevice": {"timeZone": "UTC"}}}
            if "/household/" in url:
                return {"households": [{"sets": [{"devices": [{"deviceId": "pillow"}]}]}]}
            if url == CLIENT + "/devices/pod":
                return {"result": {"leftUserId": "main", "rightUserId": "partner", "online": False}}
            if url.endswith("/base"):
                raise APIError(404, code="PodOffline")
            return {"newField": {"future": [None, 42]}}
        api = AsyncMock()
        api.get.side_effect = get
        api.trends.return_value = {"days": [{"day": "2026-10-19", "sessions": [{"timeseries": {"heartRate": [["t", 60]]}}]}]}
        result, profiles = await snapshot(api)
        self.assertEqual(set(profiles), {"main", "partner"})
        self.assertIn("device/pillow", result["responses"])
        self.assertEqual(result["errors"]["user/main/base"], "HTTP 404 · PodOffline")
        self.assertEqual(result["responses"]["user/main/temperature"]["newField"]["future"], [None, 42])
        self.assertIn(APP + "/v1/users/partner/audio/player", requested)
        self.assertEqual(result["responses"]["user/main/trends"], api.trends.return_value)

    def test_preview_does_not_invent_sleep_or_turn_levels_into_celsius(self):
        result = measurements({
            "main_user_id": "main", "errors": {"user/main/base": "HTTP 404 · PodOffline"},
            "responses": {
                "user/main/trends": {"days": []},
                "user/main/temperature": {"currentDeviceLevel": -12, "currentState": {"type": "off"}},
                "device/pod": {"result": {"online": False}},
            },
        })
        self.assertNotIn("sleep_score", result)
        self.assertNotIn("tempBedC", result)
        self.assertEqual(result["currentDeviceLevel"], -12)
        self.assertFalse(result["hub_online"])
        self.assertIn("PodOffline", result["base_status"])

    def test_online_sensor_temperatures_are_distinct_from_targets_and_sleep(self):
        result = measurements({
            "main_user_id": "main", "errors": {}, "responses": {
                "user/main/current_device": {"id": "pod", "side": "solo"},
                "device/pod": {"result": {
                    "online": True, "isTemperatureAvailable": True,
                    "leftHeatingLevel": -47, "rightHeatingLevel": -44,
                    "leftTargetHeatingLevel": 80, "rightTargetHeatingLevel": 80,
                    "leftNowHeating": False, "rightNowHeating": False,
                }},
                "user/main/temperature": {
                    "currentDeviceLevel": -47, "currentLevel": 0,
                    "currentState": {"type": "off"},
                },
                "user/main/base": {
                    "left": {"torso": {"currentAngle": 0}, "leg": {"currentAngle": 0}},
                    "right": {"torso": {"currentAngle": 12}, "leg": {"currentAngle": 5}},
                },
                "user/main/audio_player": {"volume": 0, "state": "Ready"},
                "user/main/trends": {"days": []},
            },
        })
        self.assertEqual((result["leftBedTempC"], result["rightBedTempC"]), (21, 22))
        self.assertEqual(result["currentBedTempC"], 21)
        self.assertEqual(result["leftBedLevel"], -47)
        self.assertEqual(result["currentLevel"], 0)
        self.assertEqual(result["bed_state"], "off")
        self.assertTrue(result["hub_online"])
        self.assertEqual((result["leftTorsoAngle"], result["rightTorsoAngle"]), (0, 12))
        self.assertEqual((result["leftLegAngle"], result["rightLegAngle"]), (0, 5))
        self.assertEqual(result["audioVolume"], 0)
        self.assertNotIn("tempBedC", result)
        self.assertNotIn("sleep_score", result)

    def test_current_bed_selection_does_not_mix_household_devices(self):
        responses = {
            "user/main/current_device": {"id": "pod"},
            "device/pillow": {"result": {"online": False, "leftHeatingLevel": 100}},
            "device/pod": {"result": {"online": True, "leftHeatingLevel": -47}},
            "device/other-pod": {"result": {"online": True, "leftHeatingLevel": 100}},
        }
        payload = {"main_user_id": "main", "errors": {}, "responses": responses}
        result = measurements(payload)
        self.assertTrue(result["hub_online"])
        self.assertEqual(result["leftBedTempC"], 21)
        responses["user/main/current_device"] = {"id": "missing"}
        self.assertNotIn("leftBedTempC", measurements(payload))
        del responses["user/main/current_device"]
        self.assertNotIn("leftBedTempC", measurements(payload))
        responses["account"] = {"user": {"currentDevice": {"id": "pod"}}}
        self.assertEqual(measurements(payload)["leftBedTempC"], 21)

    def test_offline_or_unavailable_temperature_is_not_current(self):
        for flags in ({"online": False}, {"online": True, "isTemperatureAvailable": False}, {}):
            with self.subTest(flags=flags):
                result = measurements({
                    "main_user_id": "main", "errors": {}, "responses": {
                        "device/pod": {"result": {**flags, "leftHeatingLevel": -47}},
                        "user/main/temperature": {"currentDeviceLevel": -47},
                        "user/main/trends": {"days": [{"day": "2026-10-20", "sessions": [{
                            "timeseries": {"tempBedC": [["t", 28.5]]},
                        }]}]},
                    },
                })
                self.assertNotIn("leftBedTempC", result)
                self.assertNotIn("currentBedTempC", result)
                self.assertEqual(result["tempBedC"], 28.5)

    def test_conversion_preserves_zero_and_rejects_invalid_levels(self):
        self.assertEqual(bed_temperature(0), 27)
        self.assertEqual(bed_temperature(-100), 13)
        self.assertEqual(bed_temperature(100), 44)
        # Upstream nearest-entry conversion resolves a tie to the lower raw key.
        self.assertEqual(bed_temperature(-46), 21)
        for value in (None, True, False, "0", float("nan"), float("inf"), -101, 101):
            with self.subTest(value=value):
                self.assertIsNone(bed_temperature(value))

    async def test_backfill_keeps_going_through_empty_months(self):
        api, store = AsyncMock(), AsyncMock()
        store.pool.fetchrow.return_value = {"next_before": date(2026, 9, 1), "complete": False}
        api.trends.return_value = {"days": []}
        with patch("collector.sources.eight_sleep.save_days", AsyncMock(return_value=True)):
            pending = await backfill_one(api, store, "source", "user", {"createdAt": "2025-01-01"})
        self.assertTrue(pending)
        self.assertEqual(store.pool.execute.call_args.args[3], date(2026, 8, 2))
        self.assertFalse(store.pool.execute.call_args.args[4])

    async def test_backfill_does_not_advance_cursor_after_failure_or_pause(self):
        api, store = AsyncMock(), AsyncMock()
        store.pool.fetchrow.return_value = None
        api.trends.side_effect = APIError(500)
        with self.assertRaises(APIError):
            await backfill_one(api, store, "source", "user", {"createdAt": "2025-01-01"})
        store.pool.execute.assert_not_awaited()
        api.trends.side_effect = None
        api.trends.return_value = {"days": []}
        with patch("collector.sources.eight_sleep.save_days", AsyncMock(return_value=False)):
            await backfill_one(api, store, "source", "user", {"createdAt": "2025-01-01"})
        store.pool.execute.assert_not_awaited()

    async def test_rejected_login_never_echoes_credentials(self):
        def handler(request):
            return httpx.Response(400, json={"password": "private", "message": "private"})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            with self.assertRaises(APIError) as caught:
                await EightAPI("private", "private", http).authenticate()
        self.assertEqual(str(caught.exception), "HTTP 400")


if __name__ == "__main__":
    unittest.main()
