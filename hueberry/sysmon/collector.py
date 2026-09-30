# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""System metrics collector: prints one JSON line per interval for the overlay.

Run as ``python -m hueberry.sysmon.collector --config PATH``. Each line is
``{"text": ..., "class": orientation}`` where ``text`` holds one segment per
enabled metric (``CPU 12%``, ``GPU 3%``, ``VRAM 512/8176MiB``,
``RAM 5.1G/31.2G``, ``NVMe R:0% W:1%``) joined by two spaces (row) or a
newline (stacked).

This module must stay free of PyQt imports. Every sampler reads below an
injectable ``root`` (default ``/``) so tests can build fake proc/sys trees.
A missing or unreadable source renders ``n/a`` and never raises. The
delta-based metrics (CPU and disks) show ``0%`` on the very first sample,
when there is no previous sample to compare against, as long as their
source is readable.

SIGTERM, SIGINT and a closed output pipe (BrokenPipeError) end the process
with exit status 0.
"""

import argparse
import json
import logging
import os
import signal
import sys
import time
from pathlib import Path
from typing import Callable

from hueberry.sysmon import config as sysmon_config
from hueberry.sysmon.config import (
    GPU_CARD_AUTO,
    GPU_CARD_RE,
    ORIENTATION_STACKED,
    DiskSpec,
    SysmonConfig,
)

logger = logging.getLogger(__name__)

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s [pid=%(process)d] %(message)s"
EXIT_OK = 0
DEFAULT_ROOT = Path("/")
NA = "n/a"
ROW_SEPARATOR = "  "
STACKED_SEPARATOR = "\n"
LINE_END = "\n"

PROC_STAT = Path("proc/stat")
PROC_MEMINFO = Path("proc/meminfo")
PROC_DISKSTATS = Path("proc/diskstats")
DRM_CLASS_DIR = Path("sys/class/drm")
SYS_BLOCK_DIR = Path("sys/block")
DRM_DEVICE_DIR = "device"
GPU_BUSY_FILE = "gpu_busy_percent"
VRAM_USED_FILE = "mem_info_vram_used"
VRAM_TOTAL_FILE = "mem_info_vram_total"
GPU_CARD_GLOB = f"card*/{DRM_DEVICE_DIR}/{GPU_BUSY_FILE}"

CPU_LINE_PREFIX = "cpu "
CPU_TIME_FIELDS = 8  # user nice system idle iowait irq softirq steal (guest is in user)
CPU_IDLE_INDEX = 3
CPU_IOWAIT_INDEX = 4
MEMINFO_TOTAL = "MemTotal"
MEMINFO_AVAILABLE = "MemAvailable"
DISKSTATS_NAME_INDEX = 2
DISKSTATS_READ_SECTORS_INDEX = 5  # field 6 (1-based)
DISKSTATS_WRITE_SECTORS_INDEX = 9  # field 10 (1-based)

PERCENT = 100.0
SECTOR_BYTES = 512
BYTES_PER_MB = 1_000_000
BYTES_PER_MIB = 1024 * 1024
KIB_PER_GIB = 1024 * 1024
DEFAULT_DISK_MAX_MBPS = 500.0
EXCLUDED_DISK_PREFIXES = ("loop", "ram", "zram", "dm-", "sr")
NVME_PREFIX = "nvme"
NVME_LABEL = "NVMe"
CPU_LABEL = "CPU"
GPU_LABEL = "GPU"
VRAM_LABEL = "VRAM"
RAM_LABEL = "RAM"
STOP_SIGNALS = (signal.SIGTERM, signal.SIGINT)

Pair = tuple[int, int]
Writer = Callable[[str], None]


def _read_text(path: Path) -> str | None:
    """Contents of ``path``, or None when it is missing or unreadable."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        logger.debug("Cannot read metric source path=%s error=%s", path, exc)
        return None


def _read_int(path: Path) -> int | None:
    """Integer held in ``path``, or None when missing or not an integer."""
    text = _read_text(path)
    if text is None:
        return None
    try:
        return int(text.strip())
    except ValueError:
        logger.debug("Metric source is not an integer path=%s", path)
        return None


def _parse_cpu_line(line: str) -> Pair | None:
    """``(busy, total)`` jiffies from a /proc/stat ``cpu`` line."""
    try:
        values = [int(part) for part in line.split()[1:CPU_TIME_FIELDS + 1]]
    except ValueError:
        return None
    if len(values) <= CPU_IOWAIT_INDEX:
        return None
    total = sum(values)
    idle = values[CPU_IDLE_INDEX] + values[CPU_IOWAIT_INDEX]
    return total - idle, total


def read_cpu_times(root: Path) -> Pair | None:
    """``(busy, total)`` jiffies of the aggregate CPU line, idle = idle + iowait."""
    text = _read_text(root / PROC_STAT) or ""
    for line in text.splitlines():
        if line.startswith(CPU_LINE_PREFIX):
            return _parse_cpu_line(line)
    return None


def cpu_percent(previous: Pair | None, current: Pair | None) -> float | None:
    """Busy share between two samples; None if unreadable, 0 on the first sample."""
    if current is None:
        return None
    if previous is None:
        return 0.0
    total = current[1] - previous[1]
    if total <= 0:
        return 0.0
    busy = current[0] - previous[0]
    return min(PERCENT, max(0.0, busy * PERCENT / total))


def read_memory_kib(root: Path) -> Pair | None:
    """``(used, total)`` KiB where used = MemTotal - MemAvailable."""
    text = _read_text(root / PROC_MEMINFO)
    if text is None:
        return None
    fields: dict[str, int] = {}
    for line in text.splitlines():
        name, _sep, rest = line.partition(":")
        parts = rest.split()
        if parts and parts[0].isdigit():
            fields[name.strip()] = int(parts[0])
    total = fields.get(MEMINFO_TOTAL)
    available = fields.get(MEMINFO_AVAILABLE)
    if total is None or available is None:
        return None
    return total - available, total


def _drm_device(root: Path, card: str) -> Path:
    """The PCI device directory behind DRM ``card``."""
    return root / DRM_CLASS_DIR / card / DRM_DEVICE_DIR


def read_gpu_busy(root: Path, card: str | None) -> int | None:
    """GPU busy percent of ``card``, or None when unknown."""
    if card is None:
        return None
    return _read_int(_drm_device(root, card) / GPU_BUSY_FILE)


def read_vram_bytes(root: Path, card: str | None) -> Pair | None:
    """``(used, total)`` VRAM bytes of ``card``, or None when unknown."""
    if card is None:
        return None
    used = _read_int(_drm_device(root, card) / VRAM_USED_FILE)
    total = _read_int(_drm_device(root, card) / VRAM_TOTAL_FILE)
    if used is None or total is None or total <= 0:
        return None
    return used, total


def read_diskstats(root: Path) -> dict[str, Pair] | None:
    """Device name -> ``(sectors read, sectors written)``; None if unreadable."""
    text = _read_text(root / PROC_DISKSTATS)
    if text is None:
        return None
    stats: dict[str, Pair] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) <= DISKSTATS_WRITE_SECTORS_INDEX:
            continue
        read, written = parts[DISKSTATS_READ_SECTORS_INDEX], parts[DISKSTATS_WRITE_SECTORS_INDEX]
        if read.isdigit() and written.isdigit():
            stats[parts[DISKSTATS_NAME_INDEX]] = (int(read), int(written))
    return stats


def disk_percent(previous: int, current: int, elapsed_s: float, max_mbps: float) -> float:
    """Sector delta over ``elapsed_s`` as a percent of ``max_mbps``, capped at 100."""
    if elapsed_s <= 0 or max_mbps <= 0:
        return 0.0
    mbps = max(0, current - previous) * SECTOR_BYTES / BYTES_PER_MB / elapsed_s
    return min(PERCENT, mbps * PERCENT / max_mbps)


def detect_gpu_card(root: Path) -> str | None:
    """First DRM card (sorted) exposing ``gpu_busy_percent``, or None."""
    for path in sorted((root / DRM_CLASS_DIR).glob(GPU_CARD_GLOB)):
        card = path.parent.parent.name
        if GPU_CARD_RE.fullmatch(card):
            return card
    return None


def disk_label(device: str) -> str:
    """Display label: ``NVMe`` for nvme devices, else the upper-cased name."""
    return NVME_LABEL if device.startswith(NVME_PREFIX) else device.upper()


def detect_disks(root: Path) -> tuple[DiskSpec, ...]:
    """Block devices under /sys/block, minus loop/ram/zram/dm/optical ones."""
    try:
        names = sorted(entry.name for entry in (root / SYS_BLOCK_DIR).iterdir())
    except OSError as exc:
        logger.debug("Cannot list block devices error=%s", exc)
        return ()
    return tuple(DiskSpec(name, disk_label(name), DEFAULT_DISK_MAX_MBPS)
                 for name in names if not name.startswith(EXCLUDED_DISK_PREFIXES))


def format_percent(label: str, value: float | None) -> str:
    """``LABEL 12%`` or ``LABEL n/a``."""
    return f"{label} {NA}" if value is None else f"{label} {round(value)}%"


def format_vram(pair: Pair | None) -> str:
    """``VRAM used/totalMiB`` or ``VRAM n/a``."""
    if pair is None:
        return f"{VRAM_LABEL} {NA}"
    used, total = (round(value / BYTES_PER_MIB) for value in pair)
    return f"{VRAM_LABEL} {used}/{total}MiB"


def format_ram(pair: Pair | None) -> str:
    """``RAM used G/total G`` (one decimal) or ``RAM n/a``."""
    if pair is None:
        return f"{RAM_LABEL} {NA}"
    used, total = (value / KIB_PER_GIB for value in pair)
    return f"{RAM_LABEL} {used:.1f}G/{total:.1f}G"


def format_disk(label: str, read_pct: float, write_pct: float) -> str:
    """``LABEL R:0% W:1%``."""
    return f"{label} R:{round(read_pct)}% W:{round(write_pct)}%"


class Collector:
    """Samples the enabled metrics below ``root`` and renders the overlay text."""

    def __init__(self, config: SysmonConfig, root: Path = DEFAULT_ROOT) -> None:
        """Resolve the GPU card and disks once (auto-detecting when configured)."""
        self.config = config
        self.root = Path(root)
        self.gpu_card = self._resolve_gpu_card()
        self.disks = config.disks or detect_disks(self.root)
        self._cpu: Pair | None = None
        self._diskstats: dict[str, Pair] | None = None
        self._time: float | None = None
        logger.info("Sysmon collector ready gpu_card=%s disks=%s", self.gpu_card,
                    ",".join(disk.device for disk in self.disks))

    def _resolve_gpu_card(self) -> str | None:
        """The configured card, or the auto-detected one (None when none found)."""
        if self.config.gpu_card != GPU_CARD_AUTO:
            return self.config.gpu_card
        return detect_gpu_card(self.root)

    def segments(self, now: float) -> list[str]:
        """Take one sample at monotonic time ``now``; one segment per enabled metric."""
        elapsed = None if self._time is None else now - self._time
        self._time = now
        found = []
        if self.config.show_cpu:
            found.append(self._cpu_segment())
        if self.config.show_gpu:
            found.append(format_percent(GPU_LABEL, read_gpu_busy(self.root, self.gpu_card)))
        if self.config.show_vram:
            found.append(format_vram(read_vram_bytes(self.root, self.gpu_card)))
        if self.config.show_ram:
            found.append(format_ram(read_memory_kib(self.root)))
        if self.config.show_disks:
            found.extend(self._disk_segments(elapsed))
        return found

    def _cpu_segment(self) -> str:
        """CPU busy percent since the previous sample."""
        current = read_cpu_times(self.root)
        value = cpu_percent(self._cpu, current)
        self._cpu = current
        return format_percent(CPU_LABEL, value)

    def _disk_segments(self, elapsed: float | None) -> list[str]:
        """One segment per disk, from the diskstats delta since the previous sample."""
        current = read_diskstats(self.root)
        previous, self._diskstats = self._diskstats, current
        return [_disk_segment(disk, previous, current, elapsed) for disk in self.disks]

    def render(self, now: float) -> str:
        """Sample and join the segments for the configured orientation."""
        stacked = self.config.orientation == ORIENTATION_STACKED
        separator = STACKED_SEPARATOR if stacked else ROW_SEPARATOR
        return separator.join(self.segments(now))

    def payload(self, now: float) -> str:
        """One JSON object (without newline): ``{"text": ..., "class": ...}``."""
        return json.dumps({"text": self.render(now), "class": self.config.orientation})


def _disk_segment(disk: DiskSpec, previous: dict[str, Pair] | None,
                  current: dict[str, Pair] | None, elapsed: float | None) -> str:
    """Read/write load of ``disk``; n/a when absent, 0% without a previous sample."""
    if current is None or disk.device not in current:
        return f"{disk.label} {NA}"
    if previous is None or disk.device not in previous or elapsed is None:
        return format_disk(disk.label, 0.0, 0.0)
    (read_before, write_before), (read_after, write_after) = (
        previous[disk.device], current[disk.device])
    return format_disk(disk.label,
                       disk_percent(read_before, read_after, elapsed, disk.max_mbps),
                       disk_percent(write_before, write_after, elapsed, disk.max_mbps))


def write_stdout(line: str) -> None:
    """Write ``line`` to stdout and flush it immediately."""
    sys.stdout.write(line)
    sys.stdout.flush()


def run(collector: Collector, interval_s: float, *, clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep, writer: Writer = write_stdout,
        iterations: int | None = None) -> None:
    """Emit one JSON line per interval; ``iterations`` bounds the loop (None = forever)."""
    count = 0
    while iterations is None or count < iterations:
        writer(collector.payload(clock()) + LINE_END)
        sleep(interval_s)
        count += 1


class StopRequested(Exception):
    """Raised from a signal handler to end the sampling loop cleanly."""


def _raise_stop(signum: int, _frame: object) -> None:
    """Signal handler turning SIGTERM/SIGINT into StopRequested."""
    raise StopRequested(signal.Signals(signum).name)


def _install_signal_handlers() -> dict:
    """Install the stop handler; returns the previous handlers."""
    return {sig: signal.signal(sig, _raise_stop) for sig in STOP_SIGNALS}


def _restore_signal_handlers(previous: dict) -> None:
    """Put back the handlers returned by ``_install_signal_handlers``."""
    for sig, handler in previous.items():
        signal.signal(sig, handler)


def _silence_stdout() -> None:
    """Point stdout at /dev/null so the final flush at exit cannot fail again."""
    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        os.close(devnull)
    except (OSError, ValueError) as exc:
        logger.debug("Cannot redirect stdout to devnull error=%s", exc)


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Command-line options: ``--config PATH`` (default: the standard sysmon.json)."""
    parser = argparse.ArgumentParser(prog="python -m hueberry.sysmon.collector",
                                     description="Print system metrics as JSON lines.")
    parser.add_argument("--config", type=Path, default=None, help="path to sysmon.json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None, *, root: Path = DEFAULT_ROOT,
         clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep,
         writer: Writer | None = None, iterations: int | None = None) -> int:
    """Load the config and emit metrics until stopped; always returns 0."""
    config = sysmon_config.load(parse_args(argv).config)
    collector = Collector(config, root)
    previous = _install_signal_handlers()
    try:
        run(collector, config.interval_s, clock=clock, sleep=sleep,
            writer=writer or write_stdout, iterations=iterations)
    except StopRequested as exc:
        logger.info("Stopping sysmon collector signal=%s", exc)
    except BrokenPipeError:
        logger.info("Stopping sysmon collector reason=broken-pipe")
        if writer is None:
            _silence_stdout()
    finally:
        _restore_signal_handlers(previous)
    return EXIT_OK


if __name__ == "__main__":
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format=LOG_FORMAT)
    sys.exit(main())
