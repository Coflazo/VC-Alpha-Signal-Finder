"""Hardware profiling and model selection.

The failure mode that matters is a confidently wrong recommendation: telling a
partner to download 13 GB onto a laptop that cannot run it, or telling them nothing
works when something does. Both were real bugs during development and both are
pinned below.
"""

import pytest

from vc_alpha.hardware import BANDWIDTH_PRIOR, GPU, Machine, profile
from vc_alpha.modelpick import (
    CATALOGUE, ModelSpec, measure_efficiency, predict_speed, recommend,
)


def mac(total, free, silicon=True):
    return Machine(os="Darwin", arch="arm64", cpu="M", physical_cores=8,
                   logical_cores=8, total_ram_gb=total, available_ram_gb=free,
                   free_disk_gb=200, apple_silicon=silicon)


# --- profiling ---------------------------------------------------------------


def test_profiling_this_machine_returns_sane_values():
    m = profile()
    assert m.total_ram_gb > 0.5
    assert 0 <= m.available_ram_gb <= m.total_ram_gb
    assert m.physical_cores >= 1
    assert m.os in ("Darwin", "Linux", "Windows")


def test_the_summary_avoids_jargon():
    """A partner reads this, not an engineer."""
    s = profile().summary()
    assert "GB" in s
    assert "VRAM" not in s


def test_no_gpu_is_reported_as_a_fact_not_an_error():
    m = profile()
    assert m.gpu is None or m.gpu.kind in ("cuda", "metal", "rocm")
    assert m.notes, "the profile should always explain itself"


# --- the usable-memory question ----------------------------------------------


def test_usable_memory_is_less_than_free_memory():
    """The number most sizing tools get wrong. A model that technically fits but
    forces the machine to swap has made the product something the user closes."""
    m = mac(16, 10)
    assert m.usable_ram_gb() < m.available_ram_gb


def test_an_eight_gigabyte_laptop_can_still_run_something():
    """The first constants concluded an 8 GB machine could run nothing, while a 1B
    model was demonstrably running on exactly such a machine."""
    assert mac(8, 6).usable_ram_gb() >= 1.0


def test_usable_memory_grows_with_the_machine():
    sizes = [mac(t, t * 0.6).usable_ram_gb() for t in (8, 16, 32, 64)]
    assert sizes == sorted(sizes)


def test_a_busy_machine_offers_less_than_an_idle_one():
    assert mac(16, 2).usable_ram_gb() < mac(16, 12).usable_ram_gb()


def test_usable_memory_is_never_negative():
    assert mac(8, 0.2).usable_ram_gb() >= 0.0


# --- bandwidth ---------------------------------------------------------------


def test_bigger_apple_machines_are_assumed_faster():
    """Treating all Apple Silicon as one bandwidth made a 64 GB workstation pick the
    same model as a 16 GB laptop."""
    assert mac(64, 40).bandwidth_prior > mac(16, 10).bandwidth_prior


def test_a_large_discrete_gpu_raises_the_prior():
    cpu_only = Machine(os="Linux", arch="x86_64", cpu="i7", physical_cores=8,
                       logical_cores=16, total_ram_gb=32, available_ram_gb=20,
                       free_disk_gb=100)
    with_gpu = Machine(os="Linux", arch="x86_64", cpu="i7", physical_cores=8,
                       logical_cores=16, total_ram_gb=32, available_ram_gb=20,
                       free_disk_gb=100, gpu=GPU("RTX 4090", 24, "cuda"))
    assert with_gpu.bandwidth_prior > cpu_only.bandwidth_prior


# --- the memory arithmetic ---------------------------------------------------


def test_quantisation_shrinks_the_weights():
    big = ModelSpec("x", 8.0, 32, 8, 128, "f16")
    small = ModelSpec("x", 8.0, 32, 8, 128, "q4_k_m")
    assert small.weights_gb() < big.weights_gb() / 3


def test_kv_cache_grows_with_context_and_is_not_negligible():
    spec = next(s for s in CATALOGUE if s.name == "llama3.1:8b")
    assert spec.kv_cache_gb(32768) > spec.kv_cache_gb(4096)
    assert spec.kv_cache_gb(32768) > 0.5, "KV cache is often larger than expected"


def test_required_memory_exceeds_raw_weights():
    """Activations and framework overhead are real and get forgotten."""
    spec = next(s for s in CATALOGUE if s.name == "llama3.1:8b")
    assert spec.required_gb(8192) > spec.weights_gb()


# --- speed -------------------------------------------------------------------


def test_speed_falls_as_the_model_grows():
    """Inference is memory-bandwidth bound: every token reads the whole model."""
    m = mac(64, 40)
    small = next(s for s in CATALOGUE if s.name == "llama3.2:1b")
    large = next(s for s in CATALOGUE if s.name == "qwen2.5:32b")
    assert predict_speed(small, m, 0.5) > predict_speed(large, m, 0.5)


def test_efficiency_is_solved_from_a_real_measurement():
    """A published bandwidth figure describes the bus, not what an old dual-core
    achieves through it, and the gap is often a factor of ten."""
    m = mac(8, 6, silicon=False)
    spec = next(s for s in CATALOGUE if s.name == "llama3.2:1b")
    slow = measure_efficiency(2.0, spec, m)
    fast = measure_efficiency(40.0, spec, m)
    assert 0 < slow < fast <= 1.0


def test_a_nonsense_measurement_does_not_produce_a_nonsense_efficiency():
    m = mac(16, 10)
    spec = CATALOGUE[0]
    assert 0 < measure_efficiency(0, spec, m) <= 1.0


# --- selection ---------------------------------------------------------------


def test_a_bigger_machine_earns_a_bigger_model():
    small = recommend(mac(8, 6), efficiency=0.5)
    large = recommend(mac(64, 40), efficiency=0.5)
    assert large.model.params_b > small.model.params_b


def test_an_oversized_model_is_rejected_with_a_readable_reason():
    r = recommend(mac(8, 6), efficiency=0.5)
    rejected = dict(r.rejected)
    assert any("GB is free" in why for why in rejected.values())
    assert all(not why.startswith("Error") for why in rejected.values())


def test_a_machine_that_cannot_run_anything_says_so_helpfully():
    """Rather than recommending something that would make the laptop unusable."""
    r = recommend(mac(4, 0.5), efficiency=0.05)
    assert not r.ok
    assert "hosted" in r.reason.lower()


def test_the_reason_is_written_for_a_non_technical_reader():
    r = recommend(mac(32, 24), efficiency=0.5)
    assert "GB" in r.reason and "tokens per second" in r.reason
    assert "quantisation" not in r.reason.lower()


def test_too_slow_is_rejected_even_when_it_fits():
    """Fitting in memory is not the same as being usable."""
    r = recommend(mac(64, 48), efficiency=0.01)
    assert not r.ok or r.predicted_tok_per_sec >= 8


def test_embeddings_and_triage_are_chosen_separately():
    e = recommend(mac(16, 10), efficiency=0.5, role="embedding")
    t = recommend(mac(16, 10), efficiency=0.5, role="triage")
    assert e.model.role == "embedding" and t.model.role == "triage"


def test_every_catalogue_entry_explains_itself():
    assert all(s.note for s in CATALOGUE), "a user should know why a model was picked"
