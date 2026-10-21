import asyncio
import logging
from datetime import datetime, timezone

from bleak import BleakClient, BleakScanner

from collector.bluez import prefer_ble
from collector.store import Store


logger = logging.getLogger(__name__)
SERVICE = "0000180d-0000-1000-8000-00805f9b34fb"
MEASUREMENT = "00002a37-0000-1000-8000-00805f9b34fb"
KIND = "ble_heart_rate"


def parse_measurement(data):
    if len(data) < 2 or (data[0] & 1 and len(data) < 3):
        raise ValueError("不完整的心率数据包")
    flags = data[0]
    value = int.from_bytes(data[1:3], "little") if flags & 1 else data[1]
    contact = None if not flags & 4 else bool(flags & 2)
    # This band keeps contact=True after removal and broadcasts "06 00".
    # Preserve flags while parsing; invalid notifications never become samples.
    valid = value > 0 and contact is not False
    return value if valid else None, {
        "contact": contact, "reported_bpm": value, "measurement_valid": valid,
        "raw": data.hex(" ").upper(),
    }


async def collect(store: Store, source_id, device):
    queue = asyncio.Queue(maxsize=256)
    overflow = False
    disconnected = asyncio.Event()

    def on_measurement(_, data):
        nonlocal overflow
        try:
            value, metadata = parse_measurement(data)
            queue.put_nowait((value, datetime.now(timezone.utc), metadata))
        except ValueError:
            logger.warning("%s: 跳过不完整数据包", source_id)
        except asyncio.QueueFull:
            overflow = True

    try:
        await store.status(source_id, "connecting")
        await prefer_ble(device)
        async with BleakClient(
            device, timeout=30, disconnected_callback=lambda _: disconnected.set()
        ) as client:
            service = client.services.get_service(SERVICE)
            characteristic = service.get_characteristic(MEASUREMENT) if service else None
            if characteristic is None:
                raise RuntimeError("设备未提供心率测量服务，请开启心率广播")
            await client.start_notify(characteristic, on_measurement)
            await store.status(source_id, "waiting", seen=True)
            logger.info("%s: 已订阅心率通知", source_id)
            last_received = asyncio.get_running_loop().time()
            while not disconnected.is_set():
                if overflow:
                    raise RuntimeError("数据库写入积压，通知队列已满；将重新连接")
                try:
                    value, timestamp, metadata = await asyncio.wait_for(queue.get(), 2)
                except TimeoutError:
                    if asyncio.get_running_loop().time() - last_received > 30:
                        raise RuntimeError("30 秒未收到心率通知，请检查佩戴和心率广播")
                    continue
                last_received = asyncio.get_running_loop().time()
                if value is None or value <= 0:
                    # Keep the connection alive, but never save an invalid/zero
                    # measurement or present the previous pulse as current.
                    await store.status(source_id, "waiting", seen=True)
                    continue
                await store.write(source_id, value, timestamp, metadata)
            raise RuntimeError("蓝牙连接已断开，正在重试")
    except asyncio.CancelledError:
        await store.status(source_id, "offline")
        raise
    except Exception as error:
        message = (
            "连接超时，请确认心率广播已开启且设备可连接"
            if isinstance(error, TimeoutError)
            else str(error) or type(error).__name__
        )
        logger.warning("%s: %s", source_id, message)
        await store.status(source_id, "error", message)


async def run(store: Store):
    tasks = {}
    devices = {}
    try:
        while True:
            try:
                found = await BleakScanner.discover(timeout=5, return_adv=True, service_uuids=[SERVICE])
            except Exception as error:
                # Discovery is independent of established notification streams.
                # A transient scan failure must not disconnect every wearer.
                logger.warning("蓝牙扫描暂时失败，将重试；保留已有连接：%s", error)
                found = {}
            for device, advertisement in found.values():
                if SERVICE not in advertisement.service_uuids:
                    continue
                source_id = f"ble:{device.address.lower()}"
                name = advertisement.local_name or device.name or device.address
                devices[source_id] = device
                await store.discover(
                    source_id, name, KIND, "heart_rate", "bpm",
                    {"address": device.address, "rssi": advertisement.rssi},
                )
            enabled = await store.enabled(KIND)
            for source_id, task in list(tasks.items()):
                if source_id not in enabled or task.done():
                    if not task.done():
                        task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                    del tasks[source_id]
            for source_id in enabled:
                if source_id in devices and source_id not in tasks:
                    tasks[source_id] = asyncio.create_task(
                        collect(store, source_id, devices[source_id])
                    )
            await asyncio.sleep(5)
    finally:
        for task in tasks.values():
            task.cancel()
        await asyncio.gather(*tasks.values(), return_exceptions=True)
