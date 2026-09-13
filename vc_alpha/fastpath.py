"""Dispatch to the C++ extension, with a pure-Python twin for every operation.

The twins are not dead weight. They are three things at once:

  1. **The specification.** Tests assert the two implementations agree on identical
     inputs. A rewrite you cannot check against the original is one you cannot
     trust, and "it looked right" is not a correctness argument for numeric code.
  2. **The fallback.** A wheel installed on a machine with no compiler still works,
     just slower. Requiring a build toolchain to run a deal-sourcing tool would
     lose most of the people meant to use it.
  3. **The readable version.** When the C++ is wrong, the Python says what it was
     supposed to do.

`HAVE_FAST` reports which path is live, and the app surfaces it so a slow run has
a visible explanation rather than being a mystery.
"""

from __future__ import annotations

import math
import re

try:
    from vc_alpha import _fastops  # type: ignore
    HAVE_FAST = True
except ImportError:  # pragma: no cover - depends on the build environment
    _fastops = None
    HAVE_FAST = False

_WORD = re.compile(r"[a-z0-9]+")


# --- cosine ------------------------------------------------------------------


def cosine_matrix(matrix: list[list[float]], query: list[float]) -> list[float]:
    """Cosine of `query` against every row of `matrix`.

    Kept for callers holding plain Python lists. The pipeline does not use it —
    stage 2 goes through `cosine_blobs`, which reads the packed bytes sqlite
    already returns and measured 43x against 2x for this shape.

    The C++ path here needs numpy to hand over a contiguous buffer. numpy is not a
    dependency, because adding one for a function that is not on the hot path is a
    poor trade, so this quietly falls back when it is absent.
    """
    if HAVE_FAST:
        try:
            import numpy as np
        except ImportError:
            return _cosine_matrix_py(matrix, query)
        return list(_fastops.cosine_matrix(
            np.asarray(matrix, dtype=np.float64),
            np.asarray(query, dtype=np.float64),
        ))
    return _cosine_matrix_py(matrix, query)


def _cosine_matrix_py(matrix: list[list[float]], query: list[float]) -> list[float]:
    qnorm = math.sqrt(sum(q * q for q in query))
    if qnorm == 0.0:
        return [0.0] * len(matrix)
    out = []
    for row in matrix:
        dot = norm = 0.0
        for v, q in zip(row, query):
            dot += v * q
            norm += v * v
        norm = math.sqrt(norm)
        out.append(dot / (norm * qnorm) if norm > 0 else 0.0)
    return out


def cosine_blobs(blobs: list[bytes], queries: list[list[float]]) -> list[list[float]]:
    """Cosine of every stored vector against every thesis vector.

    Takes embeddings in the packed form sqlite already returns, so no Python float
    objects are created for the vectors at all. The list-of-lists binding measured
    only 2x faster than pure Python because marshalling dominated; reading the bytes
    directly measures 43x.
    """
    if HAVE_FAST:
        return [list(r) for r in _fastops.cosine_blobs(blobs, queries)]
    return _cosine_blobs_py(blobs, queries)


def _cosine_blobs_py(blobs: list[bytes], queries: list[list[float]]) -> list[list[float]]:
    import struct
    qnorms = [math.sqrt(sum(v * v for v in q)) for q in queries]
    out = []
    for blob in blobs:
        vec = struct.unpack(f"{len(blob) // 4}f", blob)
        norm = math.sqrt(sum(v * v for v in vec))
        row = []
        for q, qn in zip(queries, qnorms):
            if not norm or not qn or len(q) != len(vec):
                row.append(0.0)
            else:
                row.append(sum(a * b for a, b in zip(vec, q)) / (norm * qn))
        out.append(row)
    return out


# --- minhash -----------------------------------------------------------------


def _fnv1a(s: str, seed: int) -> int:
    h = (1469598103934665603 ^ seed) & 0xFFFFFFFFFFFFFFFF
    for b in s.encode():
        h = ((h ^ b) * 1099511628211) & 0xFFFFFFFFFFFFFFFF
    return h


def _shingles_py(text: str, k: int) -> list[str]:
    words = _WORD.findall(text.lower())
    if len(words) < k:
        return [" ".join(words)] if words else []
    return [" ".join(words[i:i + k]) for i in range(len(words) - k + 1)]


def minhash(text: str, perms: int = 128, k: int = 3) -> list[int]:
    """MinHash signature over word shingles.

    Word shingles rather than characters: a repost usually preserves the words
    while reflowing whitespace and punctuation.
    """
    if HAVE_FAST:
        return list(_fastops.minhash(text, perms, k))
    return _minhash_py(text, perms, k)


def _minhash_py(text: str, perms: int, k: int) -> list[int]:
    sig = [0xFFFFFFFFFFFFFFFF] * perms
    for sh in _shingles_py(text, k):
        for p in range(perms):
            h = _fnv1a(sh, (p * 0x9E3779B97F4A7C15) & 0xFFFFFFFFFFFFFFFF)
            if h < sig[p]:
                sig[p] = h
    return sig


def signature_similarity(a: list[int], b: list[int]) -> float:
    """Estimated Jaccard similarity: the fraction of positions that agree."""
    if HAVE_FAST:
        return _fastops.signature_similarity(a, b)
    if not a or len(a) != len(b):
        return 0.0
    return sum(x == y for x, y in zip(a, b)) / len(a)


def band_hashes(signature: list[int], bands: int = 16) -> list[int]:
    """LSH band hashes, so near-duplicates can be found by grouping."""
    if HAVE_FAST:
        return list(_fastops.band_hashes(signature, bands))
    if not signature or bands <= 0 or bands > len(signature):
        return []
    rows = len(signature) // bands
    out = []
    for b in range(bands):
        h = 1469598103934665603
        for r in range(rows):
            h = ((h ^ signature[b * rows + r]) * 1099511628211) & 0xFFFFFFFFFFFFFFFF
        out.append(h)
    return out


# --- selection ---------------------------------------------------------------


def top_k(values: list[float], k: int) -> list[int]:
    """Indices of the k largest values, descending. O(N log K), not O(N log N)."""
    if HAVE_FAST:
        return list(_fastops.top_k(list(values), k))
    if k <= 0 or not values:
        return []
    import heapq
    return [i for i, _ in heapq.nlargest(
        min(k, len(values)), enumerate(values), key=lambda p: p[1])]
