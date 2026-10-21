"""Select BLE for public-address sensors that also advertise BR/EDR support."""

import asyncio
import sys

if sys.platform == "linux":
    from bleak.backends.bluezdbus.utils import assert_reply, get_dbus_authenticator
    from dbus_fast import BusType, Message, MessageType, Variant
    from dbus_fast.aio import MessageBus


async def prefer_ble(device):
    if sys.platform != "linux":
        return
    details = getattr(device, "details", {})
    if not isinstance(details, dict) or "path" not in details:
        return
    props = details.get("props", {})
    flags = props.get("AdvertisingFlags", b"")
    # Random addresses are already BLE-only. Flag 0x04 excludes BR/EDR.
    if (
        props.get("AddressType") != "public"
        or not flags
        or flags[0] & 0x04
        or props.get("PreferredBearer") == "le"
    ):
        return

    bus = MessageBus(bus_type=BusType.SYSTEM, auth=get_dbus_authenticator())
    try:
        async with asyncio.timeout(5):
            await bus.connect()
            reply = await bus.call(Message(
                destination="org.bluez",
                path=details["path"],
                interface="org.freedesktop.DBus.Properties",
                member="Set",
                signature="ssv",
                body=["org.bluez.Device1", "PreferredBearer", Variant("s", "le")],
            ))
        if reply.message_type == MessageType.ERROR and reply.error_name in {
            "org.freedesktop.DBus.Error.UnknownProperty",
            "org.freedesktop.DBus.Error.InvalidArgs",
            "org.bluez.Error.NotSupported",
        }:
            raise RuntimeError(
                "此设备需要指定 BLE 连接；请在宿主机 /etc/bluetooth/main.conf "
                "的 [General] 中设置 Experimental=true 并重启 bluetooth"
            )
        assert_reply(reply)
    finally:
        bus.disconnect()
