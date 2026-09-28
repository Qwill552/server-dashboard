"""Collect read-only metrics from the host operating system."""

from __future__ import annotations

import collections
import os
import platform
import socket
import subprocess
import threading
import time
from typing import Any

import psutil


INTERVAL_SECONDS = 3
HISTORY_SIZE = 240  # Twelve minutes at the default sampling interval.


def _bytes_per_second(current: int, previous: int, elapsed: float) -> float:
    if elapsed <= 0 or current < previous:
        return 0.0
    return round((current - previous) / elapsed, 1)


def _cpu_temperature() -> float | None:
    try:
        sensors = psutil.sensors_temperatures()
    except (AttributeError, OSError):
        return None

    # A generic ACPI thermal zone is not necessarily the CPU. Only use sensors
    # explicitly identified as CPU/package/core sensors.
    for chip_name, readings in sensors.items():
        if any(name in chip_name.lower() for name in ("coretemp", "k10temp", "cpu", "zenpower")):
            values = [reading.current for reading in readings if reading.current is not None]
            if values:
                return round(max(values), 1)
    return None


def _caddy_status() -> dict[str, str]:
    service = os.environ.get("CADDY_SERVICE_NAME", "caddy.service")
    try:
        result = subprocess.run(
            ["systemctl", "is-active", service],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return {"state": "unknown", "detail": "Не удалось проверить systemd"}

    state = result.stdout.strip()
    if state == "active":
        return {"state": "online", "detail": "Сервис работает"}
    if state in {"inactive", "failed", "activating", "deactivating"}:
        return {"state": "offline", "detail": state}
    return {"state": "unknown", "detail": state or "Сервис не найден"}


def _network_counters() -> tuple[int, int]:
    interfaces = psutil.net_io_counters(pernic=True)
    stats = psutil.net_if_stats()
    active = [
        counters
        for name, counters in interfaces.items()
        if name != "lo" and stats.get(name) and stats[name].isup
    ]
    return sum(item.bytes_recv for item in active), sum(item.bytes_sent for item in active)


class MetricsSampler:
    def __init__(self, interval: int = INTERVAL_SECONDS) -> None:
        self.interval = interval
        self._lock = threading.Lock()
        self._snapshot: dict[str, Any] | None = None
        self._history: collections.deque[dict[str, Any]] = collections.deque(maxlen=HISTORY_SIZE)
        self._previous_time: float | None = None
        self._previous_disk: tuple[int, int] | None = None
        self._previous_network: tuple[int, int] | None = None
        psutil.cpu_percent(interval=None)
        psutil.cpu_percent(interval=None, percpu=True)

    def sample(self) -> dict[str, Any]:
        now = time.time()
        monotonic = time.monotonic()
        elapsed = monotonic - self._previous_time if self._previous_time is not None else 0

        memory = psutil.virtual_memory()
        swap = psutil.swap_memory()
        disk = psutil.disk_usage("/")
        disk_counters = psutil.disk_io_counters()
        disk_totals = (
            disk_counters.read_bytes if disk_counters else 0,
            disk_counters.write_bytes if disk_counters else 0,
        )
        network_totals = _network_counters()
        frequency = psutil.cpu_freq()
        try:
            load = [round(value, 2) for value in os.getloadavg()]
        except (AttributeError, OSError):
            load = []

        previous_disk = self._previous_disk or disk_totals
        previous_network = self._previous_network or network_totals
        cpu_percent = round(psutil.cpu_percent(interval=None), 1)
        snapshot = {
            "timestamp": round(now * 1000),
            "host": socket.gethostname(),
            "platform": f"{platform.system()} {platform.release()}",
            "uptime_seconds": max(0, round(now - psutil.boot_time())),
            "cpu": {
                "percent": cpu_percent,
                "per_core": [round(value, 1) for value in psutil.cpu_percent(interval=None, percpu=True)],
                "cores": psutil.cpu_count(logical=True) or 0,
                "frequency_mhz": round(frequency.current) if frequency else None,
                "load": load,
            },
            "memory": {
                "percent": round(memory.percent, 1),
                "used": memory.used,
                "total": memory.total,
                "swap_used": swap.used,
                "swap_total": swap.total,
            },
            "disk": {
                "percent": round(disk.percent, 1),
                "used": disk.used,
                "total": disk.total,
                "read_bps": _bytes_per_second(disk_totals[0], previous_disk[0], elapsed),
                "write_bps": _bytes_per_second(disk_totals[1], previous_disk[1], elapsed),
            },
            "network": {
                "receive_bps": _bytes_per_second(network_totals[0], previous_network[0], elapsed),
                "send_bps": _bytes_per_second(network_totals[1], previous_network[1], elapsed),
                "received_total": network_totals[0],
                "sent_total": network_totals[1],
            },
            "temperature_c": _cpu_temperature(),
            "caddy": _caddy_status(),
        }

        self._previous_time = monotonic
        self._previous_disk = disk_totals
        self._previous_network = network_totals
        with self._lock:
            self._snapshot = snapshot
            self._history.append({
                "timestamp": snapshot["timestamp"],
                "cpu": cpu_percent,
                "memory": snapshot["memory"]["percent"],
                "network_receive": snapshot["network"]["receive_bps"],
                "network_send": snapshot["network"]["send_bps"],
            })
        return snapshot

    def read(self) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        with self._lock:
            return self._snapshot, list(self._history)

    def run_forever(self) -> None:
        time.sleep(self.interval)
        while True:
            started = time.monotonic()
            try:
                self.sample()
            except Exception:
                # Keep the last known sample, which the UI marks as stale.
                import logging

                logging.exception("Metric collection failed")
            time.sleep(max(0.2, self.interval - (time.monotonic() - started)))
