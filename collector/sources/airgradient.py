"""One complete local-API snapshot per second for the configured monitor."""

import asyncio
import http.client
import json
import logging
import math
import socket
import sys
from datetime import datetime, timezone

if sys.platform == "linux":
    from bleak.backends.bluezdbus.utils import assert_reply, get_dbus_authenticator
    from dbus_fast import BusType, Message
    from dbus_fast.aio import MessageBus

from collector.store import Store


logger = logging.getLogger(__name__)
SERIAL = "e83dc16b9dcc"
HOST = f"airgradient_{SERIAL}.local"
SOURCE_ID = f"airgradient:{SERIAL}"
KIND = "airgradient"
INTERVAL = 1.0
TIMEOUT = 30.0


async def resolve_address():
    if sys.platform == "darwin":
        # macOS resolves .local via Bonjour on the host, outside Docker's VM.
        async with asyncio.timeout(TIMEOUT):
            addresses = await asyncio.get_running_loop().getaddrinfo(
                HOST, 80, family=socket.AF_INET, type=socket.SOCK_STREAM)
        if not addresses:
            raise RuntimeError("Bonjour 未找到环境设备")
        return addresses[0][4][0]
    # Host Avahi can see Wi-Fi multicast; the Docker bridge cannot. Reuse the
    # existing system-bus mount instead of adding host networking or a fixed IP.
    bus = MessageBus(bus_type=BusType.SYSTEM, auth=get_dbus_authenticator())
    try:
        async with asyncio.timeout(TIMEOUT):
            await bus.connect()
            reply = await bus.call(Message(
                destination="org.freedesktop.Avahi",
                path="/",
                interface="org.freedesktop.Avahi.Server",
                member="ResolveHostName",
                signature="iisiu",
                body=[-1, 0, HOST, 0, 0],
            ))
        assert_reply(reply)
        return reply.body[4]
    finally:
        bus.disconnect()


def reject_nonfinite(value):
    raise ValueError(f"设备返回了无效 JSON 数值：{value}")


def parse_snapshot(body):
    payload = json.loads(body, parse_constant=reject_nonfinite)
    if not isinstance(payload, dict) or payload.get("serialno") != SERIAL:
        raise ValueError("返回的设备序列号不符，正在重新发现 AirGradient")
    # Preserve every field, including strings, nulls and future firmware fields.
    # A missing CO2 sensor must not discard the other measurements.
    value = payload.get("rco2")
    if type(value) not in (int, float) or not math.isfinite(value):
        value = None
    return value, payload


def fetch_snapshot(address):
    connection = http.client.HTTPConnection(address, 80, timeout=TIMEOUT)
    try:
        # http.client connects directly and does not use HTTP proxy env vars.
        connection.request("GET", "/measures/current", headers={"Accept": "application/json"})
        response = connection.getresponse()
        if response.status != 200:
            raise RuntimeError(f"AirGradient HTTP {response.status}")
        body = response.read(256 * 1024 + 1)
        if len(body) > 256 * 1024:
            raise ValueError("AirGradient 响应超过 256 KiB")
        return parse_snapshot(body)
    finally:
        connection.close()


def next_deadline(previous, now):
    deadline = previous + INTERVAL
    # Slow requests skip missed slots; never burst or manufacture missing rows.
    return deadline if deadline > now else now + INTERVAL


def merge_display(previous, current, recorded_at):
    """Retain valid numeric readings separately from the untouched raw snapshot."""
    previous = previous or {}
    values = dict(previous.get("measurements") or {})
    times = dict(previous.get("updated_at") or {})
    for key, value in current.items():
        if type(value) not in (int, float) or not math.isfinite(value):
            continue
        values[key] = value
        times[key] = recorded_at
    return {"measurements": values, "updated_at": times}


async def restore_display(store):
    rows = await store.pool.fetch(
        """SELECT recorded_at, metadata->'display' AS display,
                  metadata->'measurements' AS measurements
           FROM samples WHERE source_id=$1 ORDER BY recorded_at DESC,id DESC LIMIT 120""",
        SOURCE_ID)
    state, pending = {}, []
    for row in rows:
        saved = row["display"]
        if saved:
            state = json.loads(saved) if isinstance(saved, str) else saved
            break
        pending.append(row)
    for row in reversed(pending):
        current = row["measurements"]
        current = json.loads(current) if isinstance(current, str) else current or {}
        state = merge_display(state, current, row["recorded_at"].isoformat())
    return state


async def run(store: Store):
    async def register(address=None):
        await store.discover(
            SOURCE_ID, f"AirGradient · {SERIAL[-6:]}", KIND, "air_quality", "ppm",
            {"serialno": SERIAL, "hostname": HOST, "address": address},
            enabled=True,
        )

    await register()
    display = await restore_display(store)
    address = None
    streaming = False
    loop = asyncio.get_running_loop()
    deadline = loop.time()
    while True:
        if SOURCE_ID not in await store.enabled(KIND):
            streaming = False
            await asyncio.sleep(INTERVAL)
            deadline = loop.time()
            continue
        try:
            if address is None:
                await store.status(SOURCE_ID, "connecting")
                address = await resolve_address()
                await register(address)
                logger.info("%s: 已发现 %s", SOURCE_ID, address)
            value, payload = await asyncio.to_thread(fetch_snapshot, address)
            received = datetime.now(timezone.utc)
            display = merge_display(display, payload, received.isoformat())
            await store.write(
                SOURCE_ID, value, received,
                {"measurements": payload, "address": address, "display": display},
            )
            if not streaming:
                logger.info("%s: 每秒采集完整快照，当前 %d 个字段", SOURCE_ID, len(payload))
                streaming = True
        except asyncio.CancelledError:
            raise
        except Exception as error:
            message = str(error) or type(error).__name__
            if isinstance(error, TimeoutError):
                message = "AirGradient 连接超时，正在重新发现设备"
            logger.warning("%s: %s", SOURCE_ID, message)
            await store.status(SOURCE_ID, "error", message)
            address = None
            streaming = False
            await asyncio.sleep(5)
            deadline = loop.time()
            continue
        deadline = next_deadline(deadline, loop.time())
        await asyncio.sleep(max(0, deadline - loop.time()))
