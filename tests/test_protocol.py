import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from collector.sources.heart_rate import collect, parse_measurement


class HeartRateProtocolTests(unittest.TestCase):
    def test_real_band_packet(self):
        value, metadata = parse_measurement(bytes.fromhex("06 66"))
        self.assertEqual(value, 102)
        self.assertIs(metadata["contact"], True)
        self.assertEqual(metadata["raw"], "06 66")

    def test_uint16_little_endian(self):
        value, metadata = parse_measurement(bytes.fromhex("07 2c 01"))
        self.assertEqual(value, 300)
        self.assertIs(metadata["contact"], True)

    def test_removed_band_zero_is_not_a_pulse_or_proof_of_contact(self):
        for packet in ("06 00", "07 00 00"):
            with self.subTest(packet=packet):
                value, metadata = parse_measurement(bytes.fromhex(packet))
                self.assertIsNone(value)
                self.assertIs(metadata["contact"], True)  # Preserve the misleading device flag.
                self.assertEqual(metadata["reported_bpm"], 0)
                self.assertIs(metadata["measurement_valid"], False)
                self.assertEqual(metadata["raw"], packet)

    def test_no_contact_reading_preserved_but_not_used_as_heart_rate(self):
        value, metadata = parse_measurement(bytes.fromhex("04 48"))
        self.assertIsNone(value)
        self.assertEqual(metadata["reported_bpm"], 72)
        self.assertIs(metadata["contact"], False)

    def test_readings_recover_without_reconnecting(self):
        values = [parse_measurement(bytes.fromhex(raw))[0] for raw in ("06 48", "06 00", "06 49")]
        self.assertEqual(values, [72, None, 73])

    def test_contact_unknown_is_distinct_from_no_contact(self):
        for flags, expected in ((0, None), (2, None), (4, False), (6, True)):
            with self.subTest(flags=flags):
                _, metadata = parse_measurement(bytes((flags, 72)))
                self.assertIs(metadata["contact"], expected)

    def test_truncated_packets_are_rejected(self):
        for packet in (b"", b"\x00", b"\x01\x48"):
            with self.subTest(packet=packet), self.assertRaises(ValueError):
                parse_measurement(packet)

    def test_optional_rr_data_does_not_change_heart_rate(self):
        value, _ = parse_measurement(bytes.fromhex("16 48 00 04"))
        self.assertEqual(value, 72)


class ConnectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_zero_notifications_are_skipped_and_valid_readings_resume(self):
        store = SimpleNamespace(status=AsyncMock(), write=AsyncMock())
        client = MagicMock()
        client.__aenter__.return_value = client
        client.__aexit__ = AsyncMock(return_value=False)
        async def notify(_, callback):
            for raw in ("06 48", "06 00", "07 00 00", "04 48", "06 49"):
                callback(None, bytes.fromhex(raw))
        client.start_notify = AsyncMock(side_effect=notify)
        with patch("collector.sources.heart_rate.prefer_ble", new=AsyncMock()), patch(
            "collector.sources.heart_rate.BleakClient", return_value=client
        ) as constructor:
            async def saved(_, value, *args):
                if value == 73:
                    constructor.call_args.kwargs["disconnected_callback"](None)
            store.write.side_effect = saved
            await collect(store, "test:device", object())
        self.assertEqual([call.args[1] for call in store.write.await_args_list], [72, 73])
        self.assertEqual(sum(call.args[1] == "waiting" for call in store.status.await_args_list), 4)
        constructor.assert_called_once()
        self.assertEqual(constructor.call_args.kwargs["timeout"], 30)
        self.assertTrue(all(call.kwargs.get("seen") for call in store.status.await_args_list if call.args[1] == "waiting"))

    async def test_connection_timeout_is_reported_to_the_dashboard(self):
        store = SimpleNamespace(status=AsyncMock())
        with patch("collector.sources.heart_rate.BleakClient") as client:
            client.return_value.__aenter__.side_effect = TimeoutError()
            await collect(store, "test:device", object())
        store.status.assert_awaited_with(
            "test:device", "error", "连接超时，请确认心率广播已开启且设备可连接"
        )


if __name__ == "__main__":
    unittest.main()
