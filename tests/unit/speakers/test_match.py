"""Matching on synthetic vectors: threshold, margin, one-to-one assignment, max vs mean."""

from __future__ import annotations

import itertools
import math
import random

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from meetingmaster3.speakers.match import (
    KnownPerson,
    assign,
    hungarian,
    match_speakers,
    person_score,
)
from meetingmaster3.speakers.vectors import (
    cosine,
    dot,
    from_blob,
    normalize,
    to_blob,
    weighted_mean,
)

DIM = 16


def unit(i: int) -> list[float]:
    v = [0.0] * DIM
    v[i] = 1.0
    return v


def blend(a: list[float], b: list[float], cos: float) -> list[float]:
    """A unit vector whose cosine with ``a`` is ``cos`` (``a`` ⟂ ``b``, both unit)."""
    s = math.sqrt(1 - cos * cos)
    return [cos * x + s * y for x, y in zip(a, b, strict=True)]


def person(pid: str, *vecs: list[float]) -> KnownPerson:
    return KnownPerson(pid, pid.title(), list(vecs))


# -- vectors -------------------------------------------------------------------------------------


def test_vector_helpers() -> None:
    assert cosine([1, 0], [0, 1]) == 0.0
    assert cosine([0, 0], [1, 0]) == 0.0
    assert math.isclose(cosine([1, 1], [2, 2]), 1.0)
    assert normalize([3, 4]) == [0.6, 0.8]
    with pytest.raises(ValueError, match="zero"):
        normalize([0, 0])
    with pytest.raises(ValueError, match="non-finite"):
        normalize([math.inf, 0])
    with pytest.raises(ValueError, match="dimension"):
        dot([1], [1, 2])
    assert weighted_mean([[1, 0], [0, 1]], [3, 1]) == normalize([3, 1])
    with pytest.raises(ValueError):
        weighted_mean([], [])
    with pytest.raises(ValueError, match="dimensions"):
        weighted_mean([[1, 0], [1]], [1, 1])


def test_blob_round_trip_is_float32() -> None:
    v = normalize([random.Random(1).gauss(0, 1) for _ in range(256)])  # noqa: S311
    blob = to_blob(v)
    assert len(blob) == 256 * 4
    back = from_blob(blob)
    assert all(math.isclose(a, b, rel_tol=1e-6, abs_tol=1e-7) for a, b in zip(v, back, strict=True))


# -- Hungarian -----------------------------------------------------------------------------------


def brute_force(cost: list[list[float]]) -> float:
    n, m = len(cost), len(cost[0])
    return min(
        sum(cost[i][c] for i, c in enumerate(cols)) for cols in itertools.permutations(range(m), n)
    )


@settings(max_examples=60, deadline=None)
@given(
    st.integers(1, 4).flatmap(
        lambda n: st.integers(n, 5).flatmap(
            lambda m: st.lists(
                st.lists(st.floats(-5, 5, allow_nan=False), min_size=m, max_size=m),
                min_size=n,
                max_size=n,
            )
        )
    )
)
def test_hungarian_is_optimal(cost: list[list[float]]) -> None:
    cols = hungarian(cost)
    assert len(set(cols)) == len(cols)  # one-to-one
    total = sum(cost[i][c] for i, c in enumerate(cols))
    assert math.isclose(total, brute_force(cost), abs_tol=1e-9)


def test_hungarian_edge_cases() -> None:
    assert hungarian([]) == []
    with pytest.raises(ValueError):
        hungarian([[1.0], [2.0]])  # more rows than columns


def test_assign_only_pairs_above_threshold() -> None:
    scores = {"A": {"p": 0.9, "q": 0.2}, "B": {"p": 0.8, "q": 0.5}}
    assert assign(scores, 0.6) == {"A": "p"}  # B's only candidate above 0.6 is taken
    assert assign(scores, 0.4) == {"A": "p", "B": "q"}
    assert assign({}, 0.5) == {}
    assert assign({"A": {}}, 0.5) == {}


# -- match_speakers --------------------------------------------------------------------------------


def test_threshold_and_ranking() -> None:
    alice, bob = unit(0), unit(1)
    people = [person("alice", alice), person("bob", bob)]
    near_alice = blend(alice, unit(5), 0.8)
    far = blend(alice, unit(6), 0.5)
    out = match_speakers({"S0": near_alice, "S1": far, "S2": None}, people, threshold=0.6)
    assert [c.person_id for c in out["S0"]] == ["alice", "bob"]
    assert out["S0"][0].suggested and math.isclose(out["S0"][0].score, 0.8)
    assert not out["S0"][1].suggested
    assert not any(c.suggested for c in out["S1"])  # 0.5 < threshold: listed, not suggested
    assert out["S2"] == []  # no embedding (too little speech)
    assert out["S0"][0].to_dict() == {
        "person_id": "alice", "name": "Alice", "score": 0.8, "suggested": True,
    }  # fmt: skip


def test_margin_over_second_best() -> None:
    alice, bob = unit(0), unit(1)
    # Equally close to both people: ambiguous, so no suggestion.
    between = normalize([a + b for a, b in zip(alice, bob, strict=True)])
    out = match_speakers({"S0": between}, [person("alice", alice), person("bob", bob)])
    assert out["S0"][0].score >= 0.7 and not any(c.suggested for c in out["S0"])
    out = match_speakers({"S0": between}, [person("alice", alice), person("bob", bob)], margin=0.0)
    assert out["S0"][0].suggested


def test_two_speakers_never_get_the_same_person() -> None:
    alice, bob = unit(0), unit(1)
    s0 = blend(alice, unit(5), 0.95)
    s1 = blend(alice, bob, 0.75)  # also close to Alice, and to Bob (0.66)
    out = match_speakers({"S0": s0, "S1": s1}, [person("alice", alice), person("bob", bob)])
    suggested = {
        lbl: next((c.person_id for c in cs if c.suggested), None) for lbl, cs in out.items()
    }
    assert suggested["S0"] == "alice"
    # S1's best candidate went to S0 and Bob does not beat Alice by the margin: no suggestion,
    # rather than a second "Alice" or a wrong "Bob".
    assert suggested["S1"] is None
    assert [c.person_id for c in out["S1"]] == ["alice", "bob"]


def test_assignment_maximises_total_score() -> None:
    alice, bob = unit(0), unit(1)
    s0 = blend(alice, bob, 0.9)  # alice .90, bob .44
    s1 = blend(bob, alice, 0.85)  # bob .85, alice .53
    out = match_speakers({"S0": s0, "S1": s1}, [person("alice", alice), person("bob", bob)])
    assert out["S0"][0].person_id == "alice" and out["S0"][0].suggested
    assert out["S1"][0].person_id == "bob" and out["S1"][0].suggested


def test_max_versus_mean_scoring() -> None:
    headset, laptop = unit(0), unit(1)  # one person recorded in two conditions
    alice = person("alice", headset, laptop)
    probe = blend(laptop, unit(4), 0.9)
    assert math.isclose(person_score(probe, alice, "max"), 0.9)
    assert person_score(probe, alice, "mean") < 0.7  # the average blurs the two conditions
    out = match_speakers({"S0": probe}, [alice], method="mean", threshold=0.7)
    assert not out["S0"][0].suggested
    assert match_speakers({"S0": probe}, [alice], threshold=0.7)["S0"][0].suggested
    assert person_score(probe, KnownPerson("x", "X", [])) == -1.0


def test_top_k_and_people_without_embeddings() -> None:
    people = [person(f"p{i}", unit(i)) for i in range(5)] + [KnownPerson("empty", "E", [])]
    out = match_speakers({"S0": unit(0)}, people, top_k=2)
    assert [c.person_id for c in out["S0"]] == ["p0", "p1"]
    assert match_speakers({"S0": unit(0)}, []) == {"S0": []}
