"""Small vector helpers in pure Python (embeddings are 256 floats; numpy is not a core dependency).

Embeddings are stored as little-endian float32 BLOBs (``array('f')``).
"""

from __future__ import annotations

import math
import sys
from array import array
from collections.abc import Sequence

Vector = list[float]


def norm(v: Sequence[float]) -> float:
    return math.sqrt(math.fsum(x * x for x in v))


def normalize(v: Sequence[float]) -> Vector:
    """``v`` scaled to unit length. Raises ``ValueError`` for a zero or non-finite vector."""
    n = norm(v)
    if not math.isfinite(n) or n == 0.0:
        raise ValueError("cannot normalise a zero or non-finite vector")
    return [x / n for x in v]


def dot(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) != len(b):
        raise ValueError(f"dimension mismatch: {len(a)} != {len(b)}")
    return math.fsum(x * y for x, y in zip(a, b, strict=True))


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    na, nb = norm(a), norm(b)
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot(a, b) / (na * nb)


def weighted_mean(vectors: Sequence[Sequence[float]], weights: Sequence[float]) -> Vector:
    """The weighted mean of ``vectors``, L2-normalised (a centroid)."""
    if not vectors or len(vectors) != len(weights):
        raise ValueError("need one weight per vector and at least one vector")
    dim = len(vectors[0])
    total = [0.0] * dim
    for v, w in zip(vectors, weights, strict=True):
        if len(v) != dim:
            raise ValueError("vectors have different dimensions")
        for i, x in enumerate(v):
            total[i] += w * x
    return normalize(total)


def to_blob(v: Sequence[float]) -> bytes:
    data = array("f", v)
    if sys.byteorder != "little":  # pragma: no cover - big-endian hosts
        data.byteswap()
    return data.tobytes()


def from_blob(blob: bytes) -> Vector:
    data = array("f")
    data.frombytes(blob)
    if sys.byteorder != "little":  # pragma: no cover - big-endian hosts
        data.byteswap()
    return list(data)
