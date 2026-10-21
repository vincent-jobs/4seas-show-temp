#!/usr/bin/env python3
"""Start Docker web/db and install the native macOS login collector."""
import argparse
import json
import runpy
import os
from pathlib import Path
import platform
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ["docker", "compose", "-f", "compose.yaml", "-f", "compose.macos.yaml"]


def collector_environment(config, inherited=None):
    env = dict(os.environ if inherited is None else inherited)
    configured = config["services"]["collector"].get("environment", {})
    for key in ("POSTGRES_PASSWORD", "EIGHT_EMAIL", "EIGHT_PASSWORD"):
        env[key] = str(configured.get(key) or "")
    env["PYTHONUNBUFFERED"] = "1"
    return env


def main():
    if sys.platform != "darwin":
        raise RuntimeError("此入口用于 macOS；Linux 请使用 docker compose up -d --build。")
    if sys.version_info < (3, 11):
        raise RuntimeError("需要 Python 3.11 或更新版本，建议使用原生 Python 3.13。")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-only", action="store_true", help="只启动已安装的本机采集器")
    args = parser.parse_args()
    os.chdir(ROOT)
    docker_bins = [str(Path.home() / ".docker/bin"),
                   str(Path.home() / "Applications/Docker.app/Contents/Resources/bin"),
                   "/Applications/Docker.app/Contents/Resources/bin"]
    os.environ["PATH"] = os.pathsep.join(docker_bins + [os.environ.get("PATH", "")])
    # Compose parses .env quoting/interpolation; never execute it as shell code.
    result = subprocess.run(COMPOSE + ["--profile", "linux-bluetooth", "config", "--format", "json"],
                            check=True, capture_output=True, text=True)
    config = json.loads(result.stdout)
    python = ROOT / ".venv" / "bin" / "python"
    if not python.exists():
        venv.EnvBuilder(with_pip=True).create(ROOT / ".venv")
    info = subprocess.run([str(python), "-c",
        "import platform; print(platform.system(), platform.machine())"],
        check=True, capture_output=True, text=True)
    if info.stdout.strip() != f"Darwin {platform.machine()}":
        raise RuntimeError(".venv 来自其他系统或架构，请移走它后重新运行本命令。")
    if not args.run_only:
        subprocess.run([str(python), "-m", "pip", "install", "--only-binary=:all:", "-r", "collector/requirements.txt"], check=True)

    if not args.run_only:
        subprocess.run(COMPOSE + ["stop", "collector"], check=True)
        subprocess.run(COMPOSE + ["up", "-d", "--wait", "db"], check=True)
        subprocess.run(COMPOSE + ["exec", "-T", "db", "psql", "-U", "postgres", "-d", "postgres", "-v", "ON_ERROR_STOP=1", "-f", "/docker-entrypoint-initdb.d/005-parallel-experiences.sql"], check=True)
        subprocess.run(COMPOSE + ["up", "-d", "--build", "--wait", "web"], check=True)
        subprocess.run([str(python), str(ROOT / "tools/install_macos_service.py")], check=True)
        print("页面：http://localhost:3000；局域网通过 Mac 的 IP:3000 访问；管理页 /manage", flush=True)
        print("请允许“4seas 采集器”访问蓝牙和本地网络。关闭终端不影响采集。", flush=True)
        return

    import fcntl
    with (ROOT / ".venv" / "collector.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("此项目的 Mac 采集器已在运行。") from None
        os.environ.update(collector_environment(config))
        sys.path.insert(0, str(ROOT))
        # Preserve the application bundle identity used by macOS privacy controls.
        runpy.run_module("collector", run_name="__main__")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        raise SystemExit(130)
    except (OSError, RuntimeError, subprocess.CalledProcessError, ValueError) as error:
        # Config output contains credentials; do not include captured stdout/stderr.
        message = ("启动命令失败，请检查 Docker Desktop、Compose 和 Python 环境。"
                   if isinstance(error, subprocess.CalledProcessError) else str(error))
        print(f"启动失败：{message}", file=sys.stderr)
        raise SystemExit(1)
