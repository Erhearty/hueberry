# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for the sysmon metrics collector, run against fake proc/sys trees."""

import json
import signal

import pytest

from hueberry.sysmon import collector
from hueberry.sysmon.config import ORIENTATION_STACKED, DiskSpec, SysmonConfig

MIB = 1024 * 1024
VRAM_USED = 512 * MIB
VRAM_TOTAL = 8176 * MIB
MEM_TOTAL_KIB = 32714752  # 31.2 GiB
MEM_USED_KIB = 5347738  # 5.1 GiB
STAT_FIRST = "cpu  100 0 50 800 50 0 0 0 0 0\ncpu0 100 0 50 800 50 0 0 0 0 0\n"
STAT_SECOND = "cpu  110 0 52 880 58 0 0 0 0 0\ncpu0 110 0 52 880 58 0 0 0 0 0\n"
WRITE_DELTA_SECTORS = 1953  # 999936 bytes in one second -> 1% of 100 MB/s
NVME = DiskSpec("nvme0n1", "NVMe", 100.0)
FIRST_TIME = 10.0
SECOND_TIME = 11.0
INTERVAL = 2.0
FIRST_TEXT = "CPU 0%  GPU 3%  VRAM 512/8176MiB  RAM 5.1G/31.2G  NVMe R:0% W:0%"
SECOND_TEXT = "CPU 12%  GPU 3%  VRAM 512/8176MiB  RAM 5.1G/31.2G  NVMe R:0% W:1%"
BLOCK_DEVICES = ("dm-0", "loop0", "nvme0n1", "ram0", "sda", "sr0", "zram0")


def _write(root, relative, text):
    """Create ``root/relative`` holding ``text``."""
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _diskstats(write_sectors):
    """A diskstats body with a partition line that must not be matched."""
    return (f" 259 0 nvme0n1 100 0 4000 0 50 0 {write_sectors} 0 0 0 0\n"
            " 259 1 nvme0n1p1 100 0 999999 0 50 0 999999 0 0 0 0\n"
            "   8 0 sda 10 0 100 0 5 0 200 0 0 0 0\n")


@pytest.fixture
def tree(tmp_path):
    """A fake root holding the first sample of every metric."""
    _write(tmp_path, "proc/stat", STAT_FIRST)
    available = MEM_TOTAL_KIB - MEM_USED_KIB
    _write(tmp_path, "proc/meminfo", f"MemTotal: {MEM_TOTAL_KIB} kB\nMemFree: 1 kB\n"
                                     f"MemAvailable: {available} kB\n")
    _write(tmp_path, "proc/diskstats", _diskstats(2000))
    (tmp_path / "sys/class/drm/card0/device").mkdir(parents=True)
    (tmp_path / "sys/class/drm/card0-DP-1").mkdir(parents=True)
    device = "sys/class/drm/card1/device/"
    _write(tmp_path, device + "gpu_busy_percent", "3\n")
    _write(tmp_path, device + "mem_info_vram_used", f"{VRAM_USED}\n")
    _write(tmp_path, device + "mem_info_vram_total", f"{VRAM_TOTAL}\n")
    for name in BLOCK_DEVICES:
        (tmp_path / "sys/block" / name).mkdir(parents=True)
    return tmp_path


def _advance(root):
    """Write the second sample of the delta-based metrics."""
    _write(root, "proc/stat", STAT_SECOND)
    _write(root, "proc/diskstats", _diskstats(2000 + WRITE_DELTA_SECTORS))


def test_two_samples_render_every_metric(tree):
    """First sample shows 0% for delta metrics; the second shows the deltas."""
    sampler = collector.Collector(SysmonConfig(disks=(NVME,)), tree)
    assert sampler.render(FIRST_TIME) == FIRST_TEXT
    _advance(tree)
    assert sampler.render(SECOND_TIME) == SECOND_TEXT


def test_disk_percent_scales_and_caps():
    """Sector deltas become MB/s relative to max_mbps, capped at 100."""
    assert collector.disk_percent(0, 1000, 0.512, 10.0) == pytest.approx(10.0)
    assert collector.disk_percent(0, 10**9, 1.0, 100.0) == 100.0
    assert collector.disk_percent(50, 10, 1.0, 100.0) == 0.0
    assert collector.disk_percent(0, 1000, 0.0, 100.0) == 0.0


def test_cpu_percent_edge_cases():
    """Unknown current is None, no previous is 0, a zero total delta is 0."""
    assert collector.cpu_percent((1, 2), None) is None
    assert collector.cpu_percent(None, (1, 2)) == 0.0
    assert collector.cpu_percent((1, 2), (1, 2)) == 0.0


def test_auto_detects_gpu_card_and_disks(tree):
    """The first card with gpu_busy_percent wins; virtual block devices are skipped."""
    assert collector.detect_gpu_card(tree) == "card1"
    disks = collector.detect_disks(tree)
    assert disks == (DiskSpec("nvme0n1", "NVMe", collector.DEFAULT_DISK_MAX_MBPS),
                     DiskSpec("sda", "SDA", collector.DEFAULT_DISK_MAX_MBPS))
    sampler = collector.Collector(SysmonConfig(), tree)
    assert sampler.gpu_card == "card1"
    assert sampler.disks == disks


def test_disk_labels():
    """nvme devices are labelled NVMe, others upper-cased."""
    assert collector.disk_label("nvme1n1") == "NVMe"
    assert collector.disk_label("vda") == "VDA"


def test_explicit_gpu_card_without_sources_is_na(tree):
    """A configured card lacking the sysfs files shows n/a for GPU and VRAM."""
    config = SysmonConfig(gpu_card="card0", show_cpu=False, show_ram=False, show_disks=False)
    assert collector.Collector(config, tree).render(FIRST_TIME) == "GPU n/a  VRAM n/a"


def test_missing_sources_render_na(tmp_path):
    """An empty root yields n/a everywhere and detects nothing."""
    assert collector.detect_gpu_card(tmp_path) is None
    assert collector.detect_disks(tmp_path) == ()
    sampler = collector.Collector(SysmonConfig(disks=(NVME,)), tmp_path)
    expected = "CPU n/a  GPU n/a  VRAM n/a  RAM n/a  NVMe n/a"
    assert sampler.render(FIRST_TIME) == expected
    assert sampler.render(SECOND_TIME) == expected


def test_malformed_sources_render_na(tree):
    """Garbage content and a missing device degrade to n/a without raising."""
    _write(tree, "proc/stat", "cpu  x y z\n")
    _write(tree, "proc/meminfo", "MemTotal: 10 kB\n")
    _write(tree, "sys/class/drm/card1/device/gpu_busy_percent", "busy\n")
    _write(tree, "sys/class/drm/card1/device/mem_info_vram_total", "0\n")
    config = SysmonConfig(disks=(DiskSpec("sdz", "SDZ", 100.0),))
    expected = "CPU n/a  GPU n/a  VRAM n/a  RAM n/a  SDZ n/a"
    assert collector.Collector(config, tree).render(FIRST_TIME) == expected


def test_stacked_orientation_joins_with_newlines(tree):
    """Stacked text uses newlines and the payload class names the orientation."""
    config = SysmonConfig(disks=(NVME,), orientation=ORIENTATION_STACKED)
    payload = json.loads(collector.Collector(config, tree).payload(FIRST_TIME))
    assert payload == {"text": FIRST_TEXT.replace("  ", "\n"), "class": ORIENTATION_STACKED}


def test_disabled_metrics_are_omitted(tree):
    """Only enabled metrics produce segments."""
    config = SysmonConfig(show_cpu=False, show_vram=False, show_disks=False)
    assert collector.Collector(config, tree).render(FIRST_TIME) == "GPU 3%  RAM 5.1G/31.2G"


def test_run_one_iteration(tree):
    """One loop pass writes one newline-terminated JSON line then sleeps."""
    lines, sleeps = [], []
    sampler = collector.Collector(SysmonConfig(disks=(NVME,)), tree)
    collector.run(sampler, INTERVAL, clock=lambda: FIRST_TIME, sleep=sleeps.append,
                  writer=lines.append, iterations=1)
    assert len(lines) == 1 and lines[0].endswith("\n")
    assert json.loads(lines[0]) == {"text": FIRST_TEXT, "class": "row"}
    assert sleeps == [INTERVAL]


def test_main_with_bad_config_uses_defaults(tree):
    """A corrupt config file falls back to defaults and the loop still runs."""
    config_path = tree / "sysmon.json"
    config_path.write_text("{not json")
    lines = []
    code = collector.main(["--config", str(config_path)], root=tree, clock=lambda: FIRST_TIME,
                          sleep=lambda _s: None, writer=lines.append, iterations=1)
    assert code == 0
    text = json.loads(lines[0])["text"]
    assert text == "CPU 0%  GPU 3%  VRAM 512/8176MiB  RAM 5.1G/31.2G  NVMe R:0% W:0%  SDA R:0% W:0%"


def test_broken_pipe_exits_zero(tree):
    """A closed output pipe ends main with status 0."""
    def broken(_line):
        raise BrokenPipeError
    code = collector.main(["--config", str(tree / "missing.json")], root=tree,
                          clock=lambda: FIRST_TIME, sleep=lambda _s: None, writer=broken)
    assert code == 0


@pytest.mark.parametrize("signum", [signal.SIGTERM, signal.SIGINT])
def test_stop_signal_exits_zero_and_restores_handlers(tree, signum):
    """SIGTERM/SIGINT during the loop end main with status 0."""
    before = signal.getsignal(signum)
    lines = []
    code = collector.main(["--config", str(tree / "missing.json")], root=tree,
                          clock=lambda: FIRST_TIME, sleep=lambda _s: signal.raise_signal(signum),
                          writer=lines.append)
    assert code == 0
    assert len(lines) == 1
    assert signal.getsignal(signum) is before
