"""Recommend next tracks and evaluate whole sets."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional

from .library import Library
from .models import Track
from .scoring import INTENTS, TransitionScore, score_transition
from .transitions import Technique, recommend_technique


@dataclass
class Recommendation:
    score: TransitionScore
    technique: Technique

    @property
    def track(self) -> Track:
        return self.score.b


def _direction_ok(delta: Optional[float], intent: str) -> bool:
    if delta is None:
        return True
    if intent == "boost":
        return delta > 0.25
    if intent == "lower":
        return delta < -0.25
    return abs(delta) <= 1.0


def recommend_next(current: Track, library: Library, intent: str, n: int = 5,
                   exclude: Iterable[str] = ()) -> List[Recommendation]:
    """Top-n tracks to play after `current` for the given intent."""
    if intent not in INTENTS:
        raise ValueError(f"intent must be one of {sorted(INTENTS)}")
    skip = set(exclude) | {current.id}
    scored = []
    for cand in library:
        if cand.id in skip or not cand.is_scorable:
            continue
        ts = score_transition(current, cand, intent)
        if not _direction_ok(ts.energy_delta, intent):
            continue
        scored.append(ts)
    scored.sort(key=lambda s: s.total, reverse=True)
    return [Recommendation(s, recommend_technique(s)) for s in scored[:n]]


def recommend_all(current: Track, library: Library, n: int = 3, exclude: Iterable[str] = ()) -> dict:
    return {intent: recommend_next(current, library, intent, n, exclude) for intent in ("boost", "maintain", "lower")}


def evaluate_set(tracks: List[Track]) -> dict:
    """Score each consecutive transition in a set and summarise the energy arc."""
    transitions = []
    for a, b in zip(tracks, tracks[1:]):
        ts = score_transition(a, b)
        transitions.append(Recommendation(ts, recommend_technique(ts)))
    scores = [r.score.total for r in transitions]
    energies = [t.energy for t in tracks if t.energy is not None]
    return {
        "transitions": transitions,
        "mean": round(sum(scores) / len(scores), 1) if scores else None,
        "weakest": min(transitions, key=lambda r: r.score.total) if transitions else None,
        "energy_curve": energies,
    }
