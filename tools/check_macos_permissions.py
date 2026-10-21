"""Request macOS permissions and report device access without writing samples."""
import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bleak import BleakScanner
from collector.sources.airgradient import resolve_address, fetch_snapshot
from collector.sources.heart_rate import SERVICE


async def bluetooth():
    try:
        devices = await BleakScanner.discover(timeout=10, service_uuids=[SERVICE])
        print("蓝牙扫描成功：" + ", ".join(f"{d.name} ({d.address})" for d in devices), flush=True)
    except Exception as error:
        print(f"蓝牙检查：{error}", flush=True)


async def network():
    try:
        address = await resolve_address()
        _, payload = await asyncio.to_thread(fetch_snapshot, address)
        print(f"本地网络读取成功：{address}，共 {len(payload)} 个字段", flush=True)
    except Exception as error:
        print(f"本地网络检查：{type(error).__name__} {error}", flush=True)


async def main():
    await asyncio.gather(bluetooth(), network())


if __name__ == "__main__":
    asyncio.run(main())
