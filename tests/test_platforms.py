import asyncio
import os
import socket
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from collector.runtime import configure_bluetooth_bus, database_options
from collector.bluez import prefer_ble
from collector.sources import airgradient, heart_rate
from tools.start_macos import collector_environment


class MacRuntimeTests(unittest.IsolatedAsyncioTestCase):
    def test_mac_does_not_read_linux_proc_or_dbus_paths(self):
        with patch("sys.platform", "darwin"), patch("collector.runtime.Path") as path:
            configure_bluetooth_bus()
            path.assert_not_called()
            self.assertEqual(database_options()["host"], "127.0.0.1")
        with patch("sys.platform", "linux"):
            self.assertEqual(database_options()["host"], "db")

    async def test_mac_does_not_set_bluez_bearer_even_with_linux_shaped_details(self):
        with patch("sys.platform", "darwin"), patch("collector.bluez.MessageBus", create=True) as bus:
            await prefer_ble(SimpleNamespace(details={"path": "/org/bluez/hci0/device"}))
            bus.assert_not_called()

    async def test_bonjour_resolution_uses_host_resolver(self):
        loop = asyncio.get_running_loop()
        resolved = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.8", 80))]
        with patch("sys.platform", "darwin"), patch.object(loop, "getaddrinfo", new=AsyncMock(return_value=resolved)) as resolver:
            self.assertEqual(await airgradient.resolve_address(), "192.168.1.8")
            resolver.assert_awaited_once_with(airgradient.HOST, 80, family=socket.AF_INET, type=socket.SOCK_STREAM)

    async def test_discovery_accepts_corebluetooth_uuid_and_filters_heart_service(self):
        device = SimpleNamespace(address="243E23AE-4A99-406C-B317-18F1BD7B4CBE", name="Band")
        advertisement = SimpleNamespace(service_uuids=[heart_rate.SERVICE], local_name="Band", rssi=-50)
        store = SimpleNamespace(discover=AsyncMock(), enabled=AsyncMock(return_value=set()))
        with patch.object(heart_rate.BleakScanner, "discover", new=AsyncMock(return_value={"device": (device, advertisement)})) as scanner, patch(
            "collector.sources.heart_rate.asyncio.sleep", new=AsyncMock(side_effect=asyncio.CancelledError)
        ):
            with self.assertRaises(asyncio.CancelledError):
                await heart_rate.run(store)
        scanner.assert_awaited_once_with(timeout=5, return_adv=True, service_uuids=[heart_rate.SERVICE])
        self.assertEqual(store.discover.await_args.args[0], "ble:243e23ae-4a99-406c-b317-18f1bd7b4cbe")
        self.assertEqual(store.discover.await_args.args[5]["address"], device.address)

    def test_compose_values_are_passed_literally_without_sourcing_env(self):
        configured = {"services": {"collector": {"environment": {
            "POSTGRES_PASSWORD": "docker", "EIGHT_EMAIL": "test@example.test",
            "EIGHT_PASSWORD": "literal$with#characters", "UNRELATED": "ignored",
        }}}}
        env = collector_environment(configured, {"PATH": "/usr/bin", "EIGHT_PASSWORD": "old"})
        self.assertEqual(env["EIGHT_PASSWORD"], "literal$with#characters")
        self.assertEqual(env["PATH"], "/usr/bin")
        self.assertNotIn("UNRELATED", env)
