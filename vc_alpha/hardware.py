"""What machine is this, and what can it actually spare.

A partner will not choose a quantisation, so the product has to look at the machine
and decide. That starts with an honest picture of it.

Cross-platform via psutil, which covers Linux, macOS and Windows uniformly. Where a
detail is only reachable through a platform-specific call, a failure degrades to
"unknown" rather than a guess, because a wrong number here produces a confidently
wrong model recommendation.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import psutil

GB = 1024 ** 3

# What the operating system and its normal background work need, before the user's
# own applications. macOS reserves more than Linux for compression and caching;
# Windows sits between them.
#
# Calibrated against a real 8 GB machine rather than picked. The first values
# (4.0 / 3.0 / 1.5) combined with the working reserve below to conclude that an 8 GB
# laptop could run nothing at all — while a 1B model was demonstrably running on
# exactly that machine. A model that says "impossible" about something already
# working is wrong, however defensible its constants look.
OS_RESERVE_GB = {"Darwin": 2.5, "Windows": 2.0, "Linux": 1.0}

# Memory bandwidth by broad machine class, GB/s. Used only as a prior: the real
# figure comes from calibration, because these vary by a factor of ten across the
# machines a fund might actually own.
BANDWIDTH_PRIOR = {
    "apple_silicon": 100.0,   # unified memory, 68-400 depending on the chip
    "modern_desktop": 50.0,   # DDR5 dual channel
    "modern_laptop": 35.0,    # DDR5, lower clocks
    "older_laptop": 20.0,     # DDR3/DDR4 dual channel
}


@dataclass(slots=True)
class GPU:
    name: str
    vram_gb: float
    kind: str            # cuda | metal | rocm | none


@dataclass(slots=True)
class Machine:
    os: str
    arch: str
    cpu: str
    physical_cores: int
    logical_cores: int
    total_ram_gb: float
    available_ram_gb: float
    free_disk_gb: float
    gpu: GPU | None = None
    apple_silicon: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def machine_class(self) -> str:
        if self.apple_silicon:
            return "apple_silicon"
        if self.physical_cores >= 8 and self.total_ram_gb >= 32:
            return "modern_desktop"
        if self.physical_cores >= 6:
            return "modern_laptop"
        return "older_laptop"

    @property
    def bandwidth_prior(self) -> float:
        """Memory bandwidth in GB/s, before calibration corrects it.

        Apple Silicon spans roughly 100 GB/s on a base chip to 400 on an Ultra, and
        treating that as one number made a 64 GB workstation pick the same model as
        a 16 GB laptop: the speed constraint bound identically on both. Memory size
        is the best available proxy for the chip tier, since Apple only sells the
        larger memory configurations on the wider-bus parts.

        A prior, not a measurement. Calibration replaces it with what the machine
        actually achieves.
        """
        base = BANDWIDTH_PRIOR[self.machine_class]
        if self.apple_silicon:
            if self.total_ram_gb >= 64:
                return 400.0      # Max or Ultra
            if self.total_ram_gb >= 32:
                return 250.0      # Pro or Max
            return base           # base chip
        if self.gpu and self.gpu.kind == "cuda" and self.gpu.vram_gb >= 8:
            # A discrete GPU with enough memory to hold the model changes the
            # picture entirely: VRAM bandwidth is an order above system memory.
            return 600.0
        return base

    @property
    def os_reserve_gb(self) -> float:
        return OS_RESERVE_GB.get(self.os, 2.0)

    def usable_ram_gb(self, working_reserve_fraction: float = 0.15) -> float:
        """Memory a model may take without making the machine unpleasant to use.

        **This is the number most model-sizing tools get wrong**, including the ones
        built into local LLM apps. They ask whether a model fits in total RAM. The
        question that matters is whether it fits in what is *spare* while the owner
        keeps working — a partner's laptop is running a browser with forty tabs,
        Slack and a video call, and a model that technically fits but forces the
        machine to swap has made the product something they close.

        So: start from what is genuinely free right now, then keep a working reserve
        on top, because the user will open more things than they have open at the
        moment they press the button.
        """
        # A proportional reserve with a modest floor. An absolute floor of several
        # gigabytes is fine on a 32 GB workstation and nonsense on an 8 GB laptop,
        # where it consumes half the machine before anything is loaded.
        reserve = max(working_reserve_fraction * self.total_ram_gb, 1.5)
        spare = self.available_ram_gb - reserve
        # Never promise more than the machine could give even if idle.
        ceiling = self.total_ram_gb - self.os_reserve_gb - reserve
        return max(0.0, min(spare, ceiling))

    def summary(self) -> str:
        """One plain sentence, for a reader who does not know what VRAM is."""
        bits = [f"{self.total_ram_gb:.0f} GB memory",
                f"{self.physical_cores} cores"]
        if self.gpu and self.gpu.vram_gb:
            bits.append(f"{self.gpu.name} with {self.gpu.vram_gb:.0f} GB")
        elif self.apple_silicon:
            bits.append("Apple Silicon, shared memory")
        else:
            bits.append("no graphics acceleration")
        return ", ".join(bits)


def _apple_silicon() -> bool:
    return platform.system() == "Darwin" and platform.machine() == "arm64"


def _cpu_name() -> str:
    system = platform.system()
    try:
        if system == "Darwin":
            out = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"],
                                 capture_output=True, text=True, timeout=5)
            if out.returncode == 0 and out.stdout.strip():
                return out.stdout.strip()
        elif system == "Linux":
            for line in Path("/proc/cpuinfo").read_text().splitlines():
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return platform.processor() or platform.machine() or "unknown"


def _detect_gpu() -> GPU | None:
    """Discrete GPU and its memory, or None.

    Deliberately quiet about failure. No GPU is the common case on the machines this
    product targets, and it is a fact rather than a problem.
    """
    if shutil.which("nvidia-smi"):
        try:
            out = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,memory.total",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=8)
            if out.returncode == 0 and out.stdout.strip():
                name, mem = out.stdout.strip().splitlines()[0].split(",")
                return GPU(name.strip(), float(mem) / 1024.0, "cuda")
        except Exception:
            pass

    if _apple_silicon():
        # Unified memory: the GPU shares system RAM rather than having its own.
        return GPU("Apple Silicon GPU", 0.0, "metal")

    if shutil.which("rocm-smi"):
        return GPU("AMD GPU", 0.0, "rocm")
    return None


def profile() -> Machine:
    """Inspect this machine. Never raises; unknowns degrade rather than guess."""
    vm = psutil.virtual_memory()
    try:
        disk = psutil.disk_usage(str(Path.home())).free / GB
    except Exception:
        disk = 0.0

    machine = Machine(
        os=platform.system(),
        arch=platform.machine(),
        cpu=_cpu_name(),
        physical_cores=psutil.cpu_count(logical=False) or 1,
        logical_cores=psutil.cpu_count(logical=True) or 1,
        total_ram_gb=vm.total / GB,
        available_ram_gb=vm.available / GB,
        free_disk_gb=disk,
        gpu=_detect_gpu(),
        apple_silicon=_apple_silicon(),
    )

    if machine.gpu and machine.gpu.kind == "cuda":
        machine.notes.append("A CUDA GPU is present, so models will run far faster.")
    elif machine.apple_silicon:
        machine.notes.append(
            "Apple Silicon shares memory between CPU and GPU, so the whole machine's "
            "memory is available to a model.")
    else:
        machine.notes.append(
            "No graphics acceleration found, so models run on the processor. That "
            "works, but larger models will be slow.")

    if machine.usable_ram_gb() < 2:
        machine.notes.append(
            "Very little memory is free right now. Closing some applications would "
            "allow a better model.")
    return machine
