"""Set up local inference from nothing, in one action.

A partner should not have to know what Ollama is, which quantisation to pick, or how
to read a memory figure. They press a button; this profiles the machine, measures
what it actually achieves, chooses a model that will not make the laptop unpleasant,
installs what is missing and verifies the result works.

Every step reports in plain language and every failure degrades honestly. Refusing
to install and falling back to the free hosted providers is a perfectly good outcome
and is reported as such, not as an error.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from collections.abc import Iterator
from dataclasses import dataclass, field

import httpx

from vc_alpha.hardware import Machine, profile
from vc_alpha.modelpick import (
    CATALOGUE, ModelSpec, Recommendation, measure_efficiency, recommend,
)

OLLAMA = "http://localhost:11434"

# Small enough to pull quickly on any connection, and present on most machines that
# have used Ollama at all. Used only to measure how fast this machine really is.
CALIBRATION_MODEL = "llama3.2:1b"

INSTALL_HINT = {
    "Darwin": "Download from ollama.com/download, or run: brew install ollama",
    "Linux": "Run: curl -fsSL https://ollama.com/install.sh | sh",
    "Windows": "Download the installer from ollama.com/download",
}


@dataclass(slots=True)
class Step:
    """One reported step. `detail` is written for a non-technical reader."""

    name: str
    ok: bool
    detail: str
    data: dict = field(default_factory=dict)


def ollama_running(timeout: float = 3.0) -> bool:
    try:
        return httpx.get(f"{OLLAMA}/api/tags", timeout=timeout).status_code == 200
    except httpx.HTTPError:
        return False


def ollama_installed() -> bool:
    return shutil.which("ollama") is not None


def installed_models() -> list[str]:
    try:
        r = httpx.get(f"{OLLAMA}/api/tags", timeout=5)
        r.raise_for_status()
        return [m["name"] for m in r.json().get("models", [])]
    except Exception:
        return []


def start_ollama() -> bool:
    """Start the background service if it is installed but not running."""
    if not ollama_installed():
        return False
    try:
        subprocess.Popen(["ollama", "serve"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        return False
    for _ in range(20):
        if ollama_running(timeout=1.0):
            return True
        time.sleep(0.5)
    return False


def pull(model: str, timeout: float = 1800.0) -> Iterator[str]:
    """Download a model, yielding human-readable progress lines."""
    try:
        with httpx.stream("POST", f"{OLLAMA}/api/pull", json={"name": model},
                          timeout=timeout) as r:
            r.raise_for_status()
            last = ""
            for line in r.iter_lines():
                if not line:
                    continue
                import json as _json
                try:
                    status = _json.loads(line).get("status", "")
                except ValueError:
                    continue
                if status and status != last:
                    last = status
                    yield status
    except Exception as e:
        yield f"download failed: {e}"


def calibrate(model: str = CALIBRATION_MODEL) -> float:
    """Measure real tokens per second with one short generation.

    The reason the recommendation can be trusted. A published bandwidth figure
    describes the memory bus; this measures what the machine in front of the user
    actually achieves through it, and the two differ by up to an order of magnitude.
    """
    try:
        start = time.time()
        r = httpx.post(f"{OLLAMA}/api/generate",
                       json={"model": model, "prompt": "Count to twenty.",
                             "stream": False, "options": {"num_predict": 60}},
                       timeout=600)
        r.raise_for_status()
        body = r.json()
        elapsed = time.time() - start
        # Ollama reports its own counts; fall back to wall clock if absent.
        tokens = body.get("eval_count") or 60
        seconds = (body.get("eval_duration") or 0) / 1e9 or elapsed
        return tokens / seconds if seconds > 0 else 0.0
    except Exception:
        return 0.0


def verify(model: str) -> bool:
    """Prove the chosen model actually answers before declaring success."""
    try:
        r = httpx.post(f"{OLLAMA}/api/generate",
                       json={"model": model, "prompt": "Reply with the word: ready",
                             "stream": False, "options": {"num_predict": 10}},
                       timeout=600)
        return r.status_code == 200 and bool(r.json().get("response"))
    except Exception:
        return False


def auto_setup(allow_download: bool = True) -> Iterator[Step]:
    """Profile, calibrate, choose, install, verify. Yields steps as they complete."""
    machine: Machine = profile()
    yield Step("inspect", True,
               f"Found {machine.summary()}. "
               f"About {machine.usable_ram_gb():.1f} GB is free for a model right now.",
               {"os": machine.os, "total_ram_gb": round(machine.total_ram_gb, 1),
                "usable_gb": round(machine.usable_ram_gb(), 2)})

    if not ollama_running():
        if ollama_installed():
            ok = start_ollama()
            yield Step("start", ok,
                       "Started the local model service."
                       if ok else "Could not start the local model service.")
        else:
            yield Step("install", False,
                       "Local models need Ollama, which is not installed. "
                       + INSTALL_HINT.get(machine.os, "See ollama.com/download") +
                       ". The product works without it using the free hosted "
                       "providers, which are faster anyway.")
            return

    if not ollama_running():
        yield Step("fallback", True,
                   "Local models are unavailable, so the free hosted providers will "
                   "be used. Nothing else is affected.")
        return

    # Calibrate against something already present, pulling the small one if needed.
    have = installed_models()
    cal_model = next((m for m in have if m.startswith("llama3.2:1b")), None)
    if not cal_model and allow_download:
        yield Step("calibrate-download", True,
                   "Downloading a small model to measure this machine's speed.")
        for status in pull(CALIBRATION_MODEL):
            if "failed" in status:
                yield Step("calibrate-download", False, status)
                break
        cal_model = CALIBRATION_MODEL if verify(CALIBRATION_MODEL) else None

    if cal_model:
        observed = calibrate(cal_model)
        spec = next(s for s in CATALOGUE if s.name.startswith("llama3.2:1b"))
        efficiency = measure_efficiency(observed, spec, machine)
        yield Step("calibrate", True,
                   f"Measured about {observed:.0f} tokens per second on a small "
                   f"model, so this machine runs at roughly "
                   f"{efficiency * 100:.0f}% of its theoretical memory speed.",
                   {"observed_tok_per_sec": round(observed, 1),
                    "efficiency": round(efficiency, 3)})
    else:
        efficiency = 0.15
        yield Step("calibrate", False,
                   "Could not measure this machine's speed, so a conservative "
                   "estimate is used instead.")

    rec: Recommendation = recommend(machine, efficiency=efficiency)
    yield Step("choose", rec.ok, rec.reason,
               {"model": rec.model.name if rec.ok else None,
                "required_gb": round(rec.required_gb, 2),
                "predicted_tok_per_sec": round(rec.predicted_tok_per_sec, 1),
                "rejected": [{"model": n, "why": w} for n, w in rec.rejected]})

    if not rec.ok:
        return

    if rec.model.name not in have:
        if not allow_download:
            yield Step("download", False,
                       f"{rec.model.name} is not installed and downloading is off.")
            return
        yield Step("download", True, f"Downloading {rec.model.name}.")
        for status in pull(rec.model.name):
            if "failed" in status:
                yield Step("download", False, status)
                return

    ok = verify(rec.model.name)
    yield Step("verify", ok,
               f"{rec.model.name} is installed and answering. Private sources like "
               f"WhatsApp will now be processed on this machine only."
               if ok else
               f"{rec.model.name} downloaded but did not answer. The hosted "
               f"providers will be used instead.",
               {"model": rec.model.name})
