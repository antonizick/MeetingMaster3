"""Match a meeting's speakers to known people (pure Python).

The score of a speaker against a person is the **maximum** cosine similarity between the
speaker's centroid and that person's stored embeddings (one per enrolled meeting). The maximum
keeps recordings made in different conditions (a headset one week, a laptop microphone the next)
useful instead of blurring them into one average; ADR-0015 has the experiment.

Suggestions use a one-to-one (Hungarian) assignment that maximises the total of
``score - threshold`` over the accepted pairs, so two speakers never get the same person. An
assigned person is ``suggested`` only when the score reaches ``threshold`` and beats the speaker's
best *other* candidate by at least ``margin``; ambiguous speakers (for example one person split
into two labels by the diarizer) get a ranked list but no suggestion. The user always confirms.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from meetingmaster3.speakers.vectors import Vector, cosine, weighted_mean

Method = Literal["max", "mean"]
DEFAULT_THRESHOLD = 0.6
DEFAULT_MARGIN = 0.1
TOP_K = 3


@dataclass(frozen=True)
class KnownPerson:
    person_id: str
    display_name: str
    embeddings: Sequence[Vector]


@dataclass(frozen=True)
class Candidate:
    person_id: str
    display_name: str
    score: float
    suggested: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "person_id": self.person_id,
            "name": self.display_name,
            "score": round(self.score, 3),
            "suggested": self.suggested,
        }


def person_score(centroid: Vector, person: KnownPerson, method: Method = "max") -> float:
    if not person.embeddings:
        return -1.0
    if method == "mean":
        return cosine(centroid, weighted_mean(person.embeddings, [1.0] * len(person.embeddings)))
    return max(cosine(centroid, e) for e in person.embeddings)


def hungarian(cost: list[list[float]]) -> list[int]:
    """Minimum-cost assignment for an ``n x m`` matrix with ``n <= m``: the column of each row.

    The O(n^2 m) shortest-augmenting-path form of the Hungarian (Kuhn-Munkres) algorithm."""
    n = len(cost)
    if n == 0:
        return []
    m = len(cost[0])
    if m < n or any(len(r) != m for r in cost):
        raise ValueError("need a rectangular matrix with at least as many columns as rows")
    inf = float("inf")
    u = [0.0] * (n + 1)
    v = [0.0] * (m + 1)
    p = [0] * (m + 1)  # p[j]: row (1-based) matched to column j
    way = [0] * (m + 1)
    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [inf] * (m + 1)
        used = [False] * (m + 1)
        while True:
            used[j0] = True
            i0, delta, j1 = p[j0], inf, 0
            for j in range(1, m + 1):
                if not used[j]:
                    cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j], way[j] = cur, j0
                    if minv[j] < delta:
                        delta, j1 = minv[j], j
            for j in range(m + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break
    out = [-1] * n
    for j in range(1, m + 1):
        if p[j]:
            out[p[j] - 1] = j - 1
    return out


def assign(scores: dict[str, dict[str, float]], threshold: float) -> dict[str, str]:
    """One-to-one label → person assignment over pairs scoring at least ``threshold``."""
    labels = list(scores)
    people = sorted({p for row in scores.values() for p in row})
    if not labels or not people:
        return {}
    forbidden = 1e6
    # Columns: the people, then one "no match" column per label (gain 0).
    cost = [
        [
            -(scores[lbl].get(p, -1.0) - threshold)
            if scores[lbl].get(p, -1.0) >= threshold
            else forbidden
            for p in people
        ]
        + [0.0] * len(labels)
        for lbl in labels
    ]
    out: dict[str, str] = {}
    for lbl, col in zip(labels, hungarian(cost), strict=True):
        if col < len(people) and cost[labels.index(lbl)][col] < forbidden:
            out[lbl] = people[col]
    return out


def match_speakers(
    centroids: dict[str, Vector | None],
    people: Sequence[KnownPerson],
    *,
    threshold: float = DEFAULT_THRESHOLD,
    margin: float = DEFAULT_MARGIN,
    method: Method = "max",
    top_k: int = TOP_K,
) -> dict[str, list[Candidate]]:
    """Ranked candidates per label (best first), at most ``top_k``, with the suggestion flagged."""
    by_id = {p.person_id: p for p in people if p.embeddings}
    scores: dict[str, dict[str, float]] = {
        label: {pid: person_score(vec, person, method) for pid, person in by_id.items()}
        for label, vec in centroids.items()
        if vec is not None
    }
    chosen = assign(scores, threshold)
    out: dict[str, list[Candidate]] = {}
    for label in centroids:
        row = scores.get(label, {})
        ranked = sorted(row.items(), key=lambda kv: (-kv[1], by_id[kv[0]].display_name))
        pick = chosen.get(label)
        suggested_id = None
        if pick is not None:
            others = [s for pid, s in row.items() if pid != pick]
            if row[pick] - max(others, default=-1.0) >= margin:
                suggested_id = pick
        # A suggestion beats every other candidate by ``margin``, so it is always ranked first.
        out[label] = [
            Candidate(pid, by_id[pid].display_name, score, pid == suggested_id)
            for pid, score in ranked[:top_k]
        ]
    return out
