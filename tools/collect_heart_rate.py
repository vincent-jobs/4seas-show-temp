#!/usr/bin/env python3
"""Scan local BLE devices and collect standard heart-rate notifications.

Run with the project Python in agent-runner:
  distrobox enter agent-runner -- .venv/bin/python tools/collect_heart_rate.py
  distrobox enter agent-runner -- .venv/bin/python tools/collect_heart_rate.py \
      --name "Xiaomi Smart Band" --seconds 30 --output heart-rate.csv
"""

import argparse
import asyncio
import csv
import os
import sys
from datetime import datetime
from pathlib import Path

from bleak import BleakClient, BleakScanner

# Allow direct execution from tools/ without installing the project.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from collector.bluez import prefer_ble


HEART_RATE_SERVICE = "0000180d-0000-1000-8000-00805f9b34fb"
HEART_RATE_MEASUREMENT = "00002a37-0000-1000-8000-00805f9b34fb"


def configure_system_bus():
    if sys.platform != "linux":
        return
    # Distrobox exposes the host bus here; no Bluetooth daemon is needed inside.
    host_socket = Path("/run/host/run/dbus/system_bus_socket")
    if (
        "DBUS_SYSTEM_BUS_ADDRESS" not in os.environ
        and not Path("/run/dbus/system_bus_socket").exists()
        and host_socket.is_socket()
    ):
        os.environ["DBUS_SYSTEM_BUS_ADDRESS"] = f"unix:path={host_socket}"


def parse_measurement(data):
    if len(data) < 2 or (data[0] & 1 and len(data) < 3):
        raise ValueError("不完整的心率数据包")
    flags = data[0]
    bpm = int.from_bytes(data[1:3], "little") if flags & 1 else data[1]
    contact = "未提供"
    if flags & 4:
        contact = "已接触" if flags & 2 else "未接触"
    return bpm, contact


async def collect(device, seconds, output):
    disconnected = asyncio.Event()
    count = 0
    output_file = None
    writer = None

    def on_measurement(_, data):
        nonlocal count
        raw = data.hex(" ").upper()
        try:
            bpm, contact = parse_measurement(data)
        except ValueError as error:
            print(f"跳过数据：{error}；原始数据 {raw}", flush=True)
            return
        timestamp = datetime.now().astimezone().isoformat(timespec="milliseconds")
        count += 1
        print(
            f"{timestamp}  心率 {bpm} bpm  接触：{contact}  原始数据：{raw}",
            flush=True,
        )
        if writer is not None:
            writer.writerow((timestamp, bpm, contact, raw))
            output_file.flush()

    print(f"连接 {device.name or '未命名设备'} [{device.address}] …", flush=True)
    try:
        await prefer_ble(device)
        async with BleakClient(
            device, disconnected_callback=lambda _: disconnected.set(), timeout=20
        ) as client:
            print("蓝牙已连接，检查心率服务 …", flush=True)
            service = client.services.get_service(HEART_RATE_SERVICE)
            if service is None:
                services = ", ".join(item.uuid for item in client.services)
                raise RuntimeError(
                    "设备没有提供标准心率服务 180D。请开启手环心率广播后重试。"
                    f"\n实际服务：{services}"
                )
            characteristic = service.get_characteristic(HEART_RATE_MEASUREMENT)
            if characteristic is None:
                raise RuntimeError("设备有心率服务，但没有心率测量特征 2A37。")
            if not {"notify", "indicate"}.intersection(characteristic.properties):
                raise RuntimeError("心率测量特征不支持通知。")
            if output:
                # Keep each run separate; never overwrite a previous recording.
                output_file = Path(output).open("x", newline="", encoding="utf-8")
                writer = csv.writer(output_file)
                writer.writerow(("timestamp", "bpm", "contact", "raw"))
                output_file.flush()
            await client.start_notify(characteristic, on_measurement)
            print(f"已订阅心率通知，采集 {seconds:g} 秒 …", flush=True)
            try:
                await asyncio.wait_for(disconnected.wait(), timeout=seconds)
            except TimeoutError:
                pass
            else:
                raise RuntimeError(f"设备提前断开；已收到 {count} 个样本。")
    finally:
        if output_file is not None:
            output_file.close()
    print(f"采集结束，共收到 {count} 个心率样本。", flush=True)
    if not count:
        raise RuntimeError("连接成功，但没有收到心率通知。请检查佩戴及心率广播状态。")


async def run(args):
    configure_system_bus()
    backend = "CoreBluetooth" if sys.platform == "darwin" else "BlueZ"
    print(f"使用本机 {backend} 扫描 BLE 设备，持续 {args.scan_seconds:g} 秒 …", flush=True)
    found = await BleakScanner.discover(timeout=args.scan_seconds, return_adv=True, service_uuids=[HEART_RATE_SERVICE])
    devices = sorted(
        found.values(),
        key=lambda item: (not bool(item[1].local_name or item[0].name), -item[1].rssi),
    )
    matches = []
    for device, advertisement in devices:
        name = advertisement.local_name or device.name or "未命名设备"
        heart_rate = HEART_RATE_SERVICE in advertisement.service_uuids
        print(
            f"{device.address}  {name}  RSSI={advertisement.rssi} dBm"
            f"  心率广播={'是' if heart_rate else '未声明'}",
            flush=True,
        )
        if args.address and device.address.casefold() == args.address.casefold():
            matches.append(device)
        elif args.name and args.name.casefold() in name.casefold():
            matches.append(device)
    print(f"共发现 {len(devices)} 台设备。", flush=True)
    if not args.address and not args.name:
        print("使用 --address 地址 或 --name 名称片段 选择手环并开始采集。", flush=True)
        return
    if len(matches) != 1:
        raise RuntimeError(
            f"匹配到 {len(matches)} 台设备。"
            "请确认手环在附近并开启广播；若有重名设备，请使用 --address。"
        )
    await collect(matches[0], args.seconds, args.output)


def positive_seconds(value):
    number = float(value)
    if not 0 < number <= 3600:
        raise argparse.ArgumentTypeError("秒数必须大于 0 且不超过 3600")
    return number


def main():
    parser = argparse.ArgumentParser(description="用本机蓝牙扫描并采集标准 BLE 心率")
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--address", help="扫描到的手环标识（macOS 为 UUID，Linux 为蓝牙地址）")
    target.add_argument("--name", help="手环名称片段；必须唯一匹配")
    parser.add_argument("--scan-seconds", type=positive_seconds, default=12)
    parser.add_argument("--seconds", type=positive_seconds, default=30)
    parser.add_argument("--output", help="将真实心率样本写入一个新的 CSV 文件")
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        print("\n采集已停止。", flush=True)
        return 130
    except Exception as error:
        print(f"采集失败 [{type(error).__name__}]：{error}", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
