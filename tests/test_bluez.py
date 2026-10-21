import unittest
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

if sys.platform != "linux":
    raise unittest.SkipTest("BlueZ tests only apply to Linux")

from dbus_fast import Message, MessageType

from collector.bluez import prefer_ble


def sensor(address_type="public", flags=b"\x08"):
    return SimpleNamespace(details={
        "path": "/org/bluez/hci0/dev_74_FB_17_26_4D_28",
        "props": {"AddressType": address_type, "AdvertisingFlags": flags},
    })


class BlueZTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_dual_mode_sensor_selects_le_before_connection(self):
        bus = SimpleNamespace(
            connect=AsyncMock(),
            call=AsyncMock(return_value=Message(
                message_type=MessageType.METHOD_RETURN, reply_serial=1,
            )),
            disconnect=Mock(),
        )
        with patch("collector.bluez.MessageBus", return_value=bus):
            await prefer_ble(sensor())
        request = bus.call.await_args.args[0]
        self.assertEqual(request.path, sensor().details["path"])
        self.assertEqual(request.body[:2], ["org.bluez.Device1", "PreferredBearer"])
        self.assertEqual(request.body[2].value, "le")
        bus.disconnect.assert_called_once()

    async def test_ble_only_sensors_do_not_require_experimental_bluez(self):
        with patch("collector.bluez.MessageBus") as bus:
            await prefer_ble(sensor("random"))
            await prefer_ble(sensor(flags=b"\x06"))
            bus.assert_not_called()

    async def test_missing_interface_has_actionable_error_and_closes_bus(self):
        bus = SimpleNamespace(
            connect=AsyncMock(),
            call=AsyncMock(return_value=Message(
                message_type=MessageType.ERROR, reply_serial=1,
                error_name="org.freedesktop.DBus.Error.UnknownProperty",
                signature="s", body=["Unknown property PreferredBearer"],
            )),
            disconnect=Mock(),
        )
        with patch("collector.bluez.MessageBus", return_value=bus):
            with self.assertRaisesRegex(RuntimeError, "Experimental=true"):
                await prefer_ble(sensor())
        bus.disconnect.assert_called_once()


if __name__ == "__main__":
    unittest.main()
