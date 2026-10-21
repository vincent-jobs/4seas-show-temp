#!/usr/bin/env python3
"""Install the user-level macOS collector app and login service."""
import argparse
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
IDENTIFIER = "local.fourseas.collector"
APP = ROOT / ".runtime" / "4seas 采集器.app"


def app_environment():
    version = f"python{sys.version_info.major}.{sys.version_info.minor}"
    return {
        "PYTHONHOME": sys.base_prefix,
        "PYTHONPATH": str(ROOT / ".venv" / "lib" / version / "site-packages"),
        "PYTHONUNBUFFERED": "1",
    }


def build_app():
    contents = APP / "Contents"
    binary = contents / "MacOS" / "fourseas"
    binary.parent.mkdir(parents=True, exist_ok=True)
    # Keep the standalone Python's relative dylib layout.
    libraries = contents / "lib"
    if not libraries.exists():
        libraries.symlink_to(Path(sys.base_prefix) / "lib", target_is_directory=True)
    shutil.copy2(Path(sys.executable).resolve(), binary)
    info = {
        "CFBundleIdentifier": IDENTIFIER,
        "CFBundleName": "4seas 采集器",
        "CFBundleDisplayName": "4seas 采集器",
        "CFBundleExecutable": "fourseas",
        "CFBundlePackageType": "APPL",
        "CFBundleVersion": "1",
        "CFBundleShortVersionString": "1.0",
        "LSUIElement": True,
        "NSBluetoothAlwaysUsageDescription": "连接您的心率手环，采集体验期间的心率数据。",
        "NSLocalNetworkUsageDescription": "连接同一 Wi-Fi 内的环境传感器，采集温湿度、二氧化碳等环境数据。",
        "LSEnvironment": app_environment(),
    }
    with (contents / "Info.plist").open("wb") as stream:
        plistlib.dump(info, stream)
    subprocess.run(["/usr/bin/codesign", "--force", "--sign", "-", "--identifier",
                    IDENTIFIER, str(APP)], check=True)
    return binary


def install_service(binary):
    log_dir = ROOT / ".runtime"
    agent = Path.home() / "Library" / "LaunchAgents" / f"{IDENTIFIER}.plist"
    agent.parent.mkdir(parents=True, exist_ok=True)
    config = {
        "Label": IDENTIFIER,
        "ProgramArguments": [str(binary), str(ROOT / "tools/start_macos.py"), "--run-only"],
        "WorkingDirectory": str(ROOT),
        "EnvironmentVariables": {**app_environment(), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin"},
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 15,
        "StandardOutPath": str(log_dir / "collector.log"),
        "StandardErrorPath": str(log_dir / "collector.log"),
    }
    with agent.open("wb") as stream:
        plistlib.dump(config, stream)
    agent.chmod(0o600)
    domain = f"gui/{os.getuid()}"
    subprocess.run(["launchctl", "bootout", f"{domain}/{IDENTIFIER}"], capture_output=True)
    subprocess.run(["launchctl", "bootstrap", domain, str(agent)], check=True)
    print("已安装登录后自动启动的 4seas 采集器。")


def main():
    if sys.platform != "darwin":
        raise SystemExit("此脚本仅用于 macOS。")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-only", action="store_true", help="只准备应用，不启动正式采集")
    args = parser.parse_args()
    binary = build_app()
    if not args.prepare_only:
        install_service(binary)
    print(APP)


if __name__ == "__main__":
    main()
