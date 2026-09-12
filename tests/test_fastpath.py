"""The C++ extension, its pure-Python twin, and near-duplicate detection.

The governing rule for a rewrite: the two implementations must agree on identical
inputs. The Python twin is the specification, and "the C++ looked right" is not a
correctness argument for numeric code.
"""

import math
import random
import struct

import pytest

from vc_alpha import fastpath as fp
from vc_alpha.dedup import find_duplicates


def rand_vec(d, rng):
    return [rng.random() for _ in range(d)]


# --- the two implementations must agree --------------------------------------


@pytest.mark.skipif(not fp.HAVE_FAST, reason="extension not built")
def test_cosine_matrix_matches_the_python_twin():
    rng = random.Random(1)
    mat = [rand_vec(64, rng) for _ in range(120)]
    q = rand_vec(64, rng)
    fast, slow = fp.cosine_matrix(mat, q), fp._cosine_matrix_py(mat, q)
    assert max(abs(a - b) for a, b in zip(fast, slow)) < 1e-9


@pytest.mark.skipif(not fp.HAVE_FAST, reason="extension not built")
def test_cosine_blobs_matches_the_python_twin():
    """The interface that matters: vectors stay in the packed form sqlite returns."""
    rng = random.Random(2)
    vecs = [rand_vec(128, rng) for _ in range(60)]
    blobs = [struct.pack(f"{len(v)}f", *v) for v in vecs]
    queries = [rand_vec(128, rng) for _ in range(3)]
    fast, slow = fp.cosine_blobs(blobs, queries), fp._cosine_blobs_py(blobs, queries)
    for a, b in zip(fast, slow):
        assert max(abs(x - y) for x, y in zip(a, b)) < 1e-6


@pytest.mark.skipif(not fp.HAVE_FAST, reason="extension not built")
def test_minhash_matches_the_python_twin():
    text = "the quick brown fox jumps over the lazy dog again and again"
    assert fp.minhash(text, 64, 3) == fp._minhash_py(text, 64, 3)


@pytest.mark.skipif(not fp.HAVE_FAST, reason="extension not built")
def test_top_k_matches_heapq():
    import heapq
    rng = random.Random(3)
    vals = [rng.random() for _ in range(2000)]
    expected = [i for i, _ in heapq.nlargest(12, enumerate(vals), key=lambda p: p[1])]
    assert fp.top_k(vals, 12) == expected


# --- behaviour that must hold either way -------------------------------------


def test_cosine_of_a_vector_with_itself_is_one():
    v = [0.3, 0.5, 0.1, 0.9]
    blob = struct.pack(f"{len(v)}f", *v)
    assert fp.cosine_blobs([blob], [v])[0][0] == pytest.approx(1.0, abs=1e-6)


def test_orthogonal_vectors_score_zero():
    v = [1.0, 0.0]
    assert fp.cosine_blobs([struct.pack("2f", *v)], [[0.0, 1.0]])[0][0] == \
        pytest.approx(0.0, abs=1e-6)


def test_a_zero_vector_does_not_divide_by_zero():
    assert fp.cosine_blobs([struct.pack("2f", 0.0, 0.0)], [[1.0, 1.0]])[0][0] == 0.0


def test_top_k_handles_k_larger_than_the_input():
    assert len(fp.top_k([0.1, 0.2], 10)) == 2


def test_top_k_of_nothing_is_nothing():
    assert fp.top_k([], 5) == []
    assert fp.top_k([1.0], 0) == []


def test_identical_text_has_identical_signatures():
    assert fp.minhash("same words here", 64, 3) == fp.minhash("same words here", 64, 3)


def test_signature_similarity_is_one_for_identical_and_low_for_unrelated():
    a = fp.minhash("invoice reconciliation for mid size companies", 128, 3)
    b = fp.minhash("invoice reconciliation for mid size companies", 128, 3)
    c = fp.minhash("a browser extension that changes tab colours", 128, 3)
    assert fp.signature_similarity(a, b) == 1.0
    assert fp.signature_similarity(a, c) < 0.3


def test_empty_text_does_not_crash():
    assert len(fp.minhash("", 32, 3)) == 32


# --- near-duplicate detection ------------------------------------------------


def test_a_repost_is_caught():
    """The case that motivates this: one launch, three sites, three embeddings."""
    texts = {
        "a": "I built an AI tool that reconciles invoices for mid-size companies",
        "b": "I built an AI tool that reconciles invoices for mid-size companies!",
        "c": "Show HN: a browser extension that changes your tab colours",
    }
    dupes = find_duplicates(texts)
    assert "b" in dupes and dupes["b"][0] == "a"
    assert "c" not in dupes


def test_the_first_occurrence_is_kept_as_the_original():
    texts = {"first": "identical text here for testing purposes",
             "second": "identical text here for testing purposes"}
    assert find_duplicates(texts)["second"][0] == "first"


def test_unrelated_documents_are_never_paired():
    texts = {str(i): f"completely different subject number {i} with distinct words"
             for i in range(20)}
    assert find_duplicates(texts) == {}


def test_a_paraphrase_is_not_caught_and_that_is_correct():
    """Word shingles catch reposts and near-verbatim copies, not rewrites. Paraphrase
    similarity is what the embedding stage is for, and claiming otherwise here would
    be overselling the method."""
    texts = {
        "a": "I built an AI tool that reconciles invoices for mid-size companies",
        "b": "We created software using machine learning to match supplier bills",
    }
    assert find_duplicates(texts) == {}


def test_threshold_is_respected():
    """Banding is derived from the threshold. Without that the threshold silently
    does not work at low values: the pair is filtered correctly but LSH never
    surfaces it to be compared in the first place."""
    texts = {"a": "one two three four five six seven eight",
             "b": "one two three four five six seven nine"}
    assert find_duplicates(texts, threshold=0.99) == {}
    assert "b" in find_duplicates(texts, threshold=0.3)


def test_band_count_tracks_the_requested_threshold():
    from vc_alpha.dedup import bands_for
    assert bands_for(0.3) > bands_for(0.9), "a looser threshold needs more bands"
