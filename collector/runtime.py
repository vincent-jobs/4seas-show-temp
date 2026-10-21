"""Host-specific setup; macOS uses CoreBluetooth and a loopback PostgreSQL port."""
import os
import sys
from pathlib import Path


def configure_bluetooth_bus():
    if sys.platform != "linux":
        return
    host_socket = Path("/run/host/run/dbus/system_bus_socket")
    if not Path("/run/dbus/system_bus_socket").exists() and host_socket.is_socket():
        os.environ.setdefault("DBUS_SYSTEM_BUS_ADDRESS", f"unix:path={host_socket}")
    # Rootless containers must authenticate using the UID seen by the host bus.
    uid = os.geteuid()
    for line in Path("/proc/self/uid_map").read_text().splitlines():
        inside, outside, size = map(int, line.split())
        if inside <= uid < inside + size:
            os.environ.setdefault("BLEAK_DBUS_AUTH_UID", str(outside + uid - inside))
            break



def database_options():
    return {
        "host": "127.0.0.1" if sys.platform == "darwin" else "db",
        "database": "postgres", "user": "postgres",
        "password": os.environ.get("POSTGRES_PASSWORD", "docker"),
        "min_size": 1, "max_size": 5, "command_timeout": 10,
    }
