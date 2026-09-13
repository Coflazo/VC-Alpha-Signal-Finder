"""Choose the best local model this machine can run without ruining it.

Two constraints, both hard, and a quality objective between them.

## Memory

    weights(P, q) = P × bytes_per_param(q)          Q4_K_M ≈ 0.5 GB per 1B params
    kv_cache      = 2 × layers × kv_heads × head_dim × context × dtype_bytes
    required      = (weights + kv_cache) × 1.15     activations and framework

The 15% covers activations and runtime overhead, which is the range the literature
reports. KV cache matters more than people expect: an 8B model at 32K context needs
roughly 4.5 GB for cache alone, often more than the weights.

## Speed

Local inference is **memory-bandwidth bound**, not compute bound. Each generated
token requires reading the whole model from memory, so

    tokens/sec ≈ η × bandwidth / model_bytes

η is the fraction of theoretical bandwidth actually achieved, and it varies by an
order of magnitude across machines. **It is measured rather than assumed**: the
installer runs one short generation with a model already present, measures real
tokens per second, and solves for η. Everything after that is extrapolation from a
measurement on the machine in front of the user, which is the only honest basis for
telling them what will be fast.

## Selection

    maximise   quality(P, q)
    subject to required(P, q) ≤ usable_ram
               predicted_tok_per_sec ≥ minimum

Quality rises with parameters but with diminishing returns, so log-scale, less a
penalty for aggressive quantisation. Deliberately simple and inspectable: nobody
should have to trust a black box about which model to download.

## Complexity

O(K) over a fixed catalogue of about twenty entries, evaluated once at setup, plus
one short benchmark. Nothing here scales with corpus size and no pipeline stage
becomes slower.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from vc_alpha.hardware import Machine

# Bytes per parameter by quantisation. Q4_K_M is the consumer default and the one
# LM Studio and Ollama both lean on: roughly a quarter the size of FP16 for a small
# and well-characterised quality cost.
BYTES_PER_PARAM = {"f16": 2.0, "q8_0": 1.0, "q5_k_m": 0.70, "q4_k_m": 0.55,
                   "q4_0": 0.50, "iq4_xs": 0.47, "q3_k_m": 0.42}

# Quality lost to quantisation, in the same units as the log-parameter term.
QUANT_PENALTY = {"f16": 0.0, "q8_0": 0.02, "q5_k_m": 0.06, "q4_k_m": 0.12,
                 "q4_0": 0.16, "iq4_xs": 0.18, "q3_k_m": 0.35}

OVERHEAD = 1.15
MIN_TOKENS_PER_SEC = 8.0     # below this the product feels broken rather than slow


@dataclass(frozen=True, slots=True)
class ModelSpec:
    """A model as Ollama names it, with the shape needed to size its KV cache."""

    name: str                 # ollama tag
    params_b: float
    layers: int
    kv_heads: int
    head_dim: int
    quant: str = "q4_k_m"
    role: str = "triage"      # triage | embedding
    note: str = ""

    def weights_gb(self) -> float:
        return self.params_b * BYTES_PER_PARAM[self.quant]

    def kv_cache_gb(self, context: int, kv_bytes: float = 2.0) -> float:
        """2 × layers × kv_heads × head_dim × context × bytes, in gigabytes."""
        return (2 * self.layers * self.kv_heads * self.head_dim
                * context * kv_bytes) / 1024 ** 3

    def required_gb(self, context: int = 8192) -> float:
        return (self.weights_gb() + self.kv_cache_gb(context)) * OVERHEAD

    def quality(self) -> float:
        """Diminishing returns in parameters, less the quantisation cost."""
        return math.log10(max(self.params_b, 0.1)) - QUANT_PENALTY[self.quant]


# Deliberately short. Every entry is something Ollama can pull by name, and the
# spread covers a 2017 laptop through a workstation.
CATALOGUE = [
    ModelSpec("qwen3-embedding:0.6b", 0.6, 28, 8, 128, "q4_k_m", "embedding",
              "Embeddings. Small enough for any machine."),
    ModelSpec("nomic-embed-text", 0.14, 12, 12, 64, "f16", "embedding",
              "Lighter embeddings for very constrained machines."),

    ModelSpec("llama3.2:1b", 1.2, 16, 8, 64, "q4_k_m", "triage",
              "Fits almost anywhere. Judgement is limited."),
    ModelSpec("qwen2.5:3b-instruct-q4_K_M", 3.1, 36, 2, 128, "q4_k_m", "triage",
              "A sensible floor for real screening work."),
    ModelSpec("llama3.1:8b", 8.0, 32, 8, 128, "q4_k_m", "triage",
              "Good general judgement where memory allows."),
    ModelSpec("qwen2.5:14b", 14.8, 48, 8, 128, "q4_k_m", "triage",
              "Noticeably better reasoning on borderline candidates."),
    ModelSpec("gpt-oss:20b", 20.0, 24, 8, 64, "q4_k_m", "triage",
              "Mixture-of-experts: large-model judgement at closer to small-model speed."),
    ModelSpec("qwen2.5:32b", 32.5, 64, 8, 128, "q4_k_m", "triage",
              "For workstations with memory to spare."),
]


@dataclass(slots=True)
class Recommendation:
    model: ModelSpec | None
    required_gb: float
    usable_gb: float
    predicted_tok_per_sec: float
    efficiency: float
    reason: str
    rejected: list[tuple[str, str]]     # (model, why not)

    @property
    def ok(self) -> bool:
        return self.model is not None


def predict_speed(spec: ModelSpec, machine: Machine, efficiency: float) -> float:
    """tok/s ≈ η × bandwidth / model_bytes. Reading the weights is the bottleneck."""
    size_gb = spec.weights_gb()
    if size_gb <= 0:
        return 0.0
    return efficiency * machine.bandwidth_prior / size_gb


def measure_efficiency(observed_tok_per_sec: float, spec: ModelSpec,
                       machine: Machine) -> float:
    """Solve for η from one real generation.

    The whole point of calibrating. A published bandwidth figure describes the
    memory bus, not what an old dual-core actually achieves through it, and the gap
    between them is often a factor of ten.
    """
    if observed_tok_per_sec <= 0:
        return 0.10
    eta = observed_tok_per_sec * spec.weights_gb() / machine.bandwidth_prior
    return min(max(eta, 0.01), 1.0)


def recommend(machine: Machine, efficiency: float = 0.15, context: int = 8192,
              role: str = "triage",
              min_tok_per_sec: float = MIN_TOKENS_PER_SEC) -> Recommendation:
    """Best model meeting both constraints, with reasons for everything rejected.

    `efficiency` defaults to a conservative prior; pass the measured value from
    `measure_efficiency` once a calibration run has happened.
    """
    usable = machine.usable_ram_gb()
    candidates = [m for m in CATALOGUE if m.role == role]
    rejected: list[tuple[str, str]] = []
    best: tuple[float, ModelSpec, float, float] | None = None

    for spec in candidates:
        need = spec.required_gb(context)
        speed = predict_speed(spec, machine, efficiency)

        if need > usable:
            rejected.append((spec.name,
                             f"needs {need:.1f} GB, only {usable:.1f} GB is free"))
            continue
        if speed < min_tok_per_sec:
            rejected.append((spec.name,
                             f"would run at about {speed:.0f} tokens/sec, too slow "
                             f"to be useful"))
            continue
        score = spec.quality()
        if best is None or score > best[0]:
            best = (score, spec, need, speed)

    if best is None:
        return Recommendation(
            None, 0.0, usable, 0.0, efficiency,
            reason=("No local model fits comfortably right now. The product will use "
                    "the free hosted providers instead, which are faster anyway. "
                    "Closing some applications would free memory if you want a local "
                    "model for private sources."),
            rejected=rejected)

    _, spec, need, speed = best
    return Recommendation(
        spec, need, usable, speed, efficiency,
        reason=(f"{spec.name} needs about {need:.1f} GB and {usable:.1f} GB is free, "
                f"so it should run at roughly {speed:.0f} tokens per second. "
                f"{spec.note}"),
        rejected=rejected)
